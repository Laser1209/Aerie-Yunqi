' ============================================================
' Aerie / Yunqi - silent dev launcher (no console window)
' It delegates all checks to start-dev.bat and writes a log file.
' ============================================================

Option Explicit

Dim objShell, objFSO
Dim strScriptDir, strLauncher, strLogsDir, strLogFile, strCommand, q

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strLauncher = strScriptDir & "\start-dev.bat"
strLogsDir = strScriptDir & "\logs"
strLogFile = strLogsDir & "\start-dev.log"
q = Chr(34)

If Not objFSO.FileExists(strLauncher) Then
    MsgBox "start-dev.bat not found." & vbCrLf & vbCrLf & _
           "Missing: " & strLauncher, _
           vbCritical, "Aerie / Yunqi"
    WScript.Quit 1
End If

If Not objFSO.FolderExists(strLogsDir) Then
    objFSO.CreateFolder(strLogsDir)
End If

objShell.CurrentDirectory = strScriptDir
objShell.Environment("PROCESS")("AERIE_SILENT") = "1"
strCommand = "cmd.exe /c " & q & q & strLauncher & q & " > " & q & strLogFile & q & " 2>&1" & q
objShell.Run strCommand, 0, False

Set objShell = Nothing
Set objFSO = Nothing
