# 把生成好的 Word 成品与评测报告复制到项目里
#
# 背景：某些受控环境（企业策略 / AI 沙箱）里，脚本进程没有项目目录的写权限，
# 于是 Word 成品与评测报告会先落在暂存目录，需要手工搬一次。
# 这个脚本就是那次"搬运"，在你的普通 PowerShell 里运行即可（权限跟着登录用户走）。
#
# ⚠️ 本文件必须保存为「UTF-8 带 BOM」：
#    Windows PowerShell 5.1 读取 .ps1 时，若无 BOM 会按 ANSI 代码页（中文 Windows 上是 GBK）
#    解码，文件里的中文会变乱码并直接导致语法错误（Missing closing '}' 之类）。
#    本文件第一行开头就是 BOM 字符（），请勿删除。
#
# 用法（在项目根目录或任意位置都可）：
#     powershell -ExecutionPolicy Bypass -File scripts/copy_deliverables.ps1
#     powershell -ExecutionPolicy Bypass -File scripts/copy_deliverables.ps1 -Source "D:\Deepseek\dsh\_outbox"

param(
    [string]$Source = "D:\Deepseek\dsh\_outbox",
    [string]$EvalHard = "D:\Deepseek\dsh\_eval_hard",
    [string]$EvalEasy = "D:\Deepseek\dsh\_eval_run",
    [string]$EvalCorpus = "D:\Deepseek\dsh\_eval_hc"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot          # 项目根 = scripts 的上一级
$docs = Join-Path $root "docs"
$data = Join-Path $root "data"

Write-Host "项目根目录：$root" -ForegroundColor Cyan
Write-Host "暂存目录：  $Source" -ForegroundColor Cyan

# ---------- 1) Word 成品 → docs/ ----------
$docFiles = @(
    "Agentic_RAG_改造全流程教程_v2.docx",                 # 含困难语料章节与三组指标
    "Agentic_RAG_改造指标速记卡.docx",
    "Agentic_RAG_项目实操手册_跑起来改参数弄坏它.docx",
    "AI应用开发面试题库_RAG与Agent.docx",                 # 已含 Q171~Q190（共 190 题）
    "AI应用开发面试题库_RAG与Agent.txt",
    "RAG知识库问答系统_学习巩固教程.docx",
    "如何验证RAG知识库问答系统是正确的.docx"
)
foreach ($f in $docFiles) {
    $src = Join-Path $Source $f
    if (Test-Path $src) {
        Copy-Item $src $docs -Force
        Write-Host "  [OK]   docs\$f" -ForegroundColor Green
    } else {
        Write-Host "  [跳过] 未找到：$src" -ForegroundColor Yellow
    }
}

# ---------- 2) 评测报告 → data/（教程与简历的数据来源） ----------
$pair = @(
    @{ From = $EvalHard;   Name = "eval_compare_hard.json" },
    @{ From = $EvalHard;   Name = "eval_report_baseline_hard.json" },
    @{ From = $EvalHard;   Name = "eval_report_agentic_hard.json" },
    @{ From = $EvalEasy;   Name = "eval_compare_easy.json" },
    @{ From = $EvalEasy;   Name = "eval_report_baseline_easy.json" },
    @{ From = $EvalEasy;   Name = "eval_report_agentic_easy.json" },
    @{ From = $EvalCorpus; Name = "eval_compare_hardcorpus.json" },
    @{ From = $EvalCorpus; Name = "eval_report_baseline_hardcorpus.json" },
    @{ From = $EvalCorpus; Name = "eval_report_agentic_hardcorpus.json" }
)
foreach ($p in $pair) {
    $src = Join-Path $p.From $p.Name
    if (Test-Path $src) {
        Copy-Item $src $data -Force
        Write-Host "  [OK]   data\$($p.Name)" -ForegroundColor Green
    } else {
        Write-Host "  [跳过] 未找到：$src" -ForegroundColor Yellow
    }
}

# ---------- 3) 自检：确认关键文件到位 ----------
Write-Host "`n=== 自检 ===" -ForegroundColor Cyan
$checks = @(
    (Join-Path $docs "Agentic_RAG_改造全流程教程_v2.docx"),
    (Join-Path $docs "Agentic_RAG_改造指标速记卡.docx"),
    (Join-Path $docs "Agentic_RAG_项目实操手册_跑起来改参数弄坏它.docx"),
    (Join-Path $docs "AI应用开发面试题库_RAG与Agent.docx"),
    (Join-Path $docs "RAG知识库问答系统_学习巩固教程.docx"),
    (Join-Path $docs "如何验证RAG知识库问答系统是正确的.docx"),
    (Join-Path $data "eval_compare_hard.json"),
    (Join-Path $data "eval_compare_easy.json"),
    (Join-Path $data "eval_compare_hardcorpus.json"),
    (Join-Path $root "app\core\agent.py"),
    (Join-Path $root "scripts\eval_agentic.py"),
    (Join-Path $root "scripts\verify_agentic.py"),
    (Join-Path $root "scripts\seed_hard_corpus.py"),
    (Join-Path $root "scripts\check_env.py"),
    (Join-Path $root "scripts\init_repo.ps1"),
    (Join-Path $root "sample_docs\hard\test_cases.json"),
    (Join-Path $root ".github\workflows\ci.yml"),
    (Join-Path $root "LICENSE")
)
$missing = 0
foreach ($c in $checks) {
    if (Test-Path $c) {
        Write-Host ("  [有] {0}" -f (Split-Path -Leaf $c)) -ForegroundColor Green
    } else {
        Write-Host ("  [缺] {0}" -f $c) -ForegroundColor Red
        $missing++
    }
}
if ($missing -eq 0) {
    Write-Host "`n全部就位。" -ForegroundColor Cyan
} else {
    Write-Host "`n有 $missing 项缺失，请检查上面的路径。" -ForegroundColor Yellow
}
