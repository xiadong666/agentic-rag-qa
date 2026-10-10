# Pull Request

## 这个 PR 解决什么问题

<!-- 现象 + 影响面。不要写"改了 xxx.py 和 yyy.py"——那是 diff 会说的 -->

## 改了什么

<!-- 用 2~4 条说明思路；关键设计取舍请写清楚 -->

## 怎么验证的

<!-- 贴命令与输出。至少覆盖下面两条静态自检，跨层改动请加验收 -->

```powershell
.\.venv-rag\Scripts\python.exe scripts\check_syntax.py
.\.venv-rag\Scripts\python.exe scripts\check_env.py --strict
```

```
粘贴输出摘要
```

- [ ] `scripts/check_syntax.py` 通过
- [ ] `scripts/check_env.py --strict` 通过
- [ ] 涉及接口/链路时，跑过 `scripts/verify_all.py` 或 `scripts/verify_agentic.py` 并全 PASS

## 指标变化（涉及检索/生成逻辑时必填）

<!-- 跑一次：eval_agentic.py --mode both --tag <你的标签> --set data/eval_set_hardcorpus.json -->

| 指标 | 改前 | 改后 |
| --- | --- | --- |
| Recall@k | | |
| 要点覆盖率 | | |
| 应答准确率 / 幻觉率 | | |
| 平均延迟 / 单问成本 | | |

> 提醒：`Hit@1 / MRR` 只在**单轮检索**下有意义。Agent 多轮会把新证据并入证据池，
> 证据变多会把期望文档的名次往后挤，所以多轮场景请看 `Recall@k`、要点覆盖率与答案正确率。

## 代价与未完成的事

<!-- 主动写出来：延迟、成本、已知限制、需要后续跟进的部分 -->

## 自查

- [ ] 没有提交 `.env`、模型缓存（`data/hf/`）、上传原文（`data/uploads/`）或任何密钥
- [ ] 新增配置同步更新了 `.env.example`，且**字段名与变量名逐字一致**
- [ ] 含中文的 `.ps1` 存为 UTF-8 带 BOM（否则 PS 5.1 报语法错）
- [ ] 中文标点统一（全角，句末一致）
