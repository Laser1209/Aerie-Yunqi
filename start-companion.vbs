' OpenCloud Companion - Silent Auto-Start Script
' ============================================
' Purpose:  Boot-time silent launcher.
'           Place in Windows startup folder:
'           Win+R -> shell:startup -> drop this .vbs here
'
' Behavior: Hides the bat window (0 = hidden).
'           Does NOT wait for bat to finish (False).
'           Writes a timestamped launcher.log so the owner
'           can verify whether the boot sequence actually ran.
' ============================================

Option Explicit

Const WshFinishedOK = 0
Const FOR_APPENDING  = 8

Dim WshShell, fso, scriptDir, batPath, logPath, ts

Set WshShell = CreateObject("WScript.Shell")
Set fso      = CreateObject("Scripting.FileSystemObject")

' 1. Resolve paths (vbs lives in the workspace root)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath   = scriptDir & "\start-companion.bat"
logPath   = scriptDir & "\launcher.log"

' 2. Verify bat exists before launching
If Not fso.FileExists(batPath) Then
    ' Can't even start -- write a clear error to a side log
    Dim errLog : errLog = scriptDir & "\launcher-ERROR.log"
    Dim errFs  : Set errFs = fso.OpenTextFile(errLog, FOR_APPENDING, True)
    errFs.WriteLine Now & " [FATAL] start-companion.bat NOT FOUND at: " & batPath
    errFs.Close
    WScript.Quit 1
End If

' 3. Append a "starting" marker to launcher.log
Dim logFs : Set logFs = fso.OpenTextFile(logPath, FOR_APPENDING, True)
ts = Now
logFs.WriteLine ts & " [INFO]  Booting OpenCloud Companion via: " & batPath
logFs.Close

' 4. Run the bat HIDDEN, do NOT block on it.
'    WindowStyle=0 (hidden), WaitOnReturn=False (fire-and-forget).
WshShell.Run """" & batPath & """", 0, False

' 5. Append a "kickoff done" marker
Set logFs = fso.OpenTextFile(logPath, FOR_APPENDING, True)
logFs.WriteLine Now & " [INFO]  Kicked off (bat running in background)."
logFs.Close

Set WshShell = Nothing
Set fso      = Nothing

WScript.Quit WshFinishedOK
