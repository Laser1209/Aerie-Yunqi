const { spawn } = require("child_process");

const _SMTC_PS1 = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.IsStatic }
foreach ($m in $methods) { Write-Host $m.Name " - " $m.ToString() }
Write-Host "==="
Write-Host "AsStream-like methods:"
$methods2 = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -match 'Stream' }
foreach ($m in $methods2) { Write-Host $m.Name " - " $m.ToString() }
`;

const ps = spawn("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _SMTC_PS1]);

let stdout = "";
ps.stdout.on("data", (d) => (stdout += d.toString()));
ps.on("close", () => {
  console.log(stdout);
});