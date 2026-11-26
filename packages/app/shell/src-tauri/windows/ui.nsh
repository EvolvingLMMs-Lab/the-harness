; The Harness: the installer's pages in the archive design (navy tokens, Space Grotesk, Inter,
; JetBrains Mono), after the "Installing" prototype of the design page. A step rail (Welcome,
; Location, Install, Finish) stays on the left of the window; each page draws its body on the
; right with its own buttons. The install page shows a progress bar for each part (the bundled
; Python runtime, The Harness, the shell) and the note about the unsigned build; the finish
; page has the login item choice and "Open The Harness".
;
; installer.nsi (Tauri's template) includes this file after its own variables; strings.nsh
; holds the English and Chinese texts. Sizes are pixels at 96 dpi, scaled by the window's dpi.

!include nsDialogs.nsh
!include LogicLib.nsh
!include WinMessages.nsh

!define H_DIR "${__FILEDIR__}"
!define H_FONTS "${H_DIR}\..\..\..\ui\static\archive\fonts"

; The archive tokens (navy), as RRGGBB for SetCtlColors and as COLORREF (0x00BBGGRR).
!define H_BG 09121D
!define H_SURFACE 112332
!define H_RAISE 17304A
!define H_LINE 547383
!define H_FG EAF4F6
!define H_MUTED C3D2D9
!define H_DIM 8EA3B0
!define H_ACCENT 69E5F3
!define H_DONE 3DDC97
!define H_BG_REF 0x001D1209
!define H_SURFACE_REF 0x00322311
!define H_RAISE_REF 0x004A3017
!define H_LINE_REF 0x00837354
!define H_FG_REF 0x00F6F4EA
!define H_MUTED_REF 0x00D9D2C3
!define H_ACCENT_REF 0x00F3E569

; Window styles: child, visible, clip siblings (+ notify, centred, bitmap, edit).
!define H_ST_TEXT 0x54000100
!define H_ST_LINE 0x54000300
!define H_ST_BUTTON 0x54000301
!define H_ST_BITMAP 0x5400020E
!define H_ST_EDIT 0x54010080

; The window's client area, the rail's rows, the body's padding.
!define H_W 700
!define H_H 470
!define H_PADX 28
!define H_PADY 24

Var HDpi
Var HX
Var HY
Var HW
Var HH
Var HT1
Var HT2
Var HT3
Var HT9
Var HDlg
Var HCtl
Var HFontTitle
Var HFontBody
Var HFontSmall
Var HFontMono
Var HFontButton
Var HFontCheck
Var HCW
Var HCH
Var HBX
Var HBY
Var HBW
Var HBH
Var HRailW
Var HRailBg
Var HRailMark
Var HRail1
Var HRail2
Var HRail3
Var HRail4
Var HStep
Var HInst1
Var HInst2
Var HInst3
Var HInst4
Var HInst5
Var HInst6
Var HBar1F
Var HBar1R
Var HBar2F
Var HBar2R
Var HBar3F
Var HBar3R
Var HBarX
Var HBarW
Var HBarH
Var HBar1Y
Var HBar2Y
Var HBar3Y
Var HDone1
Var HDone2
Var HFill1
Var HFill2
Var HFill3
Var HDirEdit
Var HOpt1M
Var HOpt1P
Var HOpt1T
Var HOpt2M
Var HOpt2P
Var HOpt2T
Var HOpt2Off
Var HCheckBox
Var HResult
Var HAutostart
Var HOpen
Var HAtFinish
Var HApplied

; -- the parts and their file counts (counted from the resource list at compile time) --------

; H_KIND_V: 2 for The Harness (its Python package, entry points and package folders),
; 1 for the rest of the bundled Python runtime.
!macro H_KIND DEST
  !ifdef H_KIND_V
    !undef H_KIND_V
  !endif
  !define H_KIND_V 1
  !insertmacro H_KIND_IF "${DEST}" "\site-packages\harness\"
  !insertmacro H_KIND_IF "${DEST}" "\site-packages\the_harness-"
  !insertmacro H_KIND_IF "${DEST}" "\Scripts\harness"
  !insertmacro H_KIND_IF "${DEST}" "runtime\packages\"
!macroend
!macro H_KIND_IF DEST PART
  !ifdef H_KIND_HIT
    !undef H_KIND_HIT
  !endif
  !searchparse /noerrors "${DEST}" "${PART}" H_KIND_HIT
  !ifdef H_KIND_HIT
    !undef H_KIND_V
    !define H_KIND_V 2
    !undef H_KIND_HIT
  !endif
!macroend

!define H_N1 0
!define H_N2 0
!macro H_COUNT DEST
  !insertmacro H_KIND "${DEST}"
  !if ${H_KIND_V} == 2
    !define /redef /math H_N2 ${H_N2} + 1
  !else
    !define /redef /math H_N1 ${H_N1} + 1
  !endif
  ; the runtime's Python version, from its DLL (runtime\python\python3XY.dll)
  !ifndef H_PYVER
    !ifdef H_PYMINOR
      !undef H_PYMINOR
    !endif
    !searchparse /noerrors "${DEST}" "runtime\python\python3" H_PYMINOR ".dll"
    !ifdef H_PYMINOR
      !if "${H_PYMINOR}" != ""
        !define H_PYVER "3.${H_PYMINOR}"
      !endif
    !endif
  !endif
!macroend
!macro H_COUNTED
  !ifndef H_PYVER
    !define H_PYVER "3"
  !endif
  !if ${H_N1} == 0
    !define /redef H_N1 1
  !endif
  !if ${H_N2} == 0
    !define /redef H_N2 1
  !endif
  !define /math H_MB ${ESTIMATEDSIZE} / 1024
!macroend

; One resource file of part KIND, moving that part's bar.
!macro H_FILE KIND SRC DEST
  !insertmacro H_KIND "${DEST}"
  !if ${H_KIND_V} == ${KIND}
    File /a "/oname=${DEST}" "${SRC}"
    Call HTick${KIND}
  !endif
!macroend

; The shell's bar at PERCENT.
!macro H_SHELL PERCENT
  StrCpy $HT9 ${PERCENT}
  Call HTick3
!macroend

; -- drawing helpers ----------------------------------------------------------------------

!macro H_PX OUT DIP
  IntOp ${OUT} ${DIP} * $HDpi
  IntOp ${OUT} ${OUT} / 96
!macroend

!macro H_FONT OUT FACE SIZE WEIGHT
  IntOp $0 ${SIZE} * $HDpi
  IntOp $0 $0 / 96
  IntOp $0 0 - $0
  System::Call 'gdi32::CreateFontW(i r0, i 0, i 0, i 0, i ${WEIGHT}, i 0, i 0, i 0, i 1, i 0, i 0, i 5, i 0, w "${FACE}") p .s'
  Pop ${OUT}
!macroend

; A static on the current nsDialogs page.
!macro H_TEXT OUT X Y W H TEXT FONT FG BG STYLE
  !insertmacro H_PX $HX ${X}
  !insertmacro H_PX $HY ${Y}
  !insertmacro H_PX $HW ${W}
  !insertmacro H_PX $HH ${H}
  nsDialogs::CreateControl STATIC ${STYLE} 0 $HX $HY $HW $HH `${TEXT}`
  Pop ${OUT}
  SendMessage ${OUT} ${WM_SETFONT} ${FONT} 0
  SetCtlColors ${OUT} ${FG} ${BG}
!macroend

; A button on the current nsDialogs page: a flat label that reacts to a click, filled with
; the foreground colour (primary) or the raised surface (secondary), as in the prototype.
!macro H_BUTTON OUT X Y W H TEXT PRIMARY CALLBACK
  !if ${PRIMARY} == 1
    !insertmacro H_TEXT ${OUT} ${X} ${Y} ${W} ${H} `${TEXT}` $HFontButton ${H_BG} ${H_FG} ${H_ST_BUTTON}
  !else
    !insertmacro H_TEXT ${OUT} ${X} ${Y} ${W} ${H} `${TEXT}` $HFontButton ${H_FG} ${H_RAISE} ${H_ST_BUTTON}
  !endif
  ${NSD_OnClick} ${OUT} ${CALLBACK}
!macroend

; A static on the window itself (the rail, the install page); X/Y/W/H in pixels already.
!macro H_WIN OUT STYLE X Y W H
  System::Call 'user32::CreateWindowExW(i 0, w "STATIC", w "", i ${STYLE}, i ${X}, i ${Y}, i ${W}, i ${H}, p $HWNDPARENT, p 0, p 0, p 0) p .s'
  Pop ${OUT}
!macroend

; A text on the window at the body's place; X/Y/W/H at 96 dpi relative to the body.
!macro H_BODYTEXT OUT X Y W H TEXT FONT FG BG STYLE
  !insertmacro H_PX $HX ${X}
  IntOp $HX $HX + $HBX
  !insertmacro H_PX $HY ${Y}
  IntOp $HY $HY + $HBY
  !insertmacro H_PX $HW ${W}
  !insertmacro H_PX $HH ${H}
  !insertmacro H_WIN ${OUT} ${STYLE} $HX $HY $HW $HH
  SendMessage ${OUT} ${WM_SETTEXT} 0 `STR:${TEXT}`
  SendMessage ${OUT} ${WM_SETFONT} ${FONT} 0
  SetCtlColors ${OUT} ${FG} ${BG}
!macroend

!macro H_TOP CTL
  System::Call 'user32::SetWindowPos(p ${CTL}, p 0, i 0, i 0, i 0, i 0, i 0x13)'
!macroend

!macro H_REPAINT CTL
  System::Call 'user32::InvalidateRect(p ${CTL}, p 0, i 1)'
!macroend

; The page's title and lead text.
!macro H_HEAD TITLE TEXT
  !insertmacro H_TEXT $HCtl 0 0 $HBW 32 `${TITLE}` $HFontTitle ${H_FG} ${H_BG} ${H_ST_LINE}
  !insertmacro H_TEXT $HCtl 0 44 $HBW 68 `${TEXT}` $HFontBody ${H_MUTED} ${H_BG} ${H_ST_TEXT}
!macroend

; The page's bottom row: a secondary button (if any) and the primary one at the right.
!macro H_BUTTONS SECONDARY SECONDARYCALL PRIMARY PRIMARYCALL
  IntOp $HT1 $HBH - 34
  IntOp $HT2 $HBW - 160
  IntOp $HT3 $HT2 - 112
  !if "${SECONDARY}" != ""
    !insertmacro H_BUTTON $HCtl $HT3 $HT1 100 34 `${SECONDARY}` 0 ${SECONDARYCALL}
  !endif
  !insertmacro H_BUTTON $HCtl $HT2 $HT1 160 34 `${PRIMARY}` 1 ${PRIMARYCALL}
!macroend

!macro H_PAGE STEP
  StrCpy $HStep ${STEP}
  Call HRail
  nsDialogs::Create 1018
  Pop $HDlg
  ${If} $HDlg == error
    Abort
  ${EndIf}
  SetCtlColors $HDlg "" ${H_BG}
!macroend

!macro H_AWAY ID
  GetDlgItem $0 $HWNDPARENT ${ID}
  System::Call 'user32::SetWindowPos(p r0, p 0, i -4000, i -4000, i 0, i 0, i 0x15)'
!macroend

; A rail step at Y (96 dpi); $2 is its x and $3 its width in pixels, $4 its height.
!macro H_RAILSTEP OUT Y TEXT
  !insertmacro H_PX $HY ${Y}
  !insertmacro H_WIN ${OUT} ${H_ST_LINE} $2 $HY $3 $4
  SendMessage ${OUT} ${WM_SETTEXT} 0 `STR:${TEXT}`
  SendMessage ${OUT} ${WM_SETFONT} $HFontBody 0
  SetCtlColors ${OUT} ${H_DIM} ${H_SURFACE}
  !insertmacro H_TOP ${OUT}
!macroend

!macro H_RAILITEM CTL N
  ${If} $HStep > ${N}
    SetCtlColors ${CTL} ${H_DONE} ${H_SURFACE}
  ${ElseIf} $HStep = ${N}
    SetCtlColors ${CTL} ${H_FG} ${H_RAISE}
  ${Else}
    SetCtlColors ${CTL} ${H_DIM} ${H_SURFACE}
  ${EndIf}
!macroend

; A bar's fill: $0 its width in pixels, then the fill and rest controls and y.
!macro H_SETBAR FILL REST Y
  System::Call 'user32::SetWindowPos(p ${FILL}, p 0, i 0, i 0, i r0, i $HBarH, i 0x16)'
  IntOp $1 $HBarX + $0
  IntOp $2 $HBarW - $0
  System::Call 'user32::SetWindowPos(p ${REST}, p 0, i r1, i ${Y}, i r2, i $HBarH, i 0x14)'
!macroend

; An option row: 1 chosen, 0 not chosen, 2 not available.
!macro H_OPTION MARK PAD TEXT STATE
  !if ${STATE} == 1
    SetCtlColors ${MARK} ${H_FG} ${H_ACCENT}
    SetCtlColors ${PAD} ${H_FG} ${H_RAISE}
    SetCtlColors ${TEXT} ${H_FG} ${H_RAISE}
  !else if ${STATE} == 0
    SetCtlColors ${MARK} ${H_FG} ${H_SURFACE}
    SetCtlColors ${PAD} ${H_FG} ${H_SURFACE}
    SetCtlColors ${TEXT} ${H_MUTED} ${H_SURFACE}
  !else
    SetCtlColors ${MARK} ${H_FG} ${H_BG}
    SetCtlColors ${PAD} ${H_FG} ${H_BG}
    SetCtlColors ${TEXT} ${H_DIM} ${H_BG}
  !endif
  !insertmacro H_REPAINT ${MARK}
  !insertmacro H_REPAINT ${PAD}
  !insertmacro H_REPAINT ${TEXT}
!macroend

; The three parts as rows on nsDialogs pages: the name, with a full bar (BAR 1) or a mark.
!macro H_PARTROW Y TEXT BAR
  !if ${BAR} == 1
    IntOp $HT1 $HBW - 216
    !insertmacro H_TEXT $HCtl 0 ${Y} $HT1 30 `${TEXT}` $HFontBody ${H_MUTED} ${H_BG} ${H_ST_LINE}
    IntOp $HT1 $HBW - 200
    !define /redef /math H_ROWY ${Y} + 11
    !insertmacro H_TEXT $HCtl $HT1 ${H_ROWY} 200 8 "" $HFontBody ${H_FG} ${H_ACCENT} ${H_ST_LINE}
  !else
    !define /redef /math H_ROWY ${Y} + 12
    !insertmacro H_TEXT $HCtl 0 ${H_ROWY} 6 6 "" $HFontBody ${H_FG} ${H_ACCENT} ${H_ST_LINE}
    IntOp $HT1 $HBW - 18
    !insertmacro H_TEXT $HCtl 18 ${Y} $HT1 30 `${TEXT}` $HFontBody ${H_MUTED} ${H_BG} ${H_ST_LINE}
  !endif
!macroend

; -- the window: size, colours, fonts, the rail ------------------------------------------

Function HGuiInit
  StrCpy $HAutostart 1
  StrCpy $HOpen 1
  System::Call 'user32::GetDpiForWindow(p $HWNDPARENT) i .r0'
  ${If} $0 < 96
    StrCpy $0 96
  ${EndIf}
  StrCpy $HDpi $0

  ; The archive fonts, for this process only.
  InitPluginsDir
  File "/oname=$PLUGINSDIR\h-inter-400.ttf" "${H_FONTS}\inter-400.ttf"
  File "/oname=$PLUGINSDIR\h-inter-600.ttf" "${H_FONTS}\inter-600.ttf"
  File "/oname=$PLUGINSDIR\h-space-grotesk-500.ttf" "${H_FONTS}\space-grotesk-500.ttf"
  File "/oname=$PLUGINSDIR\h-jetbrains-mono-400.ttf" "${H_FONTS}\jetbrains-mono-400.ttf"
  System::Call 'gdi32::AddFontResourceExW(w "$PLUGINSDIR\h-inter-400.ttf", i 0x10, p 0)'
  System::Call 'gdi32::AddFontResourceExW(w "$PLUGINSDIR\h-inter-600.ttf", i 0x10, p 0)'
  System::Call 'gdi32::AddFontResourceExW(w "$PLUGINSDIR\h-space-grotesk-500.ttf", i 0x10, p 0)'
  System::Call 'gdi32::AddFontResourceExW(w "$PLUGINSDIR\h-jetbrains-mono-400.ttf", i 0x10, p 0)'
  !insertmacro H_FONT $HFontTitle "$(H_FaceTitle)" 21 400
  !insertmacro H_FONT $HFontBody "$(H_FaceBody)" 14 400
  !insertmacro H_FONT $HFontSmall "$(H_FaceBody)" 12 400
  !insertmacro H_FONT $HFontMono "$(H_FaceMono)" 13 400
  !insertmacro H_FONT $HFontButton "$(H_FaceButton)" 13 $(H_WeightButton)
  !insertmacro H_FONT $HFontCheck "Inter" 14 400

  ; The client area at 700 x 470, around the same centre.
  !insertmacro H_PX $HCW ${H_W}
  !insertmacro H_PX $HCH ${H_H}
  System::Call '*(i, i, i, i) p .r3'
  System::Call 'user32::GetWindowRect(p $HWNDPARENT, p r3)'
  System::Call '*$3(i .r4, i .r5, i .r6, i .r7)'
  System::Call 'user32::GetClientRect(p $HWNDPARENT, p r3)'
  System::Call '*$3(i, i, i .r8, i .r9)'
  System::Free $3
  IntOp $6 $6 - $4
  IntOp $7 $7 - $5
  IntOp $8 $6 - $8
  IntOp $9 $7 - $9
  IntOp $8 $8 + $HCW
  IntOp $9 $9 + $HCH
  IntOp $0 $6 - $8
  IntOp $0 $0 / 2
  IntOp $4 $4 + $0
  IntOp $0 $7 - $9
  IntOp $0 $0 / 2
  IntOp $5 $5 + $0
  ${If} $5 < 0
    StrCpy $5 0
  ${EndIf}
  ${If} $4 < 0
    StrCpy $4 0
  ${EndIf}
  System::Call 'user32::SetWindowPos(p $HWNDPARENT, p 0, i r4, i r5, i r8, i r9, i 0x14)'

  ; A dark title bar in the rail's colour (Windows 10 2004+ / 11; ignored elsewhere).
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 20, *i 1, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 35, *i ${H_SURFACE_REF}, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 36, *i ${H_FG_REF}, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 34, *i ${H_LINE_REF}, i 4)'

  ; MUI's header, lines and branding, and the stock buttons, out of sight: each page draws
  ; its own. The buttons stay enabled, so Enter and Esc still work.
  SetCtlColors $HWNDPARENT "" ${H_BG}
  !insertmacro H_AWAY 1
  !insertmacro H_AWAY 2
  !insertmacro H_AWAY 3
  !insertmacro H_AWAY 1028
  !insertmacro H_AWAY 1256
  !insertmacro H_AWAY 1034
  !insertmacro H_AWAY 1035
  !insertmacro H_AWAY 1036
  !insertmacro H_AWAY 1037
  !insertmacro H_AWAY 1038
  !insertmacro H_AWAY 1039
  !insertmacro H_AWAY 1045
  !insertmacro H_AWAY 1046

  ; The rail: its background with the tile and wordmark at the bottom (the sidebar image,
  ; drawn for this dpi), a raised mark on the current step, and the four steps.
  ${If} $HDpi >= 192
    File "/oname=$PLUGINSDIR\h-rail.bmp" "${H_DIR}\sidebar-200.bmp"
  ${ElseIf} $HDpi >= 168
    File "/oname=$PLUGINSDIR\h-rail.bmp" "${H_DIR}\sidebar-175.bmp"
  ${ElseIf} $HDpi >= 144
    File "/oname=$PLUGINSDIR\h-rail.bmp" "${H_DIR}\sidebar-150.bmp"
  ${ElseIf} $HDpi >= 120
    File "/oname=$PLUGINSDIR\h-rail.bmp" "${H_DIR}\sidebar-125.bmp"
  ${Else}
    File "/oname=$PLUGINSDIR\h-rail.bmp" "${SIDEBARIMAGE}"
  ${EndIf}
  System::Call 'user32::LoadImageW(p 0, w "$PLUGINSDIR\h-rail.bmp", i 0, i 0, i 0, i 0x10) p .r1'
  System::Call '*(i, i, i, i, i, i, p) p .r3'
  System::Call 'gdi32::GetObjectW(p r1, i 24, p r3)'
  System::Call '*$3(i, i .r4, i .r5)'
  System::Free $3
  StrCpy $HRailW $4
  IntOp $6 $HCH - $5
  !insertmacro H_PX $7 1
  IntOp $8 $HRailW - $7
  !insertmacro H_WIN $HRailBg ${H_ST_LINE} 0 0 $8 $6
  SetCtlColors $HRailBg "" ${H_SURFACE}
  !insertmacro H_WIN $0 ${H_ST_LINE} $8 0 $7 $6
  SetCtlColors $0 "" ${H_LINE}
  !insertmacro H_WIN $0 ${H_ST_BITMAP} 0 $6 $HRailW $5
  SendMessage $0 0x172 0 $1

  !insertmacro H_PX $1 10
  !insertmacro H_PX $2 20
  IntOp $3 $HRailW - $1
  IntOp $3 $3 - $1
  IntOp $3 $3 - $7
  !insertmacro H_PX $4 30
  !insertmacro H_WIN $HRailMark ${H_ST_LINE} $1 0 $3 $4
  SetCtlColors $HRailMark "" ${H_RAISE}
  IntOp $3 $HRailW - $2
  IntOp $3 $3 - $2
  IntOp $3 $3 - $7
  !insertmacro H_RAILSTEP $HRail1 16 "$(H_Step1)"
  !insertmacro H_RAILSTEP $HRail2 50 "$(H_Step2)"
  !insertmacro H_RAILSTEP $HRail3 84 "$(H_Step3)"
  !insertmacro H_RAILSTEP $HRail4 118 "$(H_Step4)"

  ; The body: every page's dialog goes here, right of the rail.
  !insertmacro H_PX $5 ${H_PADX}
  !insertmacro H_PX $HBY ${H_PADY}
  IntOp $HBX $HRailW + $5
  IntOp $8 $HCW - $HBX
  IntOp $8 $8 - $5
  IntOp $9 $HCH - $HBY
  IntOp $9 $9 - $HBY
  GetDlgItem $0 $HWNDPARENT 1018
  System::Call 'user32::SetWindowPos(p r0, p 0, i $HBX, i $HBY, i r8, i r9, i 0x14)'
  GetDlgItem $0 $HWNDPARENT 1044
  System::Call 'user32::SetWindowPos(p r0, p 0, i $HBX, i $HBY, i r8, i r9, i 0x14)'
  IntOp $HBW $8 * 96
  IntOp $HBW $HBW / $HDpi
  IntOp $HBH $9 * 96
  IntOp $HBH $HBH / $HDpi
