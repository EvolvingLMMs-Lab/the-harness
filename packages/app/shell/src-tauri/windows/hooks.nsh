; The Harness: installer hooks (Tauri NSIS installerHooks).
; After installing: the session host starts at login, on by default as Ollama's installer
; does; the shell applies this default once, so an update keeps what the user chose. On an
; interactive install the finish page (ui.nsh) then applies the user's choice ("Keep working
; after the computer starts": --autostart on, or off when unchecked).
; Before installing over or removing an older copy: stop the host so its runtime files can
; be replaced; when removing (not updating): the login item goes too.
; The shell is ${MAINBINARYNAME}.exe (the-harness, or the-harness-dev of a dev build), in this
; build's own folder: each channel's installer acts on its own shell, host and login item.

!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 +2
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --stop-host'
!macroend

!macro NSIS_HOOK_POSTINSTALL
  nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart default'
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --stop-host'
  ; An update runs the old uninstaller too (/UPDATE): the login item stays then.
  ${If} $UpdateMode <> 1
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart off'
  ${EndIf}
!macroend
