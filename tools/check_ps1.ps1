# Check PowerShell script encoding safety (ASCII-only on purpose).
#
# Why this tool exists:
#   Windows PowerShell 5.1 reads a .ps1 file without a BOM using the current ANSI
#   code page (GBK/936 on Chinese Windows). A UTF-8 file with Chinese text is then
#   mis-decoded: sometimes it prints garbage, sometimes the WHOLE SCRIPT SILENTLY
#   RUNS NOTHING (exit code 0, no output) -- which is very hard to diagnose.
#   Rule: if a .ps1 contains any non-ASCII character, it MUST be saved as
#   "UTF-8 with BOM". Pure ASCII files work either way.
#
# This script itself is ASCII-only so it can never suffer from the problem it detects.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/check_ps1.ps1 -Root scripts

param(
    [string]$Root = "scripts",
    [string]$Path = ""
)

function Test-OneScript([string]$file) {
    $bytes = [System.IO.File]::ReadAllBytes($file)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $nonAscii = 0
    foreach ($b in $bytes) { if ($b -gt 127) { $nonAscii++ } }

    # Decode as UTF-8 ourselves, then parse the STRING (avoids misleading errors
    # from parsing the file directly, which would use the ANSI code page).
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    if ($hasBom) { $text = $text.Substring(1) }
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
    $syntaxOk = ($null -eq $errors) -or ($errors.Count -eq 0)
    $encodingSafe = ($nonAscii -eq 0) -or $hasBom

    $name = Split-Path -Leaf $file
    if ($syntaxOk -and $encodingSafe) {
        Write-Output ("  PASS  {0,-24} syntax=OK  non-ASCII={1,-4} BOM={2}" -f $name, $nonAscii, $hasBom)
    } else {
        Write-Output ("  FAIL  {0,-24} syntax={1}  non-ASCII={2}  BOM={3}" -f `
            $name, $(if ($syntaxOk) { "OK" } else { "ERROR" }), $nonAscii, $hasBom)
        if (-not $syntaxOk) {
            foreach ($e in $errors) {
                Write-Output ("          line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message)
            }
        }
        if (-not $encodingSafe) {
            Write-Output "          FIX: contains non-ASCII but no UTF-8 BOM -> re-save as 'UTF-8 with BOM'."
            Write-Output "               (PS 5.1 decodes it as ANSI/GBK and may silently run nothing)"
        }
    }
}

$targets = @()
if ($Path) {
    $targets = @($Path)
} else {
    $targets = @(Get-ChildItem -Path $Root -Filter *.ps1 -Recurse -File | ForEach-Object { $_.FullName })
}

if ($targets.Count -eq 0) {
    Write-Output "No .ps1 files found under: $Root"
    exit 0
}

Write-Output "Checking $($targets.Count) PowerShell script(s):"
foreach ($t in $targets) { Test-OneScript $t }
