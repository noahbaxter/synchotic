# Get a Windows box ready to run windows_check.py, and with -Build, build the
# app the way .github/workflows/build-app.yml does. Run by run_windows_check.sh.
param([string]$Base = "$env:USERPROFILE\synchotic-validate", [switch]$Build)
$ErrorActionPreference = "Stop"
Set-Location $Base

if (-not (Test-Path venv\Scripts\python.exe)) { python -m venv venv }
# From inside src: requirements.txt's -e paths are relative to where pip runs.
Push-Location src
& ..\venv\Scripts\python -m pip install -q -r requirements.txt
if ($LASTEXITCODE) { throw "pip install failed" }
Pop-Location

# UnRAR.exe, as .github/actions/setup-unrar fetches it for Windows
if (-not (Test-Path unrar_cli\UnRAR.exe)) {
    Invoke-WebRequest https://www.rarlab.com/rar/unrarw64.exe -OutFile unrarw64.exe
    & "C:\Program Files\7-Zip\7z.exe" x unrarw64.exe -ounrar_cli -y | Out-Null
    Remove-Item unrarw64.exe
}
New-Item -ItemType Directory -Force src\libs\bin | Out-Null
Copy-Item unrar_cli\UnRAR.exe src\libs\bin\

if ($Build) {
    Push-Location src
    $certifi = & ..\venv\Scripts\python -c "import certifi; print(certifi.where())"
    & ..\venv\Scripts\pyinstaller --onedir --name synchotic-app --clean --noconfirm --log-level ERROR `
        --icon packaging/windows/synchotic.ico `
        --add-data "drives.json;." `
        --add-data "src/drive/byoc_setup_instructions.txt;src/drive" `
        --add-data "docs/settings.template.jsonc;docs" `
        --add-data "VERSION;." `
        --add-data "$certifi;certifi" `
        --add-binary "libs/bin/UnRAR.exe;." `
        --hidden-import certifi `
        --hidden-import rarfile `
        --paths vendor/chotic-ui `
        --collect-submodules chotic_ui `
        sync.py
    if ($LASTEXITCODE) { throw "pyinstaller failed" }
    Copy-Item VERSION dist\synchotic-app\.version
    Pop-Location
    "built $Base\src\dist\synchotic-app\synchotic-app.exe"
}
