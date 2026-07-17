$ErrorActionPreference = "Stop"
$path = "e:\Agent_reply\.trae\documents\plan-agent-perspective-llm-research-and-roadmap-v10.1.1.md"
$bak = "e:\Agent_reply\.trae\documents\plan-agent-perspective-llm-research-and-roadmap-v10.1.1.md.bak.20260717195110"

if (-not (Test-Path $bak)) {
    Write-Host "[ERROR] backup not found, abort"
    exit 1
}

# 读取 bak 文件
$lines = [System.IO.File]::ReadAllLines($bak)
$origLineCount = $lines.Count
$origCharCount = ($lines | Measure-Object -Character).Characters
Write-Host "[1/4] original: $origLineCount lines / $origCharCount chars"
Write-Host "    backup: $bak"

# ── 23 章节（5 大区块·新顺序）──
$json = @'
[
    {"name":"header",         "start":1,    "end":43},
    {"name":"0_TLDR",         "start":43,   "end":214},
    {"name":"M_history",      "start":3275, "end":3449},
    {"name":"A_version",      "start":214,  "end":256},
    {"name":"B_phase0",       "start":256,  "end":346},
    {"name":"C_phase1",       "start":346,  "end":547},
    {"name":"D_phase2",       "start":547,  "end":1387},
    {"name":"E_phase3",       "start":1387, "end":1810},
    {"name":"F_phase4",       "start":1810, "end":1868},
    {"name":"G_ver",          "start":1868, "end":2155},
    {"name":"H_archC",        "start":2155, "end":2259},
    {"name":"I_noLang",       "start":2259, "end":2341},
    {"name":"J_trace",        "start":2341, "end":2698},
    {"name":"K_decisions",    "start":2698, "end":2919},
    {"name":"L_floatingball", "start":3062, "end":3275},
    {"name":"Q_personaSSOT",  "start":3782, "end":4147},
    {"name":"appendixA",      "start":2919, "end":2943},
    {"name":"appendixB",      "start":2943, "end":2967},
    {"name":"appendixC",      "start":2967, "end":3003},
    {"name":"appendixD",      "start":3003, "end":3062},
    {"name":"N_disclaimer",   "start":3449, "end":3540},
    {"name":"O_notice",       "start":3540, "end":3710},
    {"name":"P_contact",      "start":3710, "end":3782}
]
'@
$arr = $json | ConvertFrom-Json

Write-Host "[2/4] sections count: $($arr.Count)"

# ── 拼接：先 build List[string] 再用 Set-Content 写 ──
$outLines = [System.Collections.Generic.List[string]]::new()

for ($idx = 0; $idx -lt $arr.Count; $idx++) {
    $sec = $arr[$idx]
    $start = $sec.start - 1
    $end   = $sec.end - 1  # 0-based 半开 [start, end)

    for ($i = $start; $i -lt $end; $i++) {
        if ($i -lt 0 -or $i -ge $lines.Count) { continue }
        $outLines.Add($lines[$i])
    }

    if ($idx -lt $arr.Count - 1) {
        $outLines.Add("---")
        $outLines.Add("")
    }
}

Write-Host "    built $($outLines.Count) lines"

# ── 用 Set-Content 写（UTF8 No BOM, LF 换行）──
$content = ($outLines -join "`n")
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $content, $utf8NoBom)

$newLineCount = ([System.IO.File]::ReadAllLines($path)).Count
$newCharCount = $content.Length
Write-Host "[3/4] new file: $newLineCount lines / $newCharCount chars"
Write-Host "    delta: lines = $($origLineCount - $newLineCount), chars = $($origCharCount - $newCharCount)"

# ── 验证 ──
$newLines = [System.IO.File]::ReadAllLines($path)
$realOrigH1 = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^#[^#]') { $realOrigH1 += $lines[$i].Trim() }
}
$realNewH1 = @()
for ($i = 0; $i -lt $newLines.Count; $i++) {
    if ($newLines[$i] -match '^#[^#]') { $realNewH1 += $newLines[$i].Trim() }
}

Write-Host "[4/4] H1 validation:"
Write-Host "    orig H1: $($realOrigH1.Count), new H1: $($realNewH1.Count)"

$missing = $realOrigH1 | Where-Object { $_ -notin $realNewH1 }
$added   = $realNewH1  | Where-Object { $_ -notin $realOrigH1 }
if ($missing.Count -gt 0) {
    Write-Host "    MISSING: $($missing.Count) [FAIL]"
    $missing | Select-Object -First 5 | ForEach-Object { Write-Host "      - $_" }
} else {
    Write-Host "    missing: 0 [OK]"
}
if ($added.Count -gt 0) {
    Write-Host "    ADDED: $($added.Count) [FAIL]"
    $added | Select-Object -First 5 | ForEach-Object { Write-Host "      + $_" }
} else {
    Write-Host "    added: 0 [OK]"
}

# 验证开头字节
$firstBytes = [System.IO.File]::ReadAllBytes($path)
Write-Host "    first 4 bytes: $($firstBytes[0]) $($firstBytes[1]) $($firstBytes[2]) $($firstBytes[3]) (expect 45 45 45 10 = --- LF)"
