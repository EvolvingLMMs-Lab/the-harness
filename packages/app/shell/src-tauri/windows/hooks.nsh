; The Harness: installer hooks (Tauri NSIS installerHooks).
; After installing: the session host starts at login, on by default as Ollama's installer
; does; the shell applies this default once, so an update keeps what the user chose.
; Before installing over or removing an older copy: stop the host so its runtime files can
; be replaced; when removing (not updating): the login item goes too.

!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$INSTDIR\the-harness.exe" 0 +2
    nsExec::Exec '"$INSTDIR\the-harness.exe" --stop-host'
!macroend

!macro NSIS_HOOK_POSTINSTALL
  nsExec::Exec '"$INSTDIR\the-harness.exe" --autostart default'
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$INSTDIR\the-harness.exe" --stop-host'
  ; An update runs the old uninstaller too (/UPDATE): the login item stays then.
  ${If} $UpdateMode <> 1
    nsExec::Exec '"$INSTDIR\the-harness.exe" --autostart off'
  ${EndIf}
!macroend
