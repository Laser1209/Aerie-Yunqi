' ============================================================
' Aerie / Yunqi - silent dev launcher (no console window)
' It delegates all checks to start-dev.bat and writes a log file.
' ============================================================

Option Explicit

Dim objShell, objFSO
Dim strScriptDir, strLauncher, strLogsDir, strLogFile, strCommand, strStamp, q, objLog

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strLauncher = strScriptDir & "\start-dev.bat"
strLogsDir = strScriptDir & "\logs"
strStamp = Year(Now) & Right("0" & Month(Now), 2) & Right("0" & Day(Now), 2) & "-" & Right("0" & Hour(Now), 2) & Right("0" & Minute(Now), 2) & Right("0" & Second(Now), 2)
strLogFile = strLogsDir & "\start-dev-" & strStamp & ".log"
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

On Error Resume Next
Set objLog = objFSO.OpenTextFile(strLogFile, 8, True)
If Err.Number = 0 Then
    objLog.WriteLine ""
    objLog.WriteLine "============================================================"
    objLog.WriteLine "Silent launcher started: " & Now
    objLog.WriteLine "ScriptDir: " & strScriptDir
    objLog.WriteLine "Launcher: " & strLauncher
    objLog.Close
End If
Err.Clear
On Error GoTo 0

objShell.CurrentDirectory = strScriptDir
objShell.Environment("PROCESS")("AERIE_SILENT") = "1"
strCommand = "cmd.exe /d /s /c " & q & "set AERIE_SILENT=1 && call " & q & strLauncher & q & " >> " & q & strLogFile & q & " 2>&1" & q
objShell.Run strCommand, 0, False

Set objShell = Nothing
Set objFSO = Nothing
