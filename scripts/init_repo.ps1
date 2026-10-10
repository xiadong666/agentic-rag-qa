# Create the git repository (local init + optional GitHub push)
#
# Why a script: in the AI sandbox a child process cannot create .git inside the project,
# so this step must run in YOUR own PowerShell window.
#
# ENCODING: this file is intentionally PURE ASCII.
#   Windows PowerShell 5.1 decodes a .ps1 without a BOM using the ANSI code page
#   (GBK/936 on Chinese Windows). If such a file contains Chinese text it gets
#   mis-decoded -- worst case the WHOLE SCRIPT SILENTLY RUNS NOTHING while still
#   returning exit code 0, which is painful to diagnose.
#   Keeping this file ASCII-only makes it immune, so no BOM is required.
#   (Other scripts in this repo that DO contain Chinese must be saved as UTF-8 with BOM;
#    verify with: powershell -File tools\check_ps1.ps1 -Root scripts)
#
# Usage:
#     cd <project root>
#     powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -Name "Your Name" -Email "you@example.com"
#     # create the GitHub repo and push in one go (needs gh CLI + gh auth login):
#     powershell -ExecutionPolicy Bypass -File scripts\init_repo.ps1 -CreateRemote

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
# 0) stale lock guard
#    An interrupted git command leaves .git/index.lock behind, and every later git
#    call then fails with "Unable to create index.lock: Permission denied".
#    That error looks like a permission problem but is usually just a stale file.
# ============================================================
$lock = Join-Path $root ".git\index.lock"
if (Test-Path $lock) {
    Write-Host "`nFound a stale git lock: $lock" -ForegroundColor Yellow
    Write-Host "This usually means a previous git command was interrupted (Ctrl+C)." -ForegroundColor Yellow
    $answer = Read-Host "Delete it and continue? [y/N]"
    if ($answer -match '^[Yy]') {
        Remove-Item $lock -Force
        Write-Host "  lock removed." -ForegroundColor Green
    } else {
        Write-Host "  Aborted. Close any running git process, then delete the file manually." -ForegroundColor Red
        exit 1
    }
}

# ============================================================
# 1) Safety check: never commit secrets or model caches
#
#    IMPORTANT: scan only files that WOULD BE COMMITTED, not everything on disk.
#    A first version scanned the whole tree and flagged data/uploads/ (old test
#    uploads containing a key) and data/hf/ (1.1 GB model cache) -- but both are
#    already excluded by .gitignore, so reporting them was a false alarm that made
#    people think they had to delete their data.
#     => tracked files + untracked-but-not-ignored files.
# ============================================================
function Get-RepoTrackedFiles {
    # -c core.quotepath=false: without it git escapes non-ASCII paths into
    #   "...\232\204" style strings, which then blow up Test-Path with
    #   "Illegal characters in path".
    # -z + NUL split: keeps names containing spaces/specials intact.
    $tracked = @(git -c core.quotepath=false ls-files -z) -split "`0" | Where-Object { $_ }
    $untracked = @(git -c core.quotepath=false ls-files -z --others --exclude-standard) -split "`0" | Where-Object { $_ }
    return @($tracked + $untracked | Sort-Object -Unique)
}