FunctionEnd



; The rail for step $HStep: done steps in the done colour, the current one raised.
Function HRail
  Push $0
  Push $1
  !insertmacro H_RAILITEM $HRail1 1
  !insertmacro H_RAILITEM $HRail2 2
  !insertmacro H_RAILITEM $HRail3 3
  !insertmacro H_RAILITEM $HRail4 4
  IntOp $0 $HStep - 1
  IntOp $0 $0 * 34
  IntOp $0 $0 + 16
  !insertmacro H_PX $0 $0
  !insertmacro H_PX $1 10
  System::Call 'user32::SetWindowPos(p $HRailMark, p 0, i r1, i r0, i 0, i 0, i 0x15)'
  !insertmacro H_REPAINT $HRailBg
  !insertmacro H_REPAINT $HRailMark
  !insertmacro H_REPAINT $HRail1
  !insertmacro H_REPAINT $HRail2
  !insertmacro H_REPAINT $HRail3
  !insertmacro H_REPAINT $HRail4
  Pop $1
  Pop $0
FunctionEnd


Function HOnNext
  Pop $0
  SendMessage $HWNDPARENT 0x408 1 0
FunctionEnd

Function HOnBack
  Pop $0
  SendMessage $HWNDPARENT 0x408 -1 0
FunctionEnd

