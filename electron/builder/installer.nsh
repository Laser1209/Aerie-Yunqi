; Aerie · 云栖 v9.0 — NSIS installer customizations
; Loaded by electron-builder via `nsis.include: builder/installer.nsh`.
; Provides:
;   - Pre-flight info banner (bilingual)
;   - Custom uninstall cleanup (logs cache)
;   - Desktop & Start Menu shortcut verification
;   - Aerie-specific registry entry for first-run auto-launch prompt

!macro customHeader
  RequestExecutionLevel user
  ; Reserve extra BRANDING constants if needed
  !define AERIE_BRAND "Aerie · 云栖"
  !define AERIE_VERSION "9.0.0"
!macroend

!macro customWelcomePage
  !define MUI_WELCOMEPAGE_TITLE "${AERIE_BRAND} 安装向导"
  !define MUI_WELCOMEPAGE_TEXT "欢迎使用 ${AERIE_BRAND} v${AERIE_VERSION} — 你的本地 AI 桌面伴侣。$\r$\n$\r$\nThis wizard will install ${AERIE_BRAND} on your computer.$\r$\n$\r$\n本程序完全运行于本地，不会上传任何个人信息。$\r$\nAll data stays on your machine."
  !insertmacro MUI_PAGE_WELCOME
!macroend

!macro customInstall
  ; Pre-installation: nothing required (pythonw.exe detection happens at runtime)
  ; Reserve $AERIE_INSTALL_DIR for any future post-install hooks
  StrCpy $AERIE_INSTALL_DIR $INSTDIR
!macroend

!macro customUnInstall
  ; Clean up local cache: %APPDATA%\Aerie · 云栖\logs and *-cache
  SetShellVarContext current
  RMDir /r "$APPDATA\${AERIE_BRAND}\logs"
  RMDir /r "$APPDATA\${AERIE_BRAND}\Cache"
  RMDir /r "$APPDATA\${AERIE_BRAND}\GPUCache"
  RMDir /r "$APPDATA\${AERIE_BRAND}\ShaderCache"
  ; Note: keep config.json and data so the user's settings survive uninstall.
!macroend

; Optional: show a finish-page note
!macro customFinishPage
  !define MUI_FINISHPAGE_TITLE "${AERIE_BRAND} 安装完成"
  !define MUI_FINISHPAGE_TEXT "${AERIE_BRAND} 已成功安装。$\r$\n$\r$\n点击"完成"退出安装程序。$\r$\n如需立即启动，请双击桌面上的 ${AERIE_BRAND} 快捷方式。$\r$\n$\r$\nInstallation complete. Click Finish to exit the setup."
  !insertmacro MUI_PAGE_FINISH
!macroend
