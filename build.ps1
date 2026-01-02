<#
.SYNOPSIS
    Build Synchotic for Windows

.DESCRIPTION
    Builds either the app (onedir → zip) or the launcher (tiny onefile).
    Default is app mode for CI.

.PARAMETER Mode
    Build mode: "App" (default) or "Launcher"

.PARAMETER BuildDir
    Directory to build in (should be on Windows filesystem for speed)

.PARAMETER SourceDir
    Source directory containing sync.py, launcher.py, etc.
#>

param(
    [Parameter()]
    [ValidateSet("App", "Launcher")]
    [string]$Mode = "App",

    [Parameter(Mandatory=$true)]
    [string]$BuildDir,

    [Parameter(Mandatory=$true)]
    [string]$SourceDir
)

$ErrorActionPreference = "Stop"

$AppName = "synchotic-app"
$LauncherName = "synchotic-launcher"

function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }

# Ensure build directory exists and is clean
if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null

# Copy source files
Write-Info "Copying source files..."
Copy-Item -Path "$SourceDir\sync.py" -Destination $BuildDir
Copy-Item -Path "$SourceDir\launcher.py" -Destination $BuildDir
Copy-Item -Path "$SourceDir\VERSION" -Destination $BuildDir
Copy-Item -Path "$SourceDir\drives.json" -Destination $BuildDir
Copy-Item -Path "$SourceDir\src" -Destination $BuildDir -Recurse

if ($Mode -eq "Launcher") {
    # Build launcher only (tiny, no dependencies embedded)
    Write-Info "Building launcher (onefile)..."
    Push-Location $BuildDir
    python -m PyInstaller --onefile --name $LauncherName --clean --noconfirm `
        launcher.py
    Pop-Location

    $OutputFile = "$BuildDir\dist\$LauncherName.exe"
    if (Test-Path $OutputFile) {
        $Size = (Get-Item $OutputFile).Length / 1MB
        Write-Info ("Built: $OutputFile ({0:N1} MB)" -f $Size)
    } else {
        Write-Host "[ERROR] Build failed" -ForegroundColor Red
        exit 1
    }
} else {
    # Build app (onedir → zip)

    # Download UnRAR if libs folder doesn't exist
    $LibsDir = "$BuildDir\libs\bin"
    if (-not (Test-Path "$SourceDir\libs")) {
        Write-Info "Downloading UnRAR..."

        $env:Path += ";C:\Program Files\7-Zip"

        $UnrarExe = "$BuildDir\unrarw64.exe"
        $UnrarDir = "$BuildDir\unrar_cli"

        Invoke-WebRequest -Uri "https://www.rarlab.com/rar/unrarw64.exe" -OutFile $UnrarExe
        7z x $UnrarExe -o"$UnrarDir" -y | Out-Null

        New-Item -ItemType Directory -Force -Path $LibsDir | Out-Null
        Copy-Item "$UnrarDir\UnRAR.exe" -Destination "$LibsDir\UnRAR.exe"
    } else {
        Copy-Item -Path "$SourceDir\libs" -Destination $BuildDir -Recurse
    }

    # Get certifi path for SSL certs
    $CertifiPath = python -c "import certifi; print(certifi.where())"

    # Build main app with --onedir
    Write-Info "Building app (onedir)..."
    Push-Location $BuildDir
    python -m PyInstaller --onedir --name $AppName --clean --noconfirm `
        --add-data "drives.json;." `
        --add-data "VERSION;." `
        --add-data "$CertifiPath;certifi" `
        --add-binary "libs\bin\UnRAR.exe;." `
        --hidden-import certifi `
        --hidden-import rarfile `
        sync.py
    Pop-Location

    # Copy version into app folder
    $DistAppDir = "$BuildDir\dist\$AppName"
    Copy-Item -Path "$BuildDir\VERSION" -Destination "$DistAppDir\.version"

    # Zip the app folder
    Write-Info "Creating app-windows.zip..."
    Push-Location $DistAppDir
    Compress-Archive -Path "*" -DestinationPath "..\app-windows.zip" -Force
    Pop-Location

    $OutputFile = "$BuildDir\dist\app-windows.zip"
    if (Test-Path $OutputFile) {
        $Size = (Get-Item $OutputFile).Length / 1MB
        Write-Info ("Built: $OutputFile ({0:N1} MB)" -f $Size)
    } else {
        Write-Host "[ERROR] Build failed" -ForegroundColor Red
        exit 1
    }
}
