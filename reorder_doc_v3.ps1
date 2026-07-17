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
# 用 JSON 数组定义，避免 PowerShell hashtable 行为
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
$totalTake = 0
for ($i = 0; $i -lt $arr.Count; $i++) {
    $sec = $arr[$i]
    $len = $sec.end - $sec.start
    $totalTake += $len
    Write-Host ("    [{0,2}] {1,-18} [{2,4}, {3,4}) = {4,3} lines" -f ($i+1), $sec.name, $sec.start, $sec.end, $len)
}
Write-Host "    total to take: $totalTake (orig total: $origLineCount)"

# ── 拼接 ──
$sb = [System.Text.StringBuilder]::new(($origCharCount * 1.2))

for ($idx = 0; $idx -lt $arr.Count; $idx++) {
    $sec = $arr[$idx]
    $start = $sec.start - 1
    $end   = $sec.end - 1   # 0-based 半开区间 [start, end)

    for ($i = $start; $i -lt $end; $i++) {
        if ($i -lt 0 -or $i -ge $lines.Count) { continue }
        [void]$sb.AppendLine($lines[$i])
    }

    if ($idx -lt $arr.Count - 1) {
        [void]$sb.AppendLine("---")
        [void]$sb.AppendLine("")
    }
}

$newContent = $sb.ToString()
# 把 StringBuilder 内容（CRLF）转成 LF 字节
$srcBytes = [System.Text.Encoding]::UTF8.GetBytes($newContent)
$dstList = New-Object System.Collections.Generic.List[byte]
$dstList.Capacity = $srcBytes.Count
for ($i = 0; $i -lt $srcBytes.Count; $i++) {
    # 跳过 \r，只保留 \n
    if ($srcBytes[$i] -eq 13) {
        if ($i+1 -lt $srcBytes.Count -and $srcBytes[$i+1] -eq 10) {
            continue
        }
        $dstList.Add($srcBytes[$i])
    } else {
        $dstList.Add($srcBytes[$i])
    }
}
$cleanBytes = $dstList.ToArray()
[System.IO.File]::WriteAllBytes($path, $cleanBytes)
$newLineCount = ([System.IO.File]::ReadAllLines($path)).Count
$newCharCount = $newContent.Length
Write-Host "[3/4] new file: $newLineCount lines / $newCharCount chars"
Write-Host "    delta: lines = $($origLineCount - $newLineCount), chars = $($origCharCount - $newCharCount)"

# ── 验证 ──
$newLines = [System.IO.File]::ReadAllLines($path)

# 提取 H1（仅真 1 级：以单个 # + 空格 开头）
$origH1 = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line.StartsWith("# ")) {
        $origH1 += $line.Trim()
    }
}
$newH1 = @()
for ($i = 0; $i -lt $newLines.Count; $i++) {
    $line = $newLines[$i]
    if ($line.StartsWith("# ")) {
        $newH1 += $line.Trim()
    }
}

# 但这会包含 "## " 和 "### "，因为这些也是 "# " 开头
# 真正的 H1 应该是 "#" 后面紧跟空格（不是 #）
# 用正则更精确
$realOrigH1 = $origH1 | Where-Object { $_ -match '^# [^#]' }
$realNewH1  = $newH1  | Where-Object { $_ -match '^# [^#]' }

Write-Host "[4/4] H1 validation:"
Write-Host "    orig H1 (true): $($realOrigH1.Count)"
Write-Host "    new  H1 (true): $($realNewH1.Count)"

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

Write-Host ""
Write-Host "=== 备份保留 ==="
Write-Host "  $bak"
