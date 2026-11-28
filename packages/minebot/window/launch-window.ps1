param(
    [Parameter(Mandatory = $true)][string]$Launcher,   # your launcher's program
    [Parameter(Mandatory = $true)][string]$Instance,   # the launcher instance that holds the window mod
    [Parameter(Mandatory = $true)][string]$Bridge,     # the body's bridge, http://127.0.0.1:PORT
    [int]$Seconds = 200
)
# Start the game window of a bot body (your own game, through your own launcher) and take it out of the
# foreground. The instance joins the bridge's view port by itself (the window mod, with the address
# `harness minebot window setup` wrote into the instance). Prints one line of JSON:
# {"joined": bool, "game": process id or null, "launcher": the process this script started}.
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Launcher)) { Write-Output (@{ joined = $false; game = $null; error = "no launcher at $Launcher" } | ConvertTo-Json -Compress); exit 1 }
# A game of this instance that still runs is ended: one window watches a body.
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'javaw.exe' -and $_.CommandLine -like "*$Instance*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
$started = Start-Process -FilePath $Launcher -ArgumentList '--launch', $Instance -WindowStyle Minimized -PassThru
$deadline = (Get-Date).AddSeconds($Seconds)
$joined = $false
while ((Get-Date) -lt $deadline -and -not $joined) {
    Start-Sleep -Seconds 2
    try { $joined = [bool](Invoke-RestMethod -Uri "$Bridge/state" -TimeoutSec 3).window.joined } catch { $joined = $false }
}
$game = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'javaw.exe' -and $_.CommandLine -like "*$Instance*" } | Select-Object -First 1
if ($game) {
    & (Join-Path $PSScriptRoot 'release-window.ps1') -ProcessId $game.ProcessId | Out-Null
    Write-Output (@{ joined = $joined; game = [int]$game.ProcessId; launcher = [int]$started.Id } | ConvertTo-Json -Compress)
} else {
    Write-Output (@{ joined = $joined; game = $null; launcher = [int]$started.Id } | ConvertTo-Json -Compress)
}