Function HOnCancel
  Pop $0
  SendMessage $HWNDPARENT ${WM_COMMAND} 2 0
FunctionEnd


; -- 1. Welcome --------------------------------------------------------------------------

Function HWelcomeCreate
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
  !insertmacro H_PAGE 1
  !insertmacro H_HEAD "$(H_WelcomeTitle)" "$(H_WelcomeText)"
  !insertmacro H_PARTROW 128 "$(H_Part1)" 0
  !insertmacro H_PARTROW 158 "$(H_Part2)" 0
  !insertmacro H_PARTROW 188 "$(H_Part3)" 0
  !insertmacro H_TEXT $HCtl 0 238 $HBW 20 "$(H_ForYou)" $HFontSmall ${H_DIM} ${H_BG} ${H_ST_LINE}
  !insertmacro H_BUTTONS "$(H_Cancel)" HOnCancel "$(H_Next)" HOnNext
  nsDialogs::Show
FunctionEnd

; -- 2. Location (and Tauri's reinstall choice, when an older copy is there) -------------

Function HLocationCreate
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
  !insertmacro H_PAGE 2
  !insertmacro H_HEAD "$(H_LocationTitle)" "$(H_LocationText)"
  ; the folder: an edit field on a raised box, and Browse
  IntOp $HT1 $HBW - 112
  !insertmacro H_TEXT $HCtl 0 122 $HT1 36 "" $HFontBody ${H_FG} ${H_RAISE} ${H_ST_LINE}
  IntOp $HT1 $HT1 - 24
  !insertmacro H_PX $HX 12
  !insertmacro H_PX $HY 130
  !insertmacro H_PX $HW $HT1
  !insertmacro H_PX $HH 20
  nsDialogs::CreateControl EDIT ${H_ST_EDIT} 0 $HX $HY $HW $HH "$INSTDIR"
  Pop $HDirEdit
  SendMessage $HDirEdit ${WM_SETFONT} $HFontBody 0
  SetCtlColors $HDirEdit ${H_FG} ${H_RAISE}
  !insertmacro H_TOP $HDirEdit
  IntOp $HT1 $HBW - 100
  !insertmacro H_BUTTON $HCtl $HT1 122 100 36 "$(H_Browse)" 0 HOnBrowse
  !insertmacro H_TEXT $HCtl 0 168 $HBW 20 "$(H_Space)" $HFontSmall ${H_DIM} ${H_BG} ${H_ST_LINE}
  !insertmacro H_BUTTONS "$(H_Back)" HOnBack "$(H_Install)" HOnNext
  ${NSD_SetFocus} $HDirEdit
  nsDialogs::Show
FunctionEnd

Function HOnBrowse
  Pop $0
  ${NSD_GetText} $HDirEdit $1
  nsDialogs::SelectFolderDialog "$(H_BrowseTitle)" "$1"
  Pop $0
  ${If} $0 != error
  ${AndIf} $0 != ""
    ; as the stock page does: the product's own folder inside the chosen one
    StrLen $2 "${PRODUCTNAME}"
    StrCpy $3 $0 "" -$2
    ${If} $3 != "${PRODUCTNAME}"
      StrCpy $3 $0 "" -1
      ${If} $3 == "\"
        StrCpy $0 $0 -1
      ${EndIf}
      StrCpy $0 "$0\${PRODUCTNAME}"
    ${EndIf}
    ${NSD_SetText} $HDirEdit $0
  ${EndIf}
FunctionEnd

Function HLocationLeave
  ${NSD_GetText} $HDirEdit $0
  ${If} $0 == ""
    Abort
  ${EndIf}
  StrCpy $INSTDIR $0
FunctionEnd

; Tauri's reinstall page: $R1 the message, $R2 / $R3 the options, $R0 the version comparison.
Function HReinstallPage
  !insertmacro H_PAGE 2
  !insertmacro H_HEAD "$(alreadyInstalled)" "$R1"
  StrCpy $HOpt2Off 0
  !if "${ALLOWDOWNGRADES}" == "false"
    ${IfThen} $R0 = -1 ${|} StrCpy $HOpt2Off 1 ${|}
  !endif
  ${If} $ReinstallPageCheck <> 2
  ${OrIf} $HOpt2Off = 1
    StrCpy $ReinstallPageCheck 1
  ${EndIf}
  IntOp $HT1 $HBW - 16
  !insertmacro H_TEXT $HOpt1M 0 124 3 40 "" $HFontBody ${H_FG} ${H_ACCENT} ${H_ST_LINE}
  !insertmacro H_TEXT $HOpt1P 3 124 13 40 "" $HFontBody ${H_FG} ${H_RAISE} ${H_ST_LINE}
  !insertmacro H_TEXT $HOpt1T 16 124 $HT1 40 "$R2" $HFontBody ${H_FG} ${H_RAISE} ${H_ST_LINE}
  !insertmacro H_TEXT $HOpt2M 0 172 3 40 "" $HFontBody ${H_FG} ${H_ACCENT} ${H_ST_LINE}
  !insertmacro H_TEXT $HOpt2P 3 172 13 40 "" $HFontBody ${H_FG} ${H_RAISE} ${H_ST_LINE}
  !insertmacro H_TEXT $HOpt2T 16 172 $HT1 40 "$R3" $HFontBody ${H_FG} ${H_RAISE} ${H_ST_LINE}
  ${NSD_OnClick} $HOpt1T HOnOption1
  ${NSD_OnClick} $HOpt1P HOnOption1
  ${If} $HOpt2Off = 0
    ${NSD_OnClick} $HOpt2T HOnOption2
    ${NSD_OnClick} $HOpt2P HOnOption2
  ${EndIf}
  Call HPaintOptions
  !insertmacro H_BUTTONS "$(H_Back)" HOnBack "$(H_Next)" HOnNext
  nsDialogs::Show
FunctionEnd

Function HOnOption1
  Pop $0
  StrCpy $ReinstallPageCheck 1
  Call HPaintOptions
FunctionEnd

Function HOnOption2
  Pop $0
  StrCpy $ReinstallPageCheck 2
  Call HPaintOptions
FunctionEnd

Function HPaintOptions
  ${If} $ReinstallPageCheck = 2
    !insertmacro H_OPTION $HOpt2M $HOpt2P $HOpt2T 1
    !insertmacro H_OPTION $HOpt1M $HOpt1P $HOpt1T 0
  ${Else}
    !insertmacro H_OPTION $HOpt1M $HOpt1P $HOpt1T 1
    ${If} $HOpt2Off = 1
      !insertmacro H_OPTION $HOpt2M $HOpt2P $HOpt2T 2
    ${Else}
      !insertmacro H_OPTION $HOpt2M $HOpt2P $HOpt2T 0
    ${EndIf}
  ${EndIf}
FunctionEnd


; -- 3. Install --------------------------------------------------------------------------

; The stock install page stays underneath (it runs the sections) and is hidden; our page is
; drawn on the window at the body's place.
Function HInstallShow
  StrCpy $HStep 3
  Call HRail
  ; NSIS shows the stock page after this function, so it is moved out of sight instead
  FindWindow $0 "#32770" "" $HWNDPARENT
  System::Call 'user32::SetWindowPos(p r0, p 0, i -4000, i -4000, i 0, i 0, i 0x15)'
  !insertmacro H_BODYTEXT $HInst1 0 0 $HBW 32 "$(H_InstallTitle)" $HFontTitle ${H_FG} ${H_BG} ${H_ST_LINE}
  IntOp $HT1 $HBW - 216
  !insertmacro H_BODYTEXT $HInst2 0 52 $HT1 30 "$(H_Part1)" $HFontBody ${H_MUTED} ${H_BG} ${H_ST_LINE}
  !insertmacro H_BODYTEXT $HInst3 0 86 $HT1 30 "$(H_Part2)" $HFontBody ${H_MUTED} ${H_BG} ${H_ST_LINE}
  !insertmacro H_BODYTEXT $HInst4 0 120 $HT1 30 "$(H_Part3)" $HFontBody ${H_MUTED} ${H_BG} ${H_ST_LINE}
  !insertmacro H_BODYTEXT $HInst5 0 172 $HBW 40 "$(H_Unsigned)" $HFontSmall ${H_DIM} ${H_BG} ${H_ST_TEXT}
  IntOp $HT1 $HBW - 160
  IntOp $HT2 $HBH - 34
  !insertmacro H_BODYTEXT $HInst6 $HT1 $HT2 160 34 "$(H_Installing)" $HFontButton ${H_BG} ${H_FG} ${H_ST_BUTTON}
  ; the bars: a filled part and the rest, side by side
  IntOp $HT1 $HBW - 200
  !insertmacro H_PX $HBarX $HT1
  IntOp $HBarX $HBarX + $HBX
  !insertmacro H_PX $HBarW 200
  !insertmacro H_PX $HBarH 8
  !insertmacro H_PX $HBar1Y 63
  IntOp $HBar1Y $HBar1Y + $HBY
  !insertmacro H_PX $HBar2Y 97
  IntOp $HBar2Y $HBar2Y + $HBY
  !insertmacro H_PX $HBar3Y 131
  IntOp $HBar3Y $HBar3Y + $HBY
  !insertmacro H_WIN $HBar1F ${H_ST_LINE} $HBarX $HBar1Y 0 $HBarH
  !insertmacro H_WIN $HBar1R ${H_ST_LINE} $HBarX $HBar1Y $HBarW $HBarH
  !insertmacro H_WIN $HBar2F ${H_ST_LINE} $HBarX $HBar2Y 0 $HBarH
  !insertmacro H_WIN $HBar2R ${H_ST_LINE} $HBarX $HBar2Y $HBarW $HBarH
  !insertmacro H_WIN $HBar3F ${H_ST_LINE} $HBarX $HBar3Y 0 $HBarH
  !insertmacro H_WIN $HBar3R ${H_ST_LINE} $HBarX $HBar3Y $HBarW $HBarH
  SetCtlColors $HBar1F "" ${H_ACCENT}
  SetCtlColors $HBar2F "" ${H_ACCENT}
  SetCtlColors $HBar3F "" ${H_ACCENT}
  SetCtlColors $HBar1R "" ${H_RAISE}
  SetCtlColors $HBar2R "" ${H_RAISE}
  SetCtlColors $HBar3R "" ${H_RAISE}
  StrCpy $HDone1 0
  StrCpy $HDone2 0
  StrCpy $HFill1 0
  StrCpy $HFill2 0
  StrCpy $HFill3 0
FunctionEnd

Function HInstallClear
  System::Call 'user32::DestroyWindow(p $HInst1)'
  System::Call 'user32::DestroyWindow(p $HInst2)'
  System::Call 'user32::DestroyWindow(p $HInst3)'
  System::Call 'user32::DestroyWindow(p $HInst4)'
  System::Call 'user32::DestroyWindow(p $HInst5)'
  System::Call 'user32::DestroyWindow(p $HInst6)'
  System::Call 'user32::DestroyWindow(p $HBar1F)'
  System::Call 'user32::DestroyWindow(p $HBar1R)'
  System::Call 'user32::DestroyWindow(p $HBar2F)'
  System::Call 'user32::DestroyWindow(p $HBar2R)'
  System::Call 'user32::DestroyWindow(p $HBar3F)'
  System::Call 'user32::DestroyWindow(p $HBar3R)'
  StrCpy $HBar1F ""
  StrCpy $HBar2F ""
  StrCpy $HBar3F ""
FunctionEnd


Function HTick1
  IntOp $HDone1 $HDone1 + 1
  ${If} $HBar1F == ""
    Return
  ${EndIf}
  Push $0
  Push $1
  Push $2
  IntOp $0 $HDone1 * $HBarW
  IntOp $0 $0 / ${H_N1}
  ${If} $0 > $HBarW
    StrCpy $0 $HBarW
  ${EndIf}
  ${If} $0 <> $HFill1
    StrCpy $HFill1 $0
    !insertmacro H_SETBAR $HBar1F $HBar1R $HBar1Y
  ${EndIf}
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

Function HTick2
  IntOp $HDone2 $HDone2 + 1
  ${If} $HBar2F == ""
    Return
  ${EndIf}
  Push $0
  Push $1
  Push $2
  IntOp $0 $HDone2 * $HBarW
  IntOp $0 $0 / ${H_N2}
  ${If} $0 > $HBarW
    StrCpy $0 $HBarW
  ${EndIf}
  ${If} $0 <> $HFill2
    StrCpy $HFill2 $0
    !insertmacro H_SETBAR $HBar2F $HBar2R $HBar2Y
  ${EndIf}
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

Function HTick3
  ${If} $HBar3F == ""
    Return
  ${EndIf}
  Push $0
  Push $1
  Push $2
  ; the earlier parts are complete by now, whatever their counts said
  StrCpy $0 $HBarW
  !insertmacro H_SETBAR $HBar1F $HBar1R $HBar1Y
  !insertmacro H_SETBAR $HBar2F $HBar2R $HBar2Y
  IntOp $0 $HT9 * $HBarW
  IntOp $0 $0 / 100
  !insertmacro H_SETBAR $HBar3F $HBar3R $HBar3Y
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; A failed install: our page goes, the stock page with its details and buttons comes back.
Function .onInstFailed
  Call HInstallClear
  FindWindow $0 "#32770" "" $HWNDPARENT
  SetCtlColors $0 ${H_FG} ${H_BG}
  System::Call 'user32::SetWindowPos(p r0, p 0, i $HBX, i $HBY, i 0, i 0, i 0x15)'
  ShowWindow $0 ${SW_SHOW}
  GetDlgItem $1 $0 1006
  SetCtlColors $1 ${H_FG} ${H_BG}
  GetDlgItem $1 $0 1027
  ShowWindow $1 ${SW_HIDE}
  GetDlgItem $1 $0 1016
  ShowWindow $1 ${SW_SHOW}
  ; the stock Cancel / Close button, at the bottom right
  !insertmacro H_PX $2 116
  IntOp $2 $HCW - $2
  !insertmacro H_PX $3 44
  IntOp $3 $HCH - $3
  GetDlgItem $1 $HWNDPARENT 2
  System::Call 'user32::SetWindowPos(p r1, p 0, i r2, i r3, i 0, i 0, i 0x15)'
FunctionEnd

; -- 4. Finish -----------------------------------------------------------------------------

Function HFinishCreate
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
  Call HInstallClear
  !insertmacro H_PAGE 4
  StrCpy $HAtFinish 1
  ; the window's close box ends the installer here too (HUserAbort applies the choice)
  GetDlgItem $0 $HWNDPARENT 2
  EnableWindow $0 1
  !insertmacro H_TEXT $HCtl 0 0 $HBW 32 "$(H_FinishTitle)" $HFontTitle ${H_FG} ${H_BG} ${H_ST_LINE}
  !insertmacro H_PARTROW 52 "$(H_Part1)" 1
  !insertmacro H_PARTROW 86 "$(H_Part2)" 1
  !insertmacro H_PARTROW 120 "$(H_Part3)" 1
  ; "Keep working after the computer starts": a box and its label, both clickable
  !insertmacro H_TEXT $HCheckBox 0 179 14 14 "" $HFontBody ${H_FG} ${H_ACCENT} ${H_ST_LINE}
  IntOp $HT1 $HBW - 22
  !insertmacro H_TEXT $HCtl 22 172 $HT1 28 "$(H_Autostart)" $HFontBody ${H_FG} ${H_BG} ${H_ST_LINE}
  ${NSD_OnClick} $HCheckBox HOnToggle
  ${NSD_OnClick} $HCtl HOnToggle
  !insertmacro H_TEXT $HCtl 22 200 $HT1 40 "$(H_AutostartNote)" $HFontSmall ${H_DIM} ${H_BG} ${H_ST_TEXT}
  ; the result, as the prototype's: a check mark and what was done
  IntOp $HT1 $HBH - 80
  !insertmacro H_TEXT $HCtl 0 $HT1 16 28 "✓" $HFontCheck ${H_DONE} ${H_BG} ${H_ST_LINE}
  IntOp $HT2 $HBW - 18
  !insertmacro H_TEXT $HResult 18 $HT1 $HT2 28 "$(H_DoneLogin)" $HFontMono ${H_DONE} ${H_BG} ${H_ST_LINE}
  ${If} $HAutostart <> 1
    ${NSD_SetText} $HResult "$(H_Done)"
    SetCtlColors $HCheckBox ${H_FG} ${H_RAISE}
  ${EndIf}
  !insertmacro H_BUTTONS "$(H_Close)" HOnClose "$(H_Open)" HOnOpen
  nsDialogs::Show
FunctionEnd

Function HOnToggle
  Pop $0
  ${If} $HAutostart = 1
    StrCpy $HAutostart 0
    SetCtlColors $HCheckBox ${H_FG} ${H_RAISE}
    ${NSD_SetText} $HResult "$(H_Done)"
  ${Else}
    StrCpy $HAutostart 1
    SetCtlColors $HCheckBox ${H_FG} ${H_ACCENT}
    ${NSD_SetText} $HResult "$(H_DoneLogin)"
  ${EndIf}
  !insertmacro H_REPAINT $HCheckBox
FunctionEnd

Function HOnOpen
  Pop $0
  StrCpy $HOpen 1
  SendMessage $HWNDPARENT 0x408 1 0
FunctionEnd

Function HOnClose
  Pop $0
  StrCpy $HOpen 0
  SendMessage $HWNDPARENT 0x408 1 0
FunctionEnd

Function HFinishLeave
  Call HApplyAutostart
  ${If} $HOpen = 1
    Call RunMainBinary
  ${EndIf}
FunctionEnd

Function HUserAbort
  ${If} $HAtFinish = 1
    Call HApplyAutostart
  ${EndIf}
FunctionEnd

; The login item as chosen. The post-install hook has already applied the shell's one-time
; default (on), which also records that the default was given, so the shell's first start
; leaves this choice alone; an update (passive, no finish page) keeps what the user chose.
Function HApplyAutostart
  ${If} $HApplied = 1
    Return
  ${EndIf}
  StrCpy $HApplied 1
  ${If} $HAutostart = 1
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart on'
  ${Else}
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart off'
  ${EndIf}
  Pop $0
FunctionEnd

; -- the uninstaller: MUI's pages in the archive colours ------------------------------------

Function un.HGuiInit
  SetCtlColors $HWNDPARENT ${H_MUTED} ${H_BG}
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 20, *i 1, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 35, *i ${H_BG_REF}, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 36, *i ${H_FG_REF}, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 34, *i ${H_LINE_REF}, i 4)'
  GetDlgItem $0 $HWNDPARENT 1028
  ShowWindow $0 ${SW_HIDE}
  GetDlgItem $0 $HWNDPARENT 1256
  ShowWindow $0 ${SW_HIDE}
  GetDlgItem $0 $HWNDPARENT 1035
  ShowWindow $0 ${SW_HIDE}
  GetDlgItem $0 $HWNDPARENT 1036
  ShowWindow $0 ${SW_HIDE}
  GetDlgItem $0 $HWNDPARENT 1045
  ShowWindow $0 ${SW_HIDE}
