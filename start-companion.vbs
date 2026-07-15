' OpenCloud Companion 静默自启动脚本
' 放到 Windows 启动文件夹:
' Win+R → shell:startup → 放入此文件
' 
' 作用：开机后无窗口启动 NapCat + AI Companion

Set WshShell = CreateObject("WScript.Shell")

' 获取本脚本所在目录
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 启动批处理（隐藏窗口）
WshShell.Run """" & scriptDir & "\start-companion.bat""", 0, False

Set WshShell = Nothing
Set fso = Nothing
