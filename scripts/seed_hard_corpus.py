"""把 sample_docs/hard 的困难语料灌入知识库，并按 test_cases.json 逐题验收。

为什么单独做一个脚本：
    "检索准不准、回答相不相关"必须用**带预期答案的题**来判，而不是凭感觉问几句。
    本脚本做三件事：
      ① 灌库：把 sample_docs/hard 下的文档（可选连 sample_docs 一起）上传入库；
      ② 检索验收：对每道题调检索，判断"期望文档是否命中"，打印逐题命中表；
      ③ 回答验收（可选 --ask）：调 LLM 生成回答，检查是否覆盖 ref_keywords，
         并统计"库里没有答案的探针题"是否正确拒答。

用法（推荐先起服务，用 HTTP 模式，最贴近真实链路）：
    # 1) 起服务（另开一个终端）
    .venv-rag\\Scripts\\python -m uvicorn app.main:app --port 8000

    # 2) 灌困难语料 + 跑检索验收
    .venv-rag\\Scripts\\python scripts\\seed_hard_corpus.py --base http://127.0.0.1:8000

    # 3) 连回答一起验收（会花钱，逐题一次生成）
    .venv-rag\\Scripts\\python scripts\\seed_hard_corpus.py --ask

    # 4) 只看题目命中情况，不灌库（库已就绪时）
    .venv-rag\\Scripts\\python scripts\\seed_hard_corpus.py --skip-upload

    # 5) 复现"干净困难库"：先清空知识库再灌（--purge）
    .venv-rag\\Scripts\\python scripts\\seed_hard_corpus.py --purge

    # 6) 生成 PDF 版语料（需要 reportlab，见脚本内提示）
    .venv-rag\\Scripts\\python scripts\\seed_hard_corpus.py --make-pdf

退出码：0 = 检索验收全部命中（允许探针题无命中），1 = 有未命中。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HARD_DIR = ROOT / "sample_docs" / "hard"
CASES_PATH = HARD_DIR / "test_cases.json"

# 是否把说明文档（README / _说明_*.txt）也当成语料灌进去。
# 默认 False：做检索验收时语料必须干净；用 --include-docs 可模拟"整个文档目录直接上传"的场景。
_INCLUDE_DOCS = False


# ----------------------------------------------------------------- 数据准备
def load_cases() -> list[dict]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data.get("cases", [])


def corpus_files(include_easy: bool) -> list[Path]:
    """列出要灌库的语料文件。

    排除项（做**检索验收**时语料必须干净，否则指标会虚高）：
        * README 等说明文档；
        * 以 `_` 开头的辅助文件（如 `_说明_怎么用这批困难语料.txt`）——
          这类文件往往写着"预期答案/验收基线"，一旦入库它会变成**干扰文档**，
          既可能被检索命中顶掉正片，也会把答案直接送进上下文（实测踩过：
          E5/E7 的 top-3 被它占位，E7 掉到第 2 位）；
        * `test_cases.json` 题集本身。

    需要把说明文档也灌进去时用 `--include-docs`（模拟"文档目录整体上传"的真实场景）。
    """
    allowed = {".md", ".txt", ".csv", ".pdf"}

    def keep(p: Path) -> bool:
        name = p.name.lower()
        if not p.is_file() or p.suffix.lower() not in allowed:
            return False
        if _INCLUDE_DOCS:
            return name != "test_cases.json"
        return (name not in {"readme.md", "readme.txt"}
                and not name.startswith(("test_cases", "_", "readme", "说明")))

    files = sorted(p for p in HARD_DIR.iterdir() if keep(p))
    if include_easy:
        easy = sorted(p for p in (ROOT / "sample_docs").glob("*") if keep(p))
        files = easy + files
    return files


# ----------------------------------------------------------------- HTTP 模式
class HttpRunner:
    def __init__(self, base: str) -> None:
        import httpx

        self.base = base.rstrip("/")
        self.c = httpx.Client(timeout=300.0)

    def health(self) -> dict:
        return self.c.get(f"{self.base}/health").json()

    def purge(self) -> int:
        docs = self.c.get(f"{self.base}/api/documents").json()
        for d in docs:
            self.c.delete(f"{self.base}/api/documents/{d['doc_id']}")
        return len(docs)

    def upload(self, path: Path) -> dict:
        with path.open("rb") as f:
            r = self.c.post(f"{self.base}/api/documents/upload",
                            files={"file": (path.name, f, "application/octet-stream")},
                            data={"title": path.stem})
        return {"status": r.status_code, **r.json()}

    def search(self, question: str, top_k: int) -> list[dict]:
        r = self.c.post(f"{self.base}/api/search", json={"question": question, "top_k": top_k})
        return r.json().get("hits", []) if r.status_code == 200 else []

    def ask(self, question: str) -> dict:
        r = self.c.post(f"{self.base}/api/agent/query", json={"question": question, "use_history": False})
        return r.json() if r.status_code == 200 else {"answer": f"(HTTP {r.status_code})", "sources": []}


# ----------------------------------------------------------------- 进程内模式
class LocalRunner:
    """不启动服务，直接在进程内用引擎（速度快，适合反复调参对比）。"""

    def __init__(self, settings) -> None:
        from app.core.engine import RAGEngine

        self.settings = settings
        self.engine = RAGEngine(settings)

    async def init(self) -> None:
        await self.engine.initialize()

    async def health(self) -> dict:
        return {"docs": len(self.engine.store.docs), "chunks": self.engine.store.total_chunks()}

    async def purge(self) -> int:
        docs = [d.doc_id for d in self.engine.store.doc_list()]
        for did in docs:
            await self.engine.delete_document(did)
        return len(docs)

    async def upload(self, path: Path) -> dict:
        info = await self.engine.ingest_file(str(path), path.name, path.stem)
        return {"status": 200, **info}

    async def search(self, question: str, top_k: int) -> list[dict]:
        return [s.model_dump() for s in await self.engine.search(question, top_k)]

    async def ask(self, question: str) -> dict:
        return await self.engine.agent_answer(question, None, use_history=False)


# ----------------------------------------------------------------- 验收逻辑
def judge_refusal(answer: str) -> bool:
    keys = ("没有找到", "未找到", "未涉及", "无法", "无相关信息", "不包含", "没有相关", "资料库中")
    return any(k in answer for k in keys)


def summarize(rows: list[tuple], *, hit: int, miss: int, kw_ok: int, kw_den: int,
              probe_ok: int, probe_den: int, asked: bool) -> int:
    print("\n" + "=" * 104)
    print(f"{'题号':<6}{'期望文档排名':<14}{'top-3 命中':<44}{'回答判定':<16}缺少的要点")
    print("-" * 104)
    for cid, rank, titles, verdict, kw_miss in rows:
        if rank == -1:
            rt = "—(探针)"
        elif rank == 0:
            rt = "未命中"
        else:
            rt = f"第 {rank} 位"
        print(f"{cid:<6}{rt:<14}{' / '.join(t[:15] for t in titles):<44}{verdict:<16}{'、'.join(kw_miss)}")
    print("-" * 104)
    total = hit + miss
    print(f"检索命中：{hit}/{total}" + (f"（未命中 {miss} 题）" if miss else "（全部命中）"))
    if asked:
        if kw_den:
            print(f"回答要点覆盖：{kw_ok}/{kw_den} = {kw_ok / kw_den:.1%}")
        if probe_den:
            print(f"库外探针正确拒答：{probe_ok}/{probe_den}"
                  + ("（全部正确拒答）" if probe_ok == probe_den else "（有一本正经作答的情况！）"))
    print("=" * 104)
    return 1 if miss else 0


def evaluate(runner, cases: list[dict], *, top_k: int, ask: bool, local: bool) -> int:
    """检索/回答验收。local=True 时 runner 的方法是协程，统一在这里驱动。"""
    if local:
        return asyncio.run(_evaluate_async(runner, cases, top_k=top_k, ask=ask))
    return _run_sync(runner, cases, top_k=top_k, ask=ask)


def _tally(row_acc: dict, case: dict, titles: list[str], ans: str) -> tuple:
    expect = case.get("expect_docs") or []
    kws = [k for k in (case.get("ref_keywords") or []) if k]
    answerable = bool(case.get("answerable", True))
    rank = next((i for i, t in enumerate(titles, 1) if t in expect), 0) if expect else -1
    verdict, kw_miss = "", []
    if ans is not None:
        if not answerable:
            row_acc["probe_den"] += 1
            if judge_refusal(ans):
                row_acc["probe_ok"] += 1
                verdict = "正确拒答"
            else:
                verdict = "⚠ 未拒答"
        elif kws:
            hitk = [k for k in kws if k in ans]
            kw_miss = [k for k in kws if k not in ans]
            row_acc["kw_ok"] += len(hitk)
            row_acc["kw_den"] += len(kws)
            verdict = "要点齐全" if not kw_miss else f"缺 {len(kw_miss)} 个要点"
    if expect:
        if rank:
            row_acc["hit"] += 1
        else:
            row_acc["miss"] += 1
    return rank, verdict, kw_miss


def _run_sync(runner, cases: list[dict], *, top_k: int, ask: bool) -> int:
    acc = {"hit": 0, "miss": 0, "kw_ok": 0, "kw_den": 0, "probe_ok": 0, "probe_den": 0}
    rows = []
    for case in cases:
        hits = runner.search(case["question"], top_k)
        titles = [h.get("doc_title", "") for h in hits]
        ans = None
        if ask:
            ans = (runner.ask(case["question"]) or {}).get("answer", "")
            print(f"  … {case['id']} 已生成回答（{len(ans)} 字）")
        rank, verdict, kw_miss = _tally(acc, case, titles, ans)
        rows.append((case["id"], rank, titles[:3], verdict, kw_miss))
    return summarize(rows, hit=acc["hit"], miss=acc["miss"], kw_ok=acc["kw_ok"],
                     kw_den=acc["kw_den"], probe_ok=acc["probe_ok"],
                     probe_den=acc["probe_den"], asked=ask)


async def _evaluate_async(runner, cases: list[dict], *, top_k: int, ask: bool) -> int:
    acc = {"hit": 0, "miss": 0, "kw_ok": 0, "kw_den": 0, "probe_ok": 0, "probe_den": 0}
    rows = []
    for case in cases:
        hits = await runner.search(case["question"], top_k)
        titles = [h.get("doc_title", "") for h in hits]
        ans = None
        if ask:
            ans = (await runner.ask(case["question"]) or {}).get("answer", "")
            print(f"  … {case['id']} 已生成回答（{len(ans)} 字）")
        rank, verdict, kw_miss = _tally(acc, case, titles, ans)
        rows.append((case["id"], rank, titles[:3], verdict, kw_miss))
    return summarize(rows, hit=acc["hit"], miss=acc["miss"], kw_ok=acc["kw_ok"],
                     kw_den=acc["kw_den"], probe_ok=acc["probe_ok"],
                     probe_den=acc["probe_den"], asked=ask)


# ----------------------------------------------------------------- PDF 生成
def make_pdf() -> int:
    """把困难语料的 md/csv 转成 PDF（文本型）+ 生成一份扫描型 PDF（图片，无文本层）。

    为什么单独提供：PDF 解析链路与 md 不同（按页抽文本、保留页码），
    所以要用 PDF 再测一遍"页码能否溯源"。
    依赖 reportlab（体积小、纯 Python）：pip install reportlab
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except Exception:  # noqa: BLE001
        print("未安装 reportlab，无法生成 PDF。请先在项目解释器里安装：")
        print("    .venv-rag\\Scripts\\python.exe -m pip install reportlab")
        print("（装不上通常是权限问题：换一个可写的虚拟环境，或用 --find-links 指定目录）")
        return 2

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    out_dir = HARD_DIR / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    for src in sorted(HARD_DIR.iterdir()):
        if not src.is_file() or src.suffix.lower() not in {".md", ".csv"}:
            continue
        text = src.read_text(encoding="utf-8")
        pdf = out_dir / (src.stem + ".pdf")
        c = canvas.Canvas(str(pdf), pagesize=A4)
        w, h = A4
        c.setFont("STSong-Light", 10.5)
        y = h - 50
        page = 1
        c.setFont("STSong-Light", 8)
        c.drawString(w - 90, 30, f"第 {page} 页")
        c.setFont("STSong-Light", 10.5)
        for line in text.splitlines():
            # 每行按 46 字符硬折行（中文按字符宽度估算），避免超出页宽
            chunks = [line[i:i + 46] for i in range(0, max(len(line), 1), 46)] or [""]
            for chunk in chunks:
                if y < 60:
                    c.showPage()
                    page += 1
                    c.setFont("STSong-Light", 10.5)
                    y = h - 50
                    c.setFont("STSong-Light", 8)
                    c.drawString(w - 90, 30, f"第 {page} 页")
                    c.setFont("STSong-Light", 10.5)
                c.drawString(45, y, chunk)
                y -= 16
        c.save()
        made.append(pdf)
        print(f"  [OK] {pdf.name}")

    # 扫描型 PDF：只有图片、没有文本层 —— 用来验证"解析失败要有清晰报错"
    scanned = out_dir / "99_扫描件_无文本层.pdf"
    c = canvas.Canvas(str(scanned), pagesize=A4)
    c.setFont("STSong-Light", 26)
    c.drawString(90, A4[1] / 2, "本页是图片，未嵌入文本层")
    c.setFont("STSong-Light", 12)
    c.drawString(90, A4[1] / 2 - 40, "上传它应触发：未解析出任何文本 → 提示需要 OCR")
    c.save()
    print(f"  [OK] {scanned.name}（应触发 OCR 报错，属预期）")
    print(f"\n共生成 {len(made) + 1} 个 PDF → {out_dir}")
    print("上传后注意看 sources 里的 page 字段：文本型 PDF 应能精确到页码。")
    return 0


