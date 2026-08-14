; Aerie · 云栖 v9.0 — NSIS installer customizations
; Loaded by electron-builder via `nsis.include: builder/installer.nsh`.
; Provides:
;   - Pre-flight info banner (bilingual)
;   - Custom uninstall cleanup (logs cache)
;   - Desktop & Start Menu shortcut verification
;   - Aerie-specific registry entry for first-run auto-launch prompt

; Branding constants must be global (top-level), not inside a macro.
; `!define` inside a !macro is macro-scoped and invisible to sibling macros,
; which produced "warning 6000: unknown variable {AERIE_BRAND}".
!define AERIE_BRAND "Aerie · 云栖"

!macro customHeader
  RequestExecutionLevel user
!macroend

!macro customWelcomePage
  !define MUI_WELCOMEPAGE_TITLE "${AERIE_BRAND} 安装向导"
  !define MUI_WELCOMEPAGE_TEXT "欢迎使用 ${AERIE_BRAND} v${VERSION} — 你的本地 AI 桌面伴侣。$\r$\n$\r$\nThis wizard will install ${AERIE_BRAND} on your computer.$\r$\n$\r$\n本程序完全运行于本地，不会上传任何个人信息。$\r$\nAll data stays on your machine."
  !insertmacro MUI_PAGE_WELCOME
!macroend

!macro customInstall
  ; Pre-installation: nothing required (pythonw.exe detection happens at runtime)
!macroend

!macro customUnInstall
  ; Clean up local cache: %APPDATA%\<PRODUCT_NAME>\logs and *-cache
  SetShellVarContext current
  RMDir /r "$APPDATA\${PRODUCT_NAME}\logs"
  RMDir /r "$APPDATA\${PRODUCT_NAME}\Cache"
  RMDir /r "$APPDATA\${PRODUCT_NAME}\GPUCache"
  RMDir /r "$APPDATA\${PRODUCT_NAME}\ShaderCache"
  ; Note: keep config.json and data so the user's settings survive uninstall.
!macroend

; Optional: show a finish-page note
!macro customFinishPage
  !define MUI_FINISHPAGE_TITLE "${AERIE_BRAND} 安装完成"
  !define MUI_FINISHPAGE_TEXT "${AERIE_BRAND} 已成功安装。$\r$\n$\r$\n点击「完成」退出安装程序。$\r$\n如需立即启动，请双击桌面上的 ${AERIE_BRAND} 快捷方式。$\r$\n$\r$\nInstallation complete. Click Finish to exit the setup."
  !insertmacro MUI_PAGE_FINISH
!macroend
