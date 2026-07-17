# gen_toc_v4.ps1 - TOC generator (no Chinese in script, uses [char] escapes)
# Avoids the GBK-misread issue entirely: all Chinese is expressed as
# unicode hex codes so the .ps1 source can be parsed as ASCII.

$ErrorActionPreference = "Stop"
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding          = [System.Text.Encoding]::UTF8

# ── Paths ──
$root = "e:\Agent_reply"
$path = Join-Path $root ".trae\documents\plan-agent-perspective-llm-research-and-roadmap-v10.1.1.md"
$kwFile = Join-Path $root "gen_toc_keywords.txt"

# Helper: build a string from unicode codepoints
function From-CodePoints {
    param([int[]]$codes)
    $sb = New-Object System.Text.StringBuilder
    foreach ($c in $codes) { [void]$sb.Append([char]$c) }
    return $sb.ToString()
}

# 'Mu Lu' = U+76EE ("目" = 30446) + U+5F55 ("录" = 24405)
$TOC_TITLE = From-CodePoints @(30446, 24405)   # "目录"
$COMMENT_HASH = [char]35                       # "#"
$KW_SEP = [char]124                            # "|"
$COLON = [char]58                              # ":"

Write-Host "TOC title string: $TOC_TITLE"

# ── Read keywords file (UTF-8) ──
$rawKw = [System.IO.File]::ReadAllText($kwFile, [System.Text.Encoding]::UTF8)
$blockDefs = @{}
$blockOrder = New-Object System.Collections.Generic.List[string]
foreach ($line in ($rawKw -split "`r?`n")) {
    $trim = $line.Trim()
    if ($trim.StartsWith($COMMENT_HASH) -or $trim -eq "") { continue }
    $colonIdx = $trim.IndexOf($COLON)
    if ($colonIdx -lt 0) { continue }
    $blockName = $trim.Substring(0, $colonIdx).Trim()
    $kwStr = $trim.Substring($colonIdx + 1).Trim()
    $kws = @()
    foreach ($part in ($kwStr -split [regex]::Escape($KW_SEP))) {
        $t = $part.Trim()
        if ($t -ne "") { $kws += $t }
    }
    $blockDefs[$blockName] = $kws
    $blockOrder.Add($blockName)
}
if ($blockDefs.Count -eq 0) {
    Write-Host "[ERROR] No blocks loaded from $kwFile"
    exit 1
}
Write-Host "Loaded $($blockDefs.Count) block definitions: $($blockOrder -join ', ')"

# ── Block display labels (ASCII safe) ──
$blockLabels = @{
    "BLOCK_ENTRANCE" = "[ENTRANCE] Entrance Zone"
    "BLOCK_CORE"     = "[CORE] Core Technical Zone"
    "BLOCK_NEW"      = "[NEW] v10.1.1 Increment Tasks Zone"
    "BLOCK_APPENDIX" = "[APPENDIX] Appendix Zone"
    "BLOCK_OPS"      = "[OPS] Ops / Contact Zone"
}

# ── Load doc as UTF-8 ──
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$text = [System.IO.File]::ReadAllText($path, $utf8Bom)
$lines = $text -split "`r?`n"
Write-Host "Loaded $($lines.Count) lines from doc"

# ── Anchor generation ──
function Get-Anchor {
    param($title)
    $a = $title.ToLower()
    # strip non-ASCII-non-CJK-non-space-non-dash
    $a = [regex]::Replace($a, '[^\u0000-\u007F\u4e00-\u9fff\s-]', '')
    $a = $a -replace '\s+', '-'
    $a = $a -replace '-+', '-'
    return $a.Trim('-')
}

# ── Parse headings, tracking code fences ──
$headings = New-Object System.Collections.Generic.List[object]
$inFence = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match '^\s*```') {
        $inFence = -not $inFence
        continue
    }
    if ($inFence) { continue }
    if ($line -match '^# [^#]') {
        $title = $line.Trim() -replace '^# ', ''
        $headings.Add([PSCustomObject]@{
            Level = 1; Line = $i + 1; Title = $title; Anchor = (Get-Anchor $title)
        })
    } elseif ($line -match '^## ') {
        $title = $line.Trim() -replace '^## ', ''
        $headings.Add([PSCustomObject]@{
            Level = 2; Line = $i + 1; Title = $title; Anchor = (Get-Anchor $title)
        })
    }
}
Write-Host "Parsed $($headings.Count) headings (code fences skipped)"

# ── Locate old TOC (## 目录) using pattern with code points ──
# The "## " + TOC_TITLE + optional whitespace
$tocHeaderPattern = '^##\s+' + [regex]::Escape($TOC_TITLE) + '\s*$'
$tocStartLine = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $tocHeaderPattern) {
        $tocStartLine = $i + 1
        break
    }
}
if ($tocStartLine -lt 0) {
    Write-Host "[ERROR] '## $TOC_TITLE' not found"
    exit 1
}

