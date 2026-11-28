param([int]$ProcessId)
# Take the game window out of the foreground without closing or hiding it: it then lets go of the mouse.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WindowPlace {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@
$window = (Get-Process -Id $ProcessId).MainWindowHandle
$front = [WindowPlace]::GetForegroundWindow()
"foreground before: $front, game window: $window"
[void][WindowPlace]::ShowWindow($window, 6)      # minimize: the focus goes to the next window
Start-Sleep -Milliseconds 400
[void][WindowPlace]::ShowWindow($window, 4)      # show again without activating
[void][WindowPlace]::SetWindowPos($window, [IntPtr]1, 0, 0, 0, 0, 0x0013)  # to the bottom, no move, no size, no activate
Start-Sleep -Milliseconds 300
"foreground after: $([WindowPlace]::GetForegroundWindow())"
