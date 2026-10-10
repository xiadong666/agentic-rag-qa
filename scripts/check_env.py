"""配置自检：确认 `.env` 里的每一项都能被 Settings 识别，并打印关键配置的实际取值。

为什么需要它（真实踩过的坑）：
    pydantic-settings 是**按字段名**映射环境变量的，且项目里配置了 `extra="ignore"`——
    也就是说：**字段名与 `.env` 变量名不一致时，那一行会被静默忽略**，不报错、不警告，
    程序继续用代码默认值。本项目就因此踩过一次：
    字段叫 `allowed_extensions_raw`、`.env` 写 `ALLOWED_EXTENSIONS`，
    结果"允许上传 csv"这条配置从来没生效，直到做困难语料验收（需要上传 CSV）时才暴露。

用法（建议加进 CI 或发布前跑一次）：
    .venv-rag\\Scripts\\python.exe scripts\\check_env.py            # 只检查，不退出非零
    .venv-rag\\Scripts\\python.exe scripts\\check_env.py --strict   # 有无法识别的键就退出码 1

退出码：0 = 正常；1 = 存在无法识别的配置项（仅在 --strict 下）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ROOT_DIR, Settings  # noqa: E402


def env_pairs(path: Path | None = None) -> list[tuple[str, str, int]]:
    """读 .env（或指定文件），返回 [(KEY, value, 行号)]（跳过注释与空行）。"""
    path = path or (ROOT_DIR / ".env")
    if not path.exists():
        return []
    out: list[tuple[str, str, int]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out.append((k.strip(), v.split("#")[0].strip(), i))
    return out


def known_keys() -> set[str]:
    """所有能被识别为配置项的键名（字段名 + alias，统一大写）。"""
    known = {f.upper() for f in Settings.model_fields}
    known |= {(fi.alias or "").upper() for fi in Settings.model_fields.values() if fi.alias}
    return known


def check_example_file(known: set[str]) -> list[str]:
    """校验 .env.example 里的每个键都能被 Settings 识别。

    为什么值得单独检查：
        `.env.example` 是给使用者的"配置清单"，一旦它与代码字段名脱节，
        用户照抄之后那一行**会被静默忽略**（pydantic-settings 不报错、不警告，
        一直用代码默认值）。本项目真实踩过两次：
          · allowed_extensions_raw  ↔ .env 写 ALLOWED_EXTENSIONS
          · llm_task_routes_raw     ↔ .env 写 LLM_TASK_ROUTES
        所以这条检查要长期留在 CI 里，当作"文档与代码一致性"的护栏。
    """
    path = ROOT_DIR / ".env.example"
    if not path.exists():
        return [".env.example 不存在（使用者没有可照抄的模板）"]
    bad: list[str] = []
    for key, value, line in env_pairs(path):
        if key.upper() not in known:
            bad.append(f"{path.name} 行{line}  {key} = {value[:40]}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(
        description="配置自检：校验 .env 每项是否可被 Settings 识别，并打印实际生效值。"
                    "（本脚本只读配置，不需要服务地址；服务地址是 verify_*.py 的参数）")
    ap.add_argument("--strict", action="store_true", help="存在无法识别的键时退出码 1")
    # 兼容误传服务地址的用法：捕获位置参数并忽略，避免"unrecognized arguments"让人以为脚本坏了
    ap.add_argument("ignored", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.ignored:
        print(f"提示：已忽略多余参数 {args.ignored} —— 本脚本只读配置，不需要服务地址。")
        print("      （要跑验收请用 scripts\\verify_agentic.py http://127.0.0.1:8000）\n")

    known = {f.upper() for f in Settings.model_fields}
    known |= {(fi.alias or "").upper() for fi in Settings.model_fields.values() if fi.alias}

    pairs = env_pairs()
    unknown = [(k, v, n) for k, v, n in pairs if k.upper() not in known]
    example_bad = check_example_file(known)

    print(f"配置自检：{ROOT_DIR / '.env'}")
    print(f"  .env 有效配置项 {len(pairs)} 个 ｜ Settings 字段 {len(Settings.model_fields)} 个")
    if unknown:
        print(f"\n  ✗ 无法识别的配置项 {len(unknown)} 个（这些行不会生效！）:")
        for k, v, n in unknown:
            print(f"      行{n:<4}{k} = {v[:48]}")
        print("    常见原因：字段名带 _raw/_str 等后缀，而 .env 里没写后缀（或反之）。")
        print("    处理：把字段名与 .env 变量名改成完全一致。")
    else:
        print("\n  ✓ .env 里所有配置项都能被识别")

    # 模板文件同样要校验：它是使用者照抄的对象，一旦与代码脱节就会埋下静默失效的坑
    if example_bad:
        print(f"\n  ✗ .env.example 有 {len(example_bad)} 个无法识别的配置项：")
        for x in example_bad:
            print(f"      {x}")
        print("    处理：把模板里的变量名改成与 Settings 字段名一致（本项目已因此踩坑两次）。")
    else:
        print("  ✓ .env.example 里所有配置项都能被识别（模板与代码一致）")

    s = Settings()
    print("\n关键配置的实际取值（以此为准，而不是 .env 里写了什么）：")
    rows = [
        ("允许上传扩展名", sorted(s.allowed_extension_set)),
        ("上传大小上限", f"{s.max_upload_mb} MB"),
        ("分块 / 重叠", f"{s.chunk_size} / {s.chunk_overlap}"),
        ("召回 dense/sparse", f"{s.retrieve_dense_k} / {s.retrieve_sparse_k}"),
        ("RRF 常数 k", s.rrf_constant),
        ("重排开关 / top_k", f"{s.rerank_enabled} / {s.rerank_top_k}"),
        ("向量库后端", s.vector_backend),
        ("对话模型", s.llm_model),
        ("小模型档", s.llm_small_model or "（留空 = 与主模型相同）"),
        ("强模型档", s.llm_strong_model or "（留空 = 与主模型相同）"),
        ("Agent 开关", s.agent_enabled),
        ("Agent 轮数上限", s.agent_max_retrieval_rounds),
        ("强证据阈值", s.agent_strong_score),
        ("忠实度自检", s.agent_verify_enabled),
        ("LLM key 已配置", s.llm_ready),
    ]
    for k, v in rows:
        print(f"  {k:<18}{v}")

    # ---- 数据目录一致性：验证"配置指向的目录"与"真实数据"是否对得上 ----
    # 为什么加这一段：DATA_DIR 是相对路径，换个目录启动就会指向别处，
    # 表现是"库里有数据但服务显示 0 篇文档"—— 这属于配置正确但**指向错误**，光看配置看不出来。
    print("\n数据目录一致性：")
    data_dir = s.data_dir
    kb = data_dir / "kb.jsonl"
    idx = data_dir / "vectors.index"
    print(f"  data_dir（实际解析）  {data_dir}  {'存在 ✓' if data_dir.exists() else '不存在 ✗'}")
    print(f"  kb.jsonl              {'存在 ✓' if kb.exists() else '缺失 ✗'}")
    print(f"  vectors.index         {'存在 ✓' if idx.exists() else '缺失 ✗（首次入库后生成）'}")
    if kb.exists():
        try:
            lines = kb.read_text(encoding="utf-8").splitlines()
            n_chunk = sum(1 for l in lines if '"kind": "chunk"' in l)
            n_doc = sum(1 for l in lines if '"kind": "doc"' in l)
            print(f"  库里内容（kb.jsonl）    {n_doc} 篇文档 / {n_chunk} 个分块")
        except Exception as e:  # noqa: BLE001
            print(f"  读取 kb.jsonl 失败：{type(e).__name__}: {e}")
    if not (s.llm_small_model or "").strip():
        print("\n提示：LLM_SMALL_MODEL 留空 → 规划/判定/改写/压缩仍走主模型（功能正常，但没省到成本）。")

    # --strict：任何"写了但不生效"的配置项都视为失败（.env 与 .env.example 都算）
    if args.strict and (unknown or example_bad):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
