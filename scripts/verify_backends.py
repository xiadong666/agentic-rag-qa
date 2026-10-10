"""向量库双后端验收：分别用 FAISS 与 Qdrant(本地模式) 跑通「入库 → 检索」。

用法：
    .venv\\Scripts\\python scripts\\verify_backends.py

两种后端各自使用独立临时数据目录，互不污染；结束打印 PASS/FAIL 汇总。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.core.engine import RAGEngine  # noqa: E402

SAMPLE = ROOT / "sample_docs" / "rag原理速查.md"
QUESTION = "混合检索为什么用 RRF 融合？"
# 验收工作目录：默认放在项目同级目录（保持 ASCII 路径 —— FAISS 的 C++ 层
# 在 Windows 上打不开含中文的路径）。可用 RAG_VERIFY_DIR 覆盖。
VERIFY_BASE = Path(os.environ.get("RAG_VERIFY_DIR", ROOT.parent / "_verify_backends"))


async def run_backend(backend: str) -> tuple[bool, str]:
    tmp = VERIFY_BASE / backend
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        settings = Settings(
            data_dir=tmp,
            vector_backend=backend,       # type: ignore[arg-type]
            qdrant_path=str(tmp / "qdrant"),
            rerank_enabled=False,         # 验收不依赖重排模型，跑得快
        )
        settings.ensure_dirs()
        engine = RAGEngine(settings)
        await engine.initialize()

        with open(SAMPLE, "rb") as f:  # 用真实样例文档入库
            tmp_doc = tmp / SAMPLE.name
            tmp_doc.write_bytes(f.read())
        info = await engine.ingest_file(str(tmp_doc), SAMPLE.name, "向量后端验收样例")
        hits = await engine.search(QUESTION, top_k=3)

        backend_name = type(engine.vectors).__name__
        ok = bool(hits) and info["chunk_count"] > 0
        detail = (f"backend={backend_name} chunks={info['chunk_count']} hits={len(hits)} "
                  f"top={hits[0].doc_title if hits else '(none)'} score={hits[0].score if hits else 0}")
        return ok, detail
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def main() -> int:
    print("=== 向量库双后端验收（FAISS vs Qdrant 本地模式）===")
    failed = 0
    for backend in ("faiss", "qdrant"):
        try:
            ok, detail = await run_backend(backend)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        print(f"[{'PASS' if ok else 'FAIL'}] {backend}: {detail}")
        failed += 0 if ok else 1
    print("=" * 56)
    print(f"结果：{'全部通过' if failed == 0 else f'{failed} 个后端失败'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
