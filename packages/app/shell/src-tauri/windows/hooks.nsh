; The Harness: installer hooks (Tauri NSIS installerHooks).
; After installing: the session host starts at login, on by default as Ollama's installer
; does; the shell applies this default once, so an update keeps what the user chose. On an
; interactive install the finish page (ui.nsh) then applies the user's choice ("Keep working
; after the computer starts": --autostart on, or off when unchecked).
; The harness command for terminals: the folder of runtime\bin\harness.exe goes on the user's
; PATH, as Ollama's and VS Code's installers add theirs (HKCU\Environment, appended unless it
; is there, the change broadcast to running programs), on every install and update; the
; shell's --path does it with the bundled Python, since a PATH is longer than an NSIS string.
; Its report says which harness a new terminal runs when that is another install's, for the
; finish page (ui.nsh).
; Before installing over or removing an older copy: stop the host so its runtime files can
; be replaced; when removing (not updating): the login item and the PATH entry go too.
; The shell is ${MAINBINARYNAME}.exe (the-harness, or the-harness-dev of a dev build), in this
; build's own folder: each channel's installer acts on its own shell, host, login item and PATH entry.

!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 +2
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --stop-host'
!macroend

!macro NSIS_HOOK_POSTINSTALL
  nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart default'
  Pop $0
  InitPluginsDir
  nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --path on --report "$PLUGINSDIR\h-command.txt"'
  Pop $0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --stop-host'
  ; An update runs the old uninstaller too (/UPDATE): the login item stays then.
  ${If} $UpdateMode <> 1
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart off'
    Pop $0
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --path off'
    Pop $0
  ${EndIf}
!macroend
