困难语料使用说明 → 请看同目录的「_说明_怎么用这批困难语料.txt」

本文件（README.md）仅作为占位，避免有人只看到目录里没有说明。
完整说明包含：七类难点对照表、两步使用方法、PDF 生成方式、本机实测基线、接评测框架的方法。

快速开始：

    # 1) 起服务
    .venv-rag\Scripts\python -m uvicorn app.main:app --port 8000

    # 2) 灌库 + 检索验收（--purge 先清空，保证是干净困难库）
    .venv-rag\Scripts\python scripts\seed_hard_corpus.py --base http://127.0.0.1:8000 --purge

    # 3) 连"回答是否相关"一起验收
    .venv-rag\Scripts\python scripts\seed_hard_corpus.py --base http://127.0.0.1:8000 --skip-upload --ask

题集在同目录 test_cases.json（14 题，含 3 道库外幻觉探针）。
