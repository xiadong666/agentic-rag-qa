"""把 sample_docs 下的示例文档灌入知识库（离线可用，无需 LLM key）。

用法：
    .venv\\Scripts\\python scripts\\seed_demo.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 允许直接以脚本方式运行：把项目根加入 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.core.engine import RAGEngine  # noqa: E402


async def main() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    engine = RAGEngine(settings)
    await engine.initialize()

    sample_dir = ROOT / "sample_docs"
    files = sorted(sample_dir.glob("*"))
    if not files:
        print("sample_docs 为空，请先确认示例文档存在。")
        return

    for f in files:
        print(f"ingest: {f.name} ...")
        result = await engine.ingest_file(str(f), f.name, f.stem)
        print(
            f"  [OK] {f.stem}: {result['char_count']} chars -> "
            f"{result['chunk_count']} chunks ({result['elapsed_ms']}ms)"
        )

    print(f"\nKB now: {len(engine.store.docs)} docs, {engine.store.total_chunks()} chunks.")
    print('Try: POST /api/search  {"question": "混合检索为什么用RRF？"}')


if __name__ == "__main__":
    asyncio.run(main())
