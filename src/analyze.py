"""
File: analyze.py
Author: citrus
Abstract:
ベンチマーク計測結果（レイテンシ・スループット・機能検証）を集計し，
比較グラフと集計CSVを docs/figures/ へ出力する
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Final

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

# ── 定数 ────────────────────────────────────────────────────────────────────

# 計測結果は {results-dir}/{workload}/results/{storage}/op_results.csv，
# 機能検証結果は {results-dir}/{workload}/results/{storage}/feature_results.csv
# に格納．results/ は .gitignore 対象のため読み取り専用として扱い，このスクリプトからは
# 一切書き込まない．
# results/trial1 はコンテナイメージのタグ未固定で計測したため，性能データと機能検証
# データのバージョンが揃っていない．results/trial2 はタグを固定して両方を揃えて
# 取り直した版のため，これ以降はデフォルトとして正とする．
_DEFAULT_RESULTS_DIR: Final[Path] = Path("results/trial2")

_OUTPUT_DIR: Final[Path] = Path("docs/figures")

_WORKLOADS: Final[list[str]] = ["small", "large"]
_STORAGES: Final[list[str]] = ["minio", "seaweedfs", "garage"]
_OPERATIONS: Final[list[str]] = ["PUT", "GET", "DELETE"]
_FEATURES: Final[list[str]] = ["HEAD", "TAGGING", "BUCKET_POLICY", "ACL"]

_WORKLOAD_LABELS: Final[dict[str, str]] = {
    "small": "small\n(1MB×1,000)",
    "large": "large\n(100MB×10)",
}
_STORAGE_LABELS: Final[dict[str, str]] = {
    "minio": "MinIO",
    "seaweedfs": "SeaweedFS",
    "garage": "Garage",
}

# dataviz スキルの検証済みカテゴリカルパレット（先頭3色）を固定順で使う．
# 3ストレージのみのため all-pairs ゲートを通過する slot1-3 を採用し，
# どのグラフでも同じストレージには同じ色を割り当てる（色は識別子固定）．
_STORAGE_COLORS: Final[dict[str, str]] = {
    "minio": "#2a78d6",  # slot1 blue
    "seaweedfs": "#eb6834",  # slot2 orange
    "garage": "#1baf7a",  # slot3 aqua
}

# 状態色（Pass/Fail）．カテゴリカル色とは別枠のため識別子との衝突はない．
_STATUS_GOOD: Final[str] = "#0ca30c"
_STATUS_CRITICAL: Final[str] = "#d03b3b"

# op_results.csv の列型を明示する．DELETEの throughput_mbps は
# 「旧CSV = 意味のない数値（修正前の計測コードによる）」「新CSV = 空」の
# 両方があり得るため，schema_overrides でFloat64に固定し，pl.concat時の
# 型不一致による例外を防ぐ．
_OP_RESULTS_SCHEMA: Final[dict[str, Any]] = {
    "storage": pl.Utf8,
    "operation": pl.Utf8,
    "workload": pl.Utf8,
    "trial": pl.Int64,
    "key": pl.Utf8,
    "size_bytes": pl.Int64,
    "elapsed_ms": pl.Float64,
    "throughput_mbps": pl.Float64,
}

_FEATURE_RESULTS_SCHEMA: Final[dict[str, Any]] = {
    "storage": pl.Utf8,
    "feature": pl.Utf8,
    "supported": pl.Boolean,
    "error": pl.Utf8,
}


def _setup_japanese_font() -> None:
    """日本語ラベルの文字化け（豆腐）対策を行う．

    macOS標準搭載のHiragino Sansを優先フォントに指定する．
    """
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False


def _lighten(hex_color: str, amount: float) -> str:
    """16進数カラーコードを白へ向けて明るくする．

    レイテンシ比較グラフでP50（濃色）とP99（淡色）を同一ストレージの
    色相の濃淡で描き分けるために使う（色は識別子=ストレージのまま変えない）．

    Args:
        hex_color: 元の16進数カラーコード（例: "#2a78d6"）．
        amount: 白へ寄せる比率．0で元の色，1で白になる．

    Returns:
        明るくした16進数カラーコード．
    """
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


# ── データ読み込み ────────────────────────────────────────────────────────


def load_op_results(results_dir: Path) -> pl.DataFrame:
    """全ワークロード・全ストレージのオペレーション計測結果を読み込む．

    Args:
        results_dir: 計測結果一式が格納されたディレクトリ
            （`{results_dir}/{workload}/results/{storage}/op_results.csv`）．

    Returns:
        `storage,operation,workload,trial,key,size_bytes,elapsed_ms,
        throughput_mbps` 列を持つ結合済みDataFrame．
    """
    frames = [
        pl.read_csv(
            results_dir / workload / "results" / storage / "op_results.csv",
            schema_overrides=_OP_RESULTS_SCHEMA,
        )
        for workload in _WORKLOADS
        for storage in _STORAGES
    ]
    return pl.concat(frames)


def load_feature_results(results_dir: Path) -> pl.DataFrame:
    """全ワークロード・全ストレージの機能検証結果を読み込む．

    機能検証は専用の検証キー（`feature-probe.parquet`）1個に対して行われ，
    ワークロード（small／large）には依存しないため，本来は同一ストレージなら
    どちらのワークロードで読んでも同じ結果になるはずである．念のため両方を
    読み込んで統合し，ワークロード間で `supported` が食い違っていないか検証する．

    Args:
        results_dir: 計測結果一式が格納されたディレクトリ
            （`{results_dir}/{workload}/results/{storage}/feature_results.csv`）．

    Returns:
        `storage,feature,supported,error` 列を持つ，ストレージ・機能ごとに
        1行へ統合されたDataFrame．

    Raises:
        ValueError: 同じストレージ・機能でワークロード間の `supported` が
            食い違う場合（機能検証がワークロードに依存してしまっている異常事態）．
    """
    frames = [
        pl.read_csv(
            results_dir / workload / "results" / storage / "feature_results.csv",
            schema_overrides=_FEATURE_RESULTS_SCHEMA,
        )
        for workload in _WORKLOADS
        for storage in _STORAGES
    ]
    combined = pl.concat(frames)

    inconsistent = combined.group_by(["storage", "feature"]).agg(
        pl.col("supported").n_unique().alias("n_unique")
    )
    if bool((inconsistent["n_unique"] > 1).any()):
        raise ValueError(
            "ワークロード間で機能検証結果(supported)が食い違っています: "
            f"{inconsistent.filter(pl.col('n_unique') > 1).to_dicts()}"
        )

    return combined.unique(subset=["storage", "feature"], keep="first").sort(
        ["storage", "feature"]
    )


# ── 集計 ────────────────────────────────────────────────────────────────────


def summarize_latency(op_results: pl.DataFrame) -> pl.DataFrame:
    """ワークロード×ストレージ×オペレーション粒度でレイテンシを集計する．

    `docs/benchmark_spec.md` の集計指標に従い，P50 / P95 / P99 を算出する．
    DELETEもレイテンシ指標としては有効なため含める（スループットのみ除外）．

    Args:
        op_results: `load_op_results` で読み込んだ計測結果．

    Returns:
        `workload,storage,operation,p50_ms,p95_ms,p99_ms` 列を持つ集計結果．
    """
    return (
        op_results.group_by(["workload", "storage", "operation"])
        .agg(
            p50_ms=pl.col("elapsed_ms").quantile(0.5, interpolation="linear"),
            p95_ms=pl.col("elapsed_ms").quantile(0.95, interpolation="linear"),
            p99_ms=pl.col("elapsed_ms").quantile(0.99, interpolation="linear"),
        )
        .sort(["workload", "operation", "storage"])
    )


def summarize_throughput(op_results: pl.DataFrame) -> pl.DataFrame:
    """ワークロード×ストレージ×オペレーション粒度でスループットを集計する．

    DELETEはボディ転送がなくスループットという指標自体が意味を持たないため，
    集計から必ず除外する（`src/benchmark.py` の `measure_delete` の方針に合わせる）．

    Args:
        op_results: `load_op_results` で読み込んだ計測結果．

    Returns:
        `workload,storage,operation,mean_mbps,max_mbps,min_mbps` 列を持つ
        集計結果（PUT・GETのみ）．
    """
    return (
        op_results.filter(pl.col("operation") != "DELETE")
        .group_by(["workload", "storage", "operation"])
        .agg(
            mean_mbps=pl.col("throughput_mbps").mean(),
            max_mbps=pl.col("throughput_mbps").max(),
            min_mbps=pl.col("throughput_mbps").min(),
        )
        .sort(["workload", "operation", "storage"])
    )


def pivot_feature_table(feature_results: pl.DataFrame) -> pl.DataFrame:
    """機能検証結果をストレージ×機能のクロス集計表に変換する．

    Args:
        feature_results: `load_feature_results` で読み込んだ検証結果．

    Returns:
        `feature` 列と各ストレージ列（真偽値）を持つ表．行は `_FEATURES` の順．
    """
    pivoted = feature_results.pivot(on="storage", index="feature", values="supported")
    order = pl.DataFrame({"feature": _FEATURES})
    return order.join(pivoted, on="feature", how="left").select(
        ["feature", *_STORAGES]
    )


# ── グラフ描画 ──────────────────────────────────────────────────────────────


def plot_latency_comparison(latency: pl.DataFrame, out_path: Path) -> None:
    """ワークロード別・オペレーション別のレイテンシ比較グラフを描画する．

    2ワークロード×3オペレーションの小さな図を並べ，各図内で3ストレージを
    横並びにする．P50は濃色の棒，P99は同じストレージ色を明るくした棒で表し，
    色（=ストレージの識別）を変えずに指標の違いを濃淡で示す．
    smallとlargeでスケール差が大きいため，対数軸ではなくワークロードごとに
    パネルを分けることでスケールの違いを吸収する．

    Args:
        latency: `summarize_latency` の出力．
        out_path: 出力先PNGパス．
    """
    x = np.arange(len(_STORAGES))
    bar_width = 0.32
    gap = 0.04

    fig, axes = plt.subplots(
        len(_WORKLOADS), len(_OPERATIONS), figsize=(13, 7.5), squeeze=False
    )

    for row, workload in enumerate(_WORKLOADS):
        for col, operation in enumerate(_OPERATIONS):
            ax = axes[row][col]
            rows = {
                r["storage"]: r
                for r in latency.filter(
                    (pl.col("workload") == workload)
                    & (pl.col("operation") == operation)
                ).to_dicts()
            }
            p50_vals = [rows[s]["p50_ms"] for s in _STORAGES]
            p99_vals = [rows[s]["p99_ms"] for s in _STORAGES]
            colors = [_STORAGE_COLORS[s] for s in _STORAGES]
            light_colors = [_lighten(c, 0.55) for c in colors]

            ax.bar(x - (bar_width + gap) / 2, p50_vals, width=bar_width, color=colors)
            ax.bar(
                x + (bar_width + gap) / 2, p99_vals, width=bar_width, color=light_colors
            )
            ax.set_xticks(x)
            ax.set_xticklabels([_STORAGE_LABELS[s] for s in _STORAGES], fontsize=9)
            ax.set_title(f"{workload} / {operation}", fontsize=11)
            if col == 0:
                ax.set_ylabel("レイテンシ (ms)")
            ax.grid(axis="y", color="#e1e0d9", linewidth=1, zorder=0)
            ax.set_axisbelow(True)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

    storage_handles = [
        mpatches.Patch(color=_STORAGE_COLORS[s], label=_STORAGE_LABELS[s])
        for s in _STORAGES
    ]
    shade_handles = [
        mpatches.Patch(facecolor="#52514e", label="P50（濃色）"),
        mpatches.Patch(facecolor="#c3c2b7", label="P99（淡色）"),
    ]
    fig.legend(
        handles=storage_handles + shade_handles,
        loc="upper center",
        ncol=5,
        frameon=False,
        bbox_to_anchor=(0.5, 1.0),
        fontsize=10,
    )
    fig.suptitle(
        "ワークロード別・オペレーション別レイテンシ比較（P50 / P99）",
        fontsize=14,
        y=1.05,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_throughput_comparison(throughput: pl.DataFrame, out_path: Path) -> None:
    """PUT / GETのスループット比較グラフを描画する（DELETEは含めない）．

    オペレーション（PUT・GET）ごとにパネルを分け，各パネル内でワークロード
    （small・large）を横軸，ストレージを色で表す．エラーバーは最小〜最大の
    範囲を示す．PUTとGETでスケールが大きく異なるためパネルを分けている．

    Args:
        throughput: `summarize_throughput` の出力（DELETEを含まない）．
        out_path: 出力先PNGパス．
    """
    operations = ["PUT", "GET"]
    x = np.arange(len(_WORKLOADS))
    bar_width = 0.24
    step = bar_width + 0.03

    fig, axes = plt.subplots(1, len(operations), figsize=(11, 5.0))

    for col, operation in enumerate(operations):
        ax = axes[col]
        subset = throughput.filter(pl.col("operation") == operation)
        for i, storage in enumerate(_STORAGES):
            storage_rows = {
                r["workload"]: r
                for r in subset.filter(pl.col("storage") == storage).to_dicts()
            }
            means = [storage_rows[w]["mean_mbps"] for w in _WORKLOADS]
            err_low = [
                storage_rows[w]["mean_mbps"] - storage_rows[w]["min_mbps"]
                for w in _WORKLOADS
            ]
            err_high = [
                storage_rows[w]["max_mbps"] - storage_rows[w]["mean_mbps"]
                for w in _WORKLOADS
            ]
            offset = (i - 1) * step
            ax.bar(
                x + offset,
                means,
                width=bar_width,
                color=_STORAGE_COLORS[storage],
                label=_STORAGE_LABELS[storage],
                yerr=[err_low, err_high],
                capsize=3,
                error_kw={"ecolor": "#52514e", "elinewidth": 1},
            )
        ax.set_xticks(x)
        ax.set_xticklabels([_WORKLOAD_LABELS[w] for w in _WORKLOADS])
        ax.set_title(f"{operation} スループット", fontsize=12)
        ax.set_ylabel("スループット (MB/s)")
        ax.grid(axis="y", color="#e1e0d9", linewidth=1, zorder=0)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=3,
        frameon=False,
        fontsize=10,
        bbox_to_anchor=(0.5, 0.99),
    )
    fig.suptitle(
        "PUT / GET スループット比較（平均，エラーバーは最小〜最大，DELETEは除く）",
        fontsize=13,
        y=1.08,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.92))
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_feature_table(feature_pivot: pl.DataFrame, out_path: Path) -> None:
    """機能検証結果の一覧表を画像として描画する．

    色に加えて「○ 対応 / × 非対応」の記号とラベルを併記し，色だけに
    依存しない判別を可能にする（状態色は good/critical の固定色を使う）．

    Args:
        feature_pivot: `pivot_feature_table` の出力．
        out_path: 出力先PNGパス．
    """
    rows = feature_pivot.to_dicts()
    cell_text = []
    cell_colors = []
    for row in rows:
        text_row = []
        color_row = []
        for storage in _STORAGES:
            supported = bool(row[storage])
            text_row.append("○ 対応" if supported else "× 非対応")
            color_row.append("#e7f6e7" if supported else "#fbe9e8")
        cell_text.append(text_row)
        cell_colors.append(color_row)

    fig, ax = plt.subplots(figsize=(7.5, 2.4))
    ax.axis("off")
    table = ax.table(
        cellText=cell_text,
        rowLabels=[str(r["feature"]) for r in rows],
        colLabels=[_STORAGE_LABELS[s] for s in _STORAGES],
        cellColours=cell_colors,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 2.1)

    for (row_idx, col_idx), cell in table.get_celld().items():
        if row_idx == 0 or col_idx < 0:
            continue
        text = cell.get_text().get_text()
        cell.get_text().set_color(_STATUS_GOOD if text.startswith("○") else _STATUS_CRITICAL)

    ax.set_title(
        "機能検証結果（HEAD／TAGGING／BUCKET_POLICY／ACL）", fontsize=13, pad=16
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── エントリーポイント ──────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する．

    Returns:
        `results_dir`・`out_dir` を持つ引数オブジェクト．
    """
    parser = argparse.ArgumentParser(
        description="ベンチマーク計測結果を集計し，比較グラフとCSVを出力する．"
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=_DEFAULT_RESULTS_DIR,
        help=(
            "計測結果ディレクトリ（{results-dir}/{workload}/results/{storage}/"
            f"op_results.csv・feature_results.csv を読む．デフォルト: {_DEFAULT_RESULTS_DIR}）"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_OUTPUT_DIR,
        help=f"集計CSV・グラフPNGの出力先ディレクトリ（デフォルト: {_OUTPUT_DIR}）",
    )
    return parser.parse_args()


def main() -> None:
    """集計・グラフ生成のエントリーポイント．

    `--results-dir`（デフォルト results/trial2）配下の計測結果・機能検証結果を
    読み込み，集計CSVとグラフPNGを `--out-dir`（デフォルト docs/figures）へ出力する．
    """
    args = _parse_args()
    results_dir: Path = args.results_dir
    out_dir: Path = args.out_dir

    _setup_japanese_font()
    out_dir.mkdir(parents=True, exist_ok=True)

    op_results = load_op_results(results_dir)
    latency = summarize_latency(op_results)
    throughput = summarize_throughput(op_results)
    latency.write_csv(out_dir / "latency_summary.csv")
    throughput.write_csv(out_dir / "throughput_summary.csv")

    feature_results = load_feature_results(results_dir)
    feature_pivot = pivot_feature_table(feature_results)
    feature_pivot.write_csv(out_dir / "feature_summary.csv")

    plot_latency_comparison(latency, out_dir / "latency_comparison.png")
    plot_throughput_comparison(throughput, out_dir / "throughput_comparison.png")
    plot_feature_table(feature_pivot, out_dir / "feature_table.png")

    print(f"分析結果を {out_dir} に出力しました．")


if __name__ == "__main__":
    main()
