# generate_data.py
# データ生成
#

import numpy as np
import polars as pl
from pathlib import Path

def generate_parquet_file(path: Path, target_mb: int) -> None:
    """
    `target_mb` MBのParquetファイルを生成する       
    """
    target_bytes = target_mb * 1024 * 1024
    chunk_size = 4096  # 1行あたり4KB
    n_rows = target_bytes // chunk_size
    rng = np.random.default_rng()
    data = [bytes(rng.bytes(chunk_size)) for _ in range(n_rows)]
    pl.DataFrame({"data": pl.Series(data, dtype=pl.Binary)}).write_parquet(path, compression="uncompressed")



def main():
    generate_parquet_file(Path("./tmp/small.parquet"), target_mb=1) # 1MB
    generate_parquet_file(Path("./tmp/large.parquet"), target_mb=100) # 1MB
    

if __name__=="__main__":
    main()

