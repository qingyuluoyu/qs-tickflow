#!/usr/bin/env python3
"""打包 TickFlow 完整部署 zip: git 跟踪文件 + frontend/dist + data/(去大缓存) + 根 .env。

用法: python packaging/build_server_zip.py <输出zip路径>
注意: 包含根 .env 里的全部密钥, 产物不可外传。
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_EXCLUDE_DIRS = {".backtest_matrix_cache", ".migration_backups"}


def git_files() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT, capture_output=True,
    )
    text = out.stdout.decode("utf-8")
    return [line for line in text.splitlines() if line]


def main() -> None:
    target = Path(sys.argv[1])
    files = git_files()
    # 前端构建产物不在 git 里, 但必须带上(服务器不装 node)
    for p in sorted((ROOT / "frontend" / "dist").rglob("*")):
        if p.is_file():
            files.append(p.relative_to(ROOT).as_posix())
    # data/ 是运行时数据, 不在 git 里; 排除可重建的大缓存
    for p in sorted((ROOT / "data").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if len(rel.parts) > 1 and rel.parts[1] in DATA_EXCLUDE_DIRS:
            continue
        files.append(rel.as_posix())
    files.append(".env")

    seen: set[str] = set()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in files:
            if rel in seen:
                continue
            seen.add(rel)
            src = ROOT / rel
            if src.is_file():
                zf.write(src, rel)
    size_mb = target.stat().st_size / 1024 / 1024
    print(f"{target}  {size_mb:.0f}MB  {len(seen)} files")


if __name__ == "__main__":
    main()