# Find end (next ## or # line after tocStart)
$tocEndLine = $tocStartLine + 1
for ($i = $tocStartLine; $i -lt $lines.Count; $i++) {
    if ($i + 1 -lt $lines.Count) {
        $next = $lines[$i + 1]
        if ($next -match '^# [^#]' -or $next -match '^## ') {
            $tocEndLine = $i + 1
            break
        }
    }
}
Write-Host "Old TOC location: 1-based $tocStartLine - $tocEndLine"

# ── Main H1 (first) ──
$mainTitle = $headings | Where-Object { $_.Level -eq 1 } | Select-Object -First 1

# ── Map H1 to block via keyword substring match ──
function Find-Block {
    param($h1, $defs, $order)
    foreach ($bk in $order) {
        $kws = $defs[$bk]
        foreach ($kw in $kws) {
            if ($h1.Title -like "*$kw*") { return $bk }
        }
    }
    return $null
}

$allH1 = $headings | Where-Object { $_.Level -eq 1 -and $_ -ne $mainTitle }
$grouped = @{}
foreach ($bk in $blockOrder) { $grouped[$bk] = New-Object System.Collections.Generic.List[object] }
$unmatched = New-Object System.Collections.Generic.List[object]
foreach ($h1 in $allH1) {
    $bk = Find-Block $h1 $blockDefs $blockOrder
    if ($bk) { $grouped[$bk].Add($h1) } else { $unmatched.Add($h1) }
}

Write-Host ""
Write-Host "===== Block allocation ====="
foreach ($bk in $blockOrder) {
    Write-Host "  $($blockLabels[$bk]): $($grouped[$bk].Count) H1s"
}
if ($unmatched.Count -gt 0) {
    Write-Host "  [UNMATCHED H1s]: $($unmatched.Count)"
    foreach ($u in $unmatched) {
        Write-Host "    - L$($u.Line) $($u.Title)"
    }
}

# ── Build new TOC lines ──
$tocOut = New-Object System.Collections.Generic.List[string]
[void]$tocOut.Add("## $TOC_TITLE")
[void]$tocOut.Add("")
if ($mainTitle) {
    [void]$tocOut.Add("- [$($mainTitle.Title)](#$($mainTitle.Anchor))")
    [void]$tocOut.Add("")
}

foreach ($bk in $blockOrder) {
    [void]$tocOut.Add("### $($blockLabels[$bk])")
    [void]$tocOut.Add("")
    foreach ($h1 in $grouped[$bk]) {
        [void]$tocOut.Add("- [$($h1.Title)](#$($h1.Anchor))")
        $idx = $headings.IndexOf($h1)
        $nextH1Line = 9999999
        for ($j = $idx + 1; $j -lt $headings.Count; $j++) {
            if ($headings[$j].Level -eq 1) { $nextH1Line = $headings[$j].Line; break }
        }
        $h2s = $headings | Where-Object { $_.Level -eq 2 -and $_.Line -gt $h1.Line -and $_.Line -lt $nextH1Line -and $_.Title -ne $TOC_TITLE }
        foreach ($h2 in $h2s) {
            [void]$tocOut.Add("  - [$($h2.Title)](#$($h2.Anchor))")
        }
    }
    [void]$tocOut.Add("")
}

# ── Preview ──
Write-Host ""
Write-Host "===== New TOC preview ($($tocOut.Count) lines) ====="
foreach ($l in $tocOut) { Write-Host $l }
Write-Host "===== End preview ====="

# ── Apply ──
$newLines = New-Object System.Collections.Generic.List[string]
for ($i = 0; $i -lt $tocStartLine - 1; $i++) { [void]$newLines.Add($lines[$i]) }
foreach ($l in $tocOut) { [void]$newLines.Add($l) }
for ($i = $tocEndLine; $i -lt $lines.Count; $i++) { [void]$newLines.Add($lines[$i]) }

$bak = $path + ".bak.beforetoc." + (Get-Date -Format 'yyyyMMddHHmmss')
Copy-Item -Path $path -Destination $bak -Force

$content = ($newLines -join "`n")
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $content, $utf8NoBom)

$finalSize = (Get-Item $path).Length
$finalLineCount = ([System.IO.File]::ReadAllLines($path)).Count
Write-Host ""
Write-Host "Backup: $bak"
Write-Host "New file: $finalLineCount lines / $finalSize bytes"
Write-Host "Delta: $($lines.Count - $finalLineCount) lines (orig $($lines.Count) -> new $finalLineCount)"
