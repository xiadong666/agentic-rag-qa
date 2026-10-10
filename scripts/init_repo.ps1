# Create the git repository (local init + optional GitHub push)
#
# Why a script: in the AI sandbox a child process cannot create .git inside the project,
# so this step must run in YOUR own PowerShell window.
#
# ASCII-only on purpose: Windows PowerShell 5.1 decodes .ps1 using the ANSI code page
# (GBK on Chinese Windows) unless the file has a UTF-8 BOM. Keeping the file ASCII-only
# makes it parse correctly on every machine and locale.
#
# Usage:
#     cd D:\Deepseek\dsh\rag-qa-system
#     powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -Name "Deng Hao" -Email "you@example.com"
#     # create the GitHub repo and push in one go (needs gh CLI + gh auth login):
#     powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -Name "Deng Hao" -Email "you@example.com" -CreateRemote

param(
    [string]$Name = "",
    [string]$Email = "",
    [string]$RemoteUrl = "",
    [switch]$CreateRemote,
    [string]$RepoName = "agentic-rag-qa",
    [switch]$SkipSafetyCheck
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "Project: $root" -ForegroundColor Cyan

# ============================================================
# 0) Safety check: never commit secrets or model caches
# ============================================================
if (-not $SkipSafetyCheck) {
    Write-Host "`n=== Safety check ===" -ForegroundColor Cyan
    $problems = @()

    $ignored = git check-ignore -v .env 2>$null
    if (-not $ignored) { $problems += ".env is NOT ignored by .gitignore" }

    $hits = Get-ChildItem -Recurse -File -Include *.py,*.js,*.json,*.md,*.yml,*.yaml,*.txt,*.ps1,*.sh |
        Where-Object { $_.FullName -notmatch '\\(\.venv|\.venv-rag|node_modules|__pycache__|\.git)\\' } |
        Select-String -Pattern 'sk-[A-Za-z0-9]{20,}' -ErrorAction SilentlyContinue
    if ($hits) {
        $problems += ("hardcoded secret found: {0} hit(s)" -f $hits.Count)
        $hits | Select-Object -First 5 | ForEach-Object {
            $problems += ("    {0}:{1}" -f $_.Path.Replace($root + '\', ''), $_.LineNumber)
        }
    }

    $big = Get-ChildItem -Recurse -File | Where-Object {
        $_.Length -gt 50MB -and $_.FullName -notmatch '\\(\.venv|\.venv-rag|\.git)\\'
    }
    if ($big) {
        $problems += "file larger than 50MB (should not be committed):"
        $big | Select-Object -First 5 | ForEach-Object {
            $problems += ("    {0} ({1} MB)" -f $_.FullName.Replace($root + '\', ''), [Math]::Round($_.Length / 1MB, 1))
        }
    }

    if ($problems.Count) {
        Write-Host "  Problems found:" -ForegroundColor Red
        $problems | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        Write-Host "`n  Aborted. Fix them first (or re-run with -SkipSafetyCheck)." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  OK: .env is ignored" -ForegroundColor Green
    Write-Host "  OK: no hardcoded secret" -ForegroundColor Green
    Write-Host "  OK: no oversized file" -ForegroundColor Green
}

# ============================================================
# 1) git identity
# ============================================================
if ($Name) { git config user.name $Name }
if ($Email) { git config user.email $Email }
$curName = git config user.name 2>$null
$curEmail = git config user.email 2>$null
if (-not $curName -or -not $curEmail) {
    Write-Host "`nMissing git identity. Re-run with:" -ForegroundColor Yellow
    Write-Host '    powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -Name "Your Name" -Email "you@example.com"' -ForegroundColor Yellow
    exit 1
}
Write-Host "`ngit identity: $curName <$curEmail>" -ForegroundColor Cyan

# ============================================================
# 2) init + commit
# ============================================================
if (-not (Test-Path ".git")) {
    Write-Host "`n=== git init ===" -ForegroundColor Cyan
    git init -b main
} else {
    Write-Host "`nAlready a git repository, continue." -ForegroundColor Cyan
}

git add -A
Write-Host "`n=== Staged files ===" -ForegroundColor Cyan
$staged = @(git diff --cached --name-only)
Write-Host ("  total: {0}" -f $staged.Count)
$staged | Group-Object { ($_ -split '/')[0] } | Sort-Object Count -Descending |
    Select-Object -First 8 | ForEach-Object { Write-Host ("    {0,-16} {1,4}" -f $_.Name, $_.Count) }

$leak = $staged | Where-Object { $_ -eq ".env" -or $_ -like "data/hf/*" -or $_ -like "data/uploads/*" }
if ($leak) {
    Write-Host "`n  Refusing to commit these files:" -ForegroundColor Red
    $leak | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}

$msgPath = Join-Path $env:TEMP "rag_commit_msg.txt"
@'
feat: Agentic RAG enterprise knowledge-base QA and decision system

Upgrade the naive RAG pipeline (retrieve once -> rerank -> generate) into an agentic
loop with explicit decision points: plan -> multi-round retrieve -> relevance grade ->
reflect/rewrite -> generate -> faithfulness verify.

Core
- Controlled agent state machine (self-built, no orchestration framework): decisions to
  the model, control flow and fallbacks stay deterministic code
- Guardrails: short-circuit refusal when no evidence (no wasted model calls); score-floor
  protection keeps high-score evidence when the grader says "insufficient"
- Six orthogonal tools (search / rewrite / compress / decision memo / kb stats / safe calc)
  behind one JSON Schema contract, with schema retry, loose-JSON fallback and safe defaults
- Two anti-hallucination gates: pre-generation relevance filter, post-generation
  faithfulness check that flags unsupported statements
- Observability: SSE trace (plan/tool/grade/reflect/verify) and per-node token/cost accounting
- Governance: three-tier model routing (small/default/strong), agent switch for scenario routing

Retrieval stack
- Multi-format parsing (PDF/Word/Markdown/CSV, page numbers preserved) -> Chinese-aware
  chunking -> local bge embeddings
- Hybrid retrieval: dense + self-implemented BM25 + RRF fusion -> cross-encoder rerank
- Pluggable vector store: FAISS (in-process) or Qdrant (local/service)

Evaluation and acceptance
- 3 annotated sets, 47 questions total, including 13 unanswerable hallucination probes
- Dual-pipeline comparison: answer accuracy 100%, hallucination rate 0.0%,
  Recall@4 100% on the enterprise hard corpus
- Acceptance suites: 21 checks for the naive chain + 22 checks for the agent decision layer,
  non-zero exit code wired into CI
- CI: static checks (config drift / syntax / secret scan) plus end-to-end acceptance

Docs
- Six Word deliverables: migration tutorial, hands-on lab manual, metrics card,
  verification guide, learning tutorial, 190-question interview bank
'@ | Set-Content -Path $msgPath -Encoding UTF8

git commit -q -F $msgPath
$commitOk = ($LASTEXITCODE -eq 0)
Remove-Item $msgPath -Force -ErrorAction SilentlyContinue
if (-not $commitOk) {
    Write-Host "`nCommit failed, see git output above." -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Commit ===" -ForegroundColor Cyan
git log --oneline -1
git status --short | Select-Object -First 5

# ============================================================
# 3) remote
# ============================================================
if ($RemoteUrl) {
    git remote remove origin 2>$null
    git remote add origin $RemoteUrl
    Write-Host "`norigin = $RemoteUrl" -ForegroundColor Green
    Write-Host "Now run: git push -u origin main" -ForegroundColor Yellow
}
elseif ($CreateRemote) {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        Write-Host "`ngh CLI not found, cannot create the remote automatically." -ForegroundColor Yellow
        Write-Host "Option 1: install gh  ->  winget install --id GitHub.cli   then  gh auth login" -ForegroundColor Yellow
        Write-Host "Option 2: create an empty repo on github.com, then run:" -ForegroundColor Yellow
        Write-Host "    git remote add origin https://github.com/<user>/$RepoName.git" -ForegroundColor Yellow
        Write-Host "    git push -u origin main" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "`nCreating GitHub repo '$RepoName' and pushing..." -ForegroundColor Cyan
    gh repo create $RepoName --public --source=. --remote=origin --push `
        --description "Agentic RAG enterprise knowledge-base QA and decision system (FastAPI + LangChain)"
}
else {
    Write-Host "`nLocal repository is ready. Next step (pick one):" -ForegroundColor Cyan
    Write-Host "  1) create the remote and push with gh:" -ForegroundColor Yellow
    Write-Host "     powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -CreateRemote" -ForegroundColor Yellow
    Write-Host "  2) after creating an empty repo on GitHub:" -ForegroundColor Yellow
    Write-Host "     git remote add origin https://github.com/<user>/$RepoName.git" -ForegroundColor Yellow
    Write-Host "     git push -u origin main" -ForegroundColor Yellow
}

Write-Host "`nDone." -ForegroundColor Green
