# 贡献指南（CONTRIBUTING）

感谢愿意一起改进这个项目。这份文档只讲**怎么改不会踩坑**，以及**这个项目特有的几条规矩**。

---

## 一、本地跑起来（五分钟）

```powershell
# 1) 建虚拟环境（⚠️ 用 .venv-rag；仓库里若残留 .venv 可能是坏的，别用）
python -m venv .venv-rag
.\.venv-rag\Scripts\Activate.ps1

# 2) 装依赖（torch 走 CPU 源，省 2GB）
.\.venv-rag\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-rag\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3) 配置
Copy-Item .env.example .env
#    然后把 LLM_API_KEY 填成你自己的（.env 已在 .gitignore 里，不会被提交）

# 4) 自检 + 灌示例语料 + 起服务
.\.venv-rag\Scripts\python.exe scripts\check_env.py
.\.venv-rag\Scripts\python.exe scripts\seed_demo.py
.\.venv-rag\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

首次运行会下载两个本地模型（embedding 约 95MB、重排约 430MB），缓存到 `data/hf/`。

> 💡 **改完 `.env` 必须重启服务**：配置在启动时读一次，热改不生效。
> 这也是"配置明明改了却没效果"最常见的原因。

---

## 二、改代码前请先知道的四条项目规矩

这四条不是风格偏好，而是这个项目**刻意坚持的设计约束**，PR 会按它们来评审。

### 1. 计算归代码，解读归模型

数字、聚合、时间计算一律由代码算好再注入上下文；模型只负责"解读"。
**不要**让模型去做算术或跨表聚合——那会让数字可信度随模型版本波动。

### 2. 决策可以交给模型，控制流必须留给代码

模型可以决定"要不要再检一轮""证据够不够"；但**循环上限、超时、降级、兜底返回值**
必须是确定性代码。每个决策节点都要能返回一个**合法结果**，而不是抛异常。

### 3. 任何新能力都要配一条可执行的验收

不要只写"功能已实现"。至少给出一种**可复现的验证方式**：

```powershell
.\.venv-rag\Scripts\python.exe scripts\verify_all.py http://127.0.0.1:8000      # 朴素链路 L0~L7
.\.venv-rag\Scripts\python.exe scripts\verify_agentic.py http://127.0.0.1:8000  # Agent 决策层 A0~A9
```

新增检查项请加进对应的 `verify_*.py`，并保证**失败时退出码非 0**（CI 靠它拦截）。

### 4. 指标变了要说明口径

如果你改了检索/生成逻辑，请跑一次评测并贴出前后对比：

```powershell
.\.venv-rag\Scripts\python.exe scripts\eval_agentic.py --mode both --tag mychange ^
    --set data/eval_set_hardcorpus.json --top-k 4
```

**注意指标口径的坑**：`Hit@1 / MRR` 只在**单轮检索**下有意义。
Agent 每轮会把新证据**并入**证据池，证据条数变多会把"期望文档的名次"往后挤，
所以多轮场景请优先看 `Recall@k`、要点覆盖率与答案正确率，而不是 Hit@1。

---

## 三、提交前自查（30 秒）

```powershell
# 1) 静态自检：语法 + 硬编码密钥 + 大文件（一条命令覆盖三项）
.\.venv-rag\Scripts\python.exe scripts\check_syntax.py

# 2) 配置防静默失效：.env 里每一项都必须能被 Settings 识别
.\.venv-rag\Scripts\python.exe scripts\check_env.py --strict
```

两条命令都**失败时退出码非 0**，所以也能直接接 CI。

> 第 2 条为什么重要：pydantic-settings 是**按字段名**映射环境变量的。
> 字段名与 `.env` 变量名不一致时会被**静默忽略**（不报错、不警告，一直用代码默认值）。
> 本项目真实踩过这个坑，详见 [docs/踩坑记录_配置静默失效.md](docs/踩坑记录_配置静默失效.md)。

---

## 四、改动的组织方式

| 事项 | 约定 |
| --- | --- |
| 分支名 | `feat/xxx`、`fix/xxx`、`docs/xxx` |
| 提交信息 | 首行 `feat|fix|docs|refactor|chore: 简短说明`，正文讲**为什么**改，而不是罗列改了哪些文件 |
| 一个 PR 一件事 | 不要把"新功能 + 大规模重排版"混在一个 PR 里，评审会很难过 |
| 新增依赖 | 必需的进 `requirements.txt`，可选的进 `requirements-extra.txt`，并写清"不装会怎样" |
| 新增配置 | 同步更新 `.env.example`，**并确认字段名与变量名逐字一致**（见上文第三条自查） |
| 中文文案 | 中文标点用全角（，。：；），句末统一，不要中英标点混用 |
| PowerShell 脚本 | 含中文的 `.ps1` **必须存为 UTF-8 带 BOM**；否则中文 Windows 的 PowerShell 5.1 会解析失败（本项目踩过） |

### 编码与换行（`.editorconfig` 已覆盖，这里说明原因）

| 文件类型 | 约定 | 为什么 |
| --- | --- | --- |
| `.py` / `.md` / `.yml` | UTF-8，**LF** | 跨平台一致；Windows 上提交 CRLF 会让全文件 diff |
| `.ps1` | UTF-8 **带 BOM**，CRLF | 见上表最后一行：不带 BOM 时 PS 5.1 按 GBK 解码中文，直接语法错误 |
| `*.jsonl` / `*.csv` / 索引 | 不格式化、不加末尾换行 | 机器生成的数据，手工格式化会破坏内容 |

---

## 五、提 PR 时请写清四件事

1. **要解决什么问题**（现象 + 影响面），不是"我改了哪几个文件"；
2. **怎么验证的**（贴命令与输出，比如验收的 PASS/FAIL 统计）；
3. **有什么代价或未完成的地方**（延迟、成本、已知限制）——主动写出来比被问出来好；
4. **有没有指标变化**（若涉及检索/生成逻辑）。

---

## 六、几个常见坑（省你半小时）

| 现象 | 原因与处理 |
| --- | --- |
| 上传 CSV/JSON 被 400 拦掉 | `ALLOWED_EXTENSIONS` 没放开（解析器本身支持）；改完 `.env` **要重启服务** |
| 库里有分块但服务显示 0 篇文档 | `DATA_DIR` 是相对路径，从别的工作目录启动了；建议在 `.env` 里配绝对路径 |
| 首次回答特别慢 | 两个本地模型在下载/加载，之后有缓存 |
| `verify_*.py` 报找不到文件 | 脚本在 `scripts/` 下，要在项目根目录用 `scripts\verify_all.py` 调用 |
| PowerShell 脚本报 `Missing closing '}'` | `.ps1` 没有 BOM，中文被按 GBK 解码；存为 UTF-8 带 BOM |
| 关了重排之后质量明显下降 | 重排是必要环节，别关；要对比就做 A/B，别直接删 |

---

## 七、许可

本项目采用 MIT 许可（见 [LICENSE](LICENSE)）。提交 PR 即表示你同意以同一许可发布你的贡献。
