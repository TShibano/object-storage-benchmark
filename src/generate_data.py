"""
File: generate_data.py
Author: citrus
Abstract:
ベンチマーク測定に用いるParquetファイルを生成する
"""

import os
import numpy as np
import polars as pl
from pathlib import Path


def generate_one_parquet_file(path: Path, target_mb: int) -> None:
    """1つのサンプルParquetファイルを生成する
    `target_mb` MBのParquetファイルを生成する

    Args:
        path (Path): 保存するファイルのパス
        target_mb (int): ファイルのサイズ(MB単位)
    """
    target_bytes = target_mb * 1024 * 1024
    chunk_size = 4096  # 1行あたり4KB
    n_rows = target_bytes // chunk_size
    rng = np.random.default_rng()
    data = [bytes(rng.bytes(chunk_size)) for _ in range(n_rows)]
    pl.DataFrame({"data": pl.Series(data, dtype=pl.Binary)}).write_parquet(
        path, compression="uncompressed"
    )


def generate_parquet_file(output_dir: Path, n_file: int, target_mb: int) -> None:
    """複数のサンプルparquetファイルを生成する
    `output_dir`で指定したディレクトリに，`n_file`個の `target_mb` MBのParquetファイルを生成する

    Args:
        output_dir (Path): 出力先のディレクトリ
        n_file (int): ファイル数
        target_mb (int): 1ファイルのサイズ(MB単位)
    """
    digit: int = len(str(n_file))
    filename_list: list[Path] = [
        Path(f"{str(i).zfill(digit + 1)}.parquet") for i in range(n_file)
    ]
    os.makedirs(output_dir)
    for filename in filename_list:
        generate_one_parquet_file(output_dir / filename, target_mb)


def main():
    generate_parquet_file(output_dir=Path("./tmp/small/"), n_file=11, target_mb=1)


if __name__ == "__main__":
    main()
