' ============================================================
' Aerie / Yunqi - silent dev launcher (no cmd window)
' Double-click to start. End via Task Manager (electron.exe).
' ============================================================

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strRoot = strScriptDir
strElectronDir = strRoot & "\electron"
strElectronBin = strElectronDir & "\node_modules\.bin\electron.cmd"

' Check electron dependency
If Not objFSO.FileExists(strElectronBin) Then
    MsgBox "electron dependency missing." & vbCrLf & vbCrLf & _
           "Please run once in cmd:" & vbCrLf & _
           "  cd /d """ & strElectronDir & """" & vbCrLf & _
           "  npm install", _
           vbCritical, "Aerie / Yunqi"
    WScript.Quit 1
End If

' Switch to electron dir and run npm start, hidden
objShell.CurrentDirectory = strElectronDir
objShell.Run "cmd.exe /c npm start", 0, False

Set objShell = Nothing
Set objFSO = Nothing
