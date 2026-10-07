# Launch a built synchotic-app.exe against an isolated root for a while, then
# stop it and show what it logged. Never touches %LOCALAPPDATA%\Synchotic.
# Run by scripts/run_windows_check.sh --exe; -Base is its folder on the host.
param([string]$Base = "$env:USERPROFILE\synchotic-validate", [int]$Seconds = 30)
$ErrorActionPreference = "Stop"
$root = "$Base\exe-root"
$exe = "$Base\src\dist\synchotic-app\synchotic-app.exe"

if (Test-Path $root) { Remove-Item -Recurse -Force $root }
New-Item -ItemType Directory -Force "$root\.dm-sync", "$root\Sync Charts" | Out-Null
Copy-Item "$Base\auth\*" "$root\.dm-sync\"
# No BOM: Windows PowerShell's utf8 writes one, and settings must not need it.
$settings = @{ library_path = "$root\Sync Charts"; download_mode = "byoc"; version = 1 } | ConvertTo-Json
[System.IO.File]::WriteAllText("$root\.dm-sync\settings.json", $settings)
$started = Get-Date

$env:SYNCHOTIC_ROOT = $root
$env:SYNCHOTIC_OS_DIRS = "0"
$p = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
Start-Sleep $Seconds
$alive = -not $p.HasExited
if ($alive) { Stop-Process -Id $p.Id -Force }
"still running after ${Seconds}s: $alive"
"--- log:"
Get-ChildItem "$root\.dm-sync\logs\*.log" -ErrorAction SilentlyContinue |
    ForEach-Object { Get-Content $_ | Where-Object { $_ -and $_ -notmatch "HOME_" } | Select-Object -First 14 }
$touched = Get-ChildItem "$env:LOCALAPPDATA\Synchotic" -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt $started }
"--- files written to the real install: $(@($touched).Count)"
Start-Sleep 1
Remove-Item -Recurse -Force $root
if (-not $alive) { exit 1 }