if (-not $SkipSafetyCheck) {
    Write-Host "`n=== Safety check ===" -ForegroundColor Cyan
    $problems = @()

    $ignored = git check-ignore -v .env 2>$null
    if (-not $ignored) { $problems += ".env is NOT ignored by .gitignore" }

    $files = Get-RepoTrackedFiles
    Write-Host ("  scanning {0} file(s) that would be committed" -f $files.Count)

    # ---- 1.1 hardcoded secrets (text files only) ----
    $scanExt = @('.py', '.js', '.json', '.md', '.yml', '.yaml', '.txt', '.ps1', '.sh', '.toml', '.ini', '.css', '.html')
    $hits = @()
    foreach ($rel in $files) {
        if (-not (Test-Path -LiteralPath $rel)) { continue }
        if ($scanExt -notcontains [System.IO.Path]::GetExtension($rel).ToLower()) { continue }
        $found = Select-String -LiteralPath $rel -Pattern 'sk-[A-Za-z0-9]{20,}' -ErrorAction SilentlyContinue
        if ($found) { $hits += $found }
    }
    if ($hits) {
        $problems += ("hardcoded secret found: {0} hit(s)" -f $hits.Count)
        $hits | Select-Object -First 5 | ForEach-Object {
            $problems += ("    {0}:{1}" -f $_.Path.Replace($root + '\', ''), $_.LineNumber)
        }
    }

    # ---- 1.2 oversized files ----
    $big = @()
    foreach ($rel in $files) {
        if (-not (Test-Path -LiteralPath $rel)) { continue }
        $len = (Get-Item -LiteralPath $rel).Length
        if ($len -gt 50MB) {
            $big += ("{0} ({1} MB)" -f $rel, [Math]::Round($len / 1MB, 1))
        }
    }
    if ($big) {
        $problems += "file larger than 50MB (should not be committed):"
        $big | Select-Object -First 5 | ForEach-Object { $problems += ("    {0}" -f $_) }
    }

    if ($problems.Count) {
        Write-Host "  Problems found:" -ForegroundColor Red
        $problems | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        Write-Host "`n  Aborted. Fix them first (or re-run with -SkipSafetyCheck)." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  OK: .env is ignored" -ForegroundColor Green
    Write-Host "  OK: no hardcoded secret in files that would be committed" -ForegroundColor Green
    Write-Host "  OK: no oversized file" -ForegroundColor Green
    Write-Host "  (data/uploads and data/hf are ignored by .gitignore, so they are skipped on purpose)" -ForegroundColor DarkGray
}

# ============================================================
# 2) git identity
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
# 3) init + commit
# ============================================================
if (-not (Test-Path ".git")) {
    Write-Host "`n=== git init ===" -ForegroundColor Cyan
    git init -b main
} else {
    Write-Host "`nAlready a git repository, continue." -ForegroundColor Cyan
}

git add -A
Write-Host "`n=== Staged files ===" -ForegroundColor Cyan
$staged = @(git -c core.quotepath=false diff --cached --name-only)
Write-Host ("  total: {0}" -f $staged.Count)
$staged | Group-Object { ($_ -split '/')[0] } | Sort-Object Count -Descending |
    Select-Object -First 8 | ForEach-Object { Write-Host ("    {0,-16} {1,4}" -f $_.Name, $_.Count) }

$leak = $staged | Where-Object { $_ -eq ".env" -or $_ -like "data/hf/*" -or $_ -like "data/uploads/*" }
if ($leak) {
    Write-Host "`n  Refusing to commit these files:" -ForegroundColor Red
    $leak | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}

$pending = @(git status --porcelain)
if ($pending.Count -eq 0) {
    Write-Host "`nNothing to commit - repository already up to date." -ForegroundColor Cyan
} else {
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
- Three Word deliverables: migration tutorial, verification guide, learning tutorial
  (generated by scripts/build_agentic_rag_doc.py and docs/gen/build*.py)
- Markdown sources: the two-part migration tutorial and a real config-drift
  postmortem in docs/ (config silently ignored because the field name and the
  .env variable name did not match)
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
}

# ============================================================
# 4) remote
# ============================================================
if ($RemoteUrl) {
    git remote remove origin 2>$null
    git remote add origin $RemoteUrl
    Write-Host "`norigin = $RemoteUrl" -ForegroundColor Green
    Write-Host "Now run: git push -u origin main" -ForegroundColor Yellow
}
elseif ($CreateRemote) {
    # winget installs gh, but the PATH of the CURRENT window is stale, so
    # Get-Command cannot find it. Fall back to the known install locations.
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    $ghExe = if ($gh) { $gh.Source } else { $null }
    if (-not $ghExe) {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\gh.exe"),
            (Join-Path $env:ProgramFiles "GitHub CLI\gh.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "GitHub CLI\gh.exe")
        )
        $ghExe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if ($ghExe) {
            Write-Host "`ngh not on PATH but found at: $ghExe" -ForegroundColor DarkGray
            Write-Host "(PATH in this window is stale after installing; using the full path instead)" -ForegroundColor DarkGray
        }
    }

    if (-not $ghExe) {
        Write-Host "`ngh CLI not found, cannot create the remote automatically." -ForegroundColor Yellow
        Write-Host "Option 1: install gh  ->  winget install --id GitHub.cli" -ForegroundColor Yellow
        Write-Host "          then open a NEW PowerShell window (PATH refresh) and run: gh auth login" -ForegroundColor Yellow
        Write-Host "Option 2: create an empty repo on github.com, then run:" -ForegroundColor Yellow
        Write-Host "    git remote add origin https://github.com/<user>/$RepoName.git" -ForegroundColor Yellow
        Write-Host "    git push -u origin main" -ForegroundColor Yellow
        exit 0
    }

    # Check login state first, otherwise gh repo create stops midway asking for a token.
    & $ghExe auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`ngh is installed but not logged in. Run this first, then re-run the script:" -ForegroundColor Yellow
        Write-Host "    & `"$ghExe`" auth login" -ForegroundColor Yellow
        exit 0
    }

    Write-Host "`nCreating GitHub repo '$RepoName' and pushing..." -ForegroundColor Cyan
    & $ghExe repo create $RepoName --public --source=. --remote=origin --push `
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
