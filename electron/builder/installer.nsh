; Aerie · 云栖 v0.1.0-beta.1 — NSIS installer customizations
; Loaded by electron-builder via `nsis.include: builder/installer.nsh`.

!macro customHeader
  RequestExecutionLevel user
!macroend

!macro customUnInstall
  SetShellVarContext current
  RMDir /r "$APPDATA\Aerie 云栖\logs"
  RMDir /r "$APPDATA\Aerie 云栖\Cache"
  RMDir /r "$APPDATA\Aerie 云栖\GPUCache"
  RMDir /r "$APPDATA\Aerie 云栖\ShaderCache"
!macroend