# ----------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="服务地址；留空则用进程内引擎（不起 HTTP）")
    ap.add_argument("--data-dir", default="", help="进程内模式的数据目录（建议传绝对路径）")
    ap.add_argument("--top-k", type=int, default=4, help="检索验收的 top-k（默认 4，与 rerank_top_k 对齐）")
    ap.add_argument("--ask", action="store_true", help="连回答一起验收（会调用 LLM 产生费用）")
    ap.add_argument("--skip-upload", action="store_true", help="跳过灌库，只跑验收")
    ap.add_argument("--purge", action="store_true", help="灌库前先清空知识库（复现干净困难库）")
    ap.add_argument("--include-easy", action="store_true", help="连 sample_docs 的简单文档一起灌（做干扰）")
    ap.add_argument("--make-pdf", action="store_true", help="生成 PDF 版语料后退出")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 道题（0 = 全部；先用 3~5 道试跑省时间）")
    ap.add_argument("--only", default="", help="只跑指定题号，逗号分隔（如 E12,E13,E14 专门验拒答）")
    ap.add_argument("--include-docs", action="store_true",
                    help="把 README / _说明_*.txt 也当语料灌入（默认排除，避免干扰检索验收）")
    args = ap.parse_args()

    global _INCLUDE_DOCS
    _INCLUDE_DOCS = args.include_docs

    if args.make_pdf:
        return make_pdf()

    cases = load_cases()
    if args.only:
        want = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"].upper() in want]
    if args.limit:
        cases = cases[: args.limit]
    files = corpus_files(args.include_easy)
    print(f"困难语料：{len(files)} 个文件　｜　测试题：{len(cases)} 道")

    if args.base:
        runner = HttpRunner(args.base)
        h = runner.health()
        print(f"服务：{args.base}　清空/灌库前：docs={h.get('docs')} chunks={h.get('chunks')}"
              f"（这是操作前的快照，最终数量在下面的验收表之后）")
        if not args.skip_upload:
            if args.purge:
                n = runner.purge()
                print(f"已清空 {n} 篇文档")
            for f in files:
                info = runner.upload(f)
                ok = info.get("status") == 200
                print(f"  [{'OK' if ok else 'FAIL'}] {f.name} → "
                      f"{info.get('chunk_count', info.get('detail', ''))} chunks")
        return evaluate(runner, cases, top_k=args.top_k, ask=args.ask, local=False)

    # 进程内模式：直接用引擎，适合反复调参对比（不起 HTTP）
    from pathlib import Path as _P

    from app.config import get_settings

    settings = get_settings()
    if args.data_dir:
        settings = settings.model_copy(update={"data_dir": _P(args.data_dir).resolve()})
    settings.ensure_dirs()
    runner = LocalRunner(settings)

    async def prepare() -> tuple[int, int, int]:
        await runner.init()
        purged = 0
        if not args.skip_upload and args.purge:
            purged = await runner.purge()
        uploaded = 0
        if not args.skip_upload:
            for f in files:
                info = await runner.upload(f)
                uploaded += 1
                print(f"  [OK] {f.name} → {info.get('chunk_count')} chunks")
        hh = await runner.health()
        return purged, uploaded, hh["chunks"]

    purged, uploaded, chunks = asyncio.run(prepare())
    print(f"进程内引擎　数据目录={settings.data_dir}"
          + (f"（清空了 {purged} 篇旧文档）" if purged else "")
          + (f"　灌入 {uploaded} 个文件后：" if uploaded else "　当前：")
          + f"docs/chunks={chunks}")
    print("  提示：上面的 chunks 是**清空+灌库之后**的最终值；"
          "若它比各文件 chunks 之和少，说明有文件解析失败或分块被去重。")
    return evaluate(runner, cases, top_k=args.top_k, ask=args.ask, local=True)


if __name__ == "__main__":
    sys.exit(main())
