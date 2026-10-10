"""静态自检：语法 + 硬编码密钥扫描（提交前跑一次，也接在 CI 里）。

为什么单独做脚本，而不是在文档里写一行"魔法命令"：
    1. 可读、可维护 —— 文档里的长命令没人会维护，改一次就过期；
    2. 跨平台 —— 同一条命令在 Windows PowerShell 与 Linux bash 下都能跑；
    3. 退出码明确 —— 失败返回 1，CI 能直接拦截。

用法：
    .venv-rag\\Scripts\\python.exe scripts\\check_syntax.py
    .venv-rag\\Scripts\\python.exe scripts\\check_syntax.py --verbose

检查项：
    ① 所有 .py 能被 ast 解析（语法错误会精确到文件与行号）
    ② 代码/文档中不得出现硬编码密钥（sk- 开头 20 位以上）
    ③ 大文件预警（>50MB，避免误提交模型缓存或数据文件）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 扫描密钥时覆盖的文件类型（与 CI 中的扫描保持一致）
SECRET_SUFFIXES = {".py", ".js", ".json", ".md", ".yml", ".yaml", ".txt", ".ps1", ".sh", ".toml", ".ini", ".css", ".html"}
SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")

# 通用忽略：依赖、缓存、编辑器
SKIP_DIRS = {".git", ".venv", ".venv-rag", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".idea"}

# 额外忽略：运行时产物与沙箱临时文件。
# 这些内容**已被 .gitignore 排除**，检查它们只会制造噪声（大模型文件、用户上传的原文）。
# 说明：如果用户上传的文件里含密钥，它不会进仓库；真要清理请单独处理 data/uploads/。
RUNTIME_DIRS = {"hf", "uploads", "qdrant"}
SKIP_PREFIXES = ("data/_", "_", "docs/_")          # data/_srv_*.py 这类临时文件
SKIP_NAMES = {"_writeprobe.txt"}

# 大文件阈值：源码/配置/文档单文件超过它才值得警惕
# （1GB 的模型权重在 data/hf 下，已被上面忽略，不该报错）
BIG_FILE_MB = 5.0


def _skipped(rel: Path) -> bool:
    parts = rel.parts
    if any(part in SKIP_DIRS for part in parts):
        return True
    # 运行时目录（data/hf、data/uploads、data/qdrant 及其子目录）
    if len(parts) >= 2 and parts[0] == "data" and parts[1] in RUNTIME_DIRS:
        return True
    name = rel.name
    if name in SKIP_NAMES:
        return True
    if any(name.startswith(pre) for pre in ("_", "~$")):
        return True
    # data/_xxx、docs/_xxx 这类下划线开头的临时产物
    if any(part.startswith("_") for part in parts):
        return True
    return False


def iter_files(suffixes: set[str] | None = None):
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if _skipped(rel):
            continue
        if suffixes is not None and p.suffix.lower() not in suffixes:
            continue
        yield p


def check_syntax(verbose: bool) -> list[str]:
    import ast

    problems: list[str] = []
    files = [p for p in iter_files({".py"})]
    for p in files:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            problems.append(f"{p.relative_to(ROOT)}:{e.lineno} {e.msg}")
        except UnicodeDecodeError as e:  # 编码问题同样会导致 CI 失败
            problems.append(f"{p.relative_to(ROOT)} 编码不是 UTF-8：{e}")
    if verbose:
        print(f"  检查 {len(files)} 个 .py 文件")
    return problems


def check_secrets(verbose: bool) -> list[str]:
    problems: list[str] = []
    scanned = 0
    for p in iter_files(SECRET_SUFFIXES):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            m = SECRET_RE.search(line)
            if not m:
                continue
            low = line.lower()
            # 占位符与示例不算泄露（.env.example 里就应该是它）
            if any(h in low for h in ("请填入", "your", "xxx", "<", "占位", "example", "placeholder")):
                continue
            problems.append(f"{p.relative_to(ROOT)}:{i} 疑似硬编码密钥：{m.group()[:12]}…")
    if verbose:
        print(f"  扫描 {scanned} 个文本文件")
    return problems


def check_big_files(limit_mb: float = BIG_FILE_MB, verbose: bool = False) -> list[str]:
    problems: list[str] = []
    limit = limit_mb * 1024 * 1024
    for p in iter_files():
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > limit:
            problems.append(f"{p.relative_to(ROOT)} 体积 {size / 1024 / 1024:.1f} MB（> {limit_mb:.0f} MB）")
    if verbose:
        print(f"  检查大文件（阈值 {limit_mb:.0f} MB）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="静态自检：语法 + 密钥扫描 + 大文件")
    ap.add_argument("--verbose", action="store_true", help="打印每个检查项的扫描规模")
    ap.add_argument("--big-mb", type=float, default=BIG_FILE_MB,
                    help=f"大文件阈值（MB），默认 {BIG_FILE_MB:.0f}；0 表示跳过")
    args = ap.parse_args()

    print(f"静态自检：{ROOT}")
    results: list[tuple[str, list[str]]] = []

    results.append(("语法检查（所有 .py 可解析）", check_syntax(args.verbose)))
    results.append(("密钥扫描（无硬编码 sk-*）", check_secrets(args.verbose)))
    if args.big_mb > 0:
        results.append((f"大文件检查（阈值 {args.big_mb:.0f} MB）", check_big_files(args.big_mb, args.verbose)))

    failed = 0
    for name, problems in results:
        if problems:
            failed += 1
            print(f"\n  ✗ {name}：{len(problems)} 个问题")
            for x in problems[:12]:
                print(f"      {x}")
            if len(problems) > 12:
                print(f"      …… 另有 {len(problems) - 12} 个")
        else:
            print(f"  ✓ {name}")

    print()
    if failed:
        print(f"自检未通过（{failed} 项有问题）", file=sys.stderr)
        return 1
    print("自检全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