FunctionEnd

; The current inner page: every child in the archive colours; the control on the stack loses
; its visual style so its text takes the colour (the "delete app data" check box).
Function un.HColorPage
  Exch $2
  Push $0
  Push $1
  FindWindow $0 "#32770" "" $HWNDPARENT
  SetCtlColors $0 ${H_MUTED} ${H_BG}
  StrCpy $1 0
  loop:
    FindWindow $1 "" "" $0 $1
    StrCmp $1 0 done
    SetCtlColors $1 ${H_MUTED} ${H_BG}
    Goto loop
  done:
  ${If} $2 != ""
    System::Call 'uxtheme::SetWindowTheme(p r2, w "", w "")'
    SetCtlColors $2 ${H_FG} ${H_BG}
  ${EndIf}
  Pop $1
  Pop $0
  Pop $2
FunctionEnd

Function un.HInstallShow
  FindWindow $0 "#32770" "" $HWNDPARENT
  GetDlgItem $1 $0 1004
  Push $1
  Call un.HColorPage
  FindWindow $0 "#32770" "" $HWNDPARENT
  GetDlgItem $1 $0 1004
  SendMessage $1 0x409 0 ${H_ACCENT_REF}
  SendMessage $1 0x2001 0 ${H_RAISE_REF}
  GetDlgItem $1 $0 1016
  SendMessage $1 0x1001 0 ${H_BG_REF}
  SendMessage $1 0x1026 0 ${H_BG_REF}
  SendMessage $1 0x1024 0 ${H_MUTED_REF}
FunctionEnd
