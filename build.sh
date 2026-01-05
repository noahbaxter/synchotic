#!/bin/bash
#
# Build Synchotic components
#
# Modes:
#   ./build.sh           Build app only (default, used by CI)
#   ./build.sh app       Build app only (onedir → zip)
#   ./build.sh launcher  Build launcher only (tiny onefile)
#   ./build.sh dev <dir> Build both and copy to target dir for local testing
#   ./build.sh --clean   Remove build artifacts
#
# The launcher is built rarely (stable). App builds happen on every release.
#
# Dev mode usage:
#   ./build.sh dev /mnt/t/TEMP
#   Then run: launcher.exe --dev         (keeps settings, replaces app)
#             launcher.exe --dev --clean (fresh install)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

detect_platform() {
    case "$(uname -s)" in
        Darwin*)
            PLATFORM="macos"
            ARCH="$(uname -m)"
            if [ "$ARCH" = "arm64" ]; then
                echo_info "Detected: macOS (Apple Silicon)"
            else
                echo_info "Detected: macOS (Intel)"
            fi
            ;;
        MINGW*|CYGWIN*|MSYS*)
            PLATFORM="windows"
            echo_info "Detected: Windows"
            ;;
        Linux*)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                PLATFORM="wsl"
                echo_info "Detected: WSL (building for Windows via PowerShell)"
            else
                echo_error "Unsupported platform: Linux"
                echo_error "Use GitHub Actions for cross-platform builds."
                exit 1
            fi
            ;;
        *)
            echo_error "Unsupported platform: $(uname -s)"
            exit 1
            ;;
    esac
}

check_deps() {
    echo_info "Checking dependencies..."

    if [ "$PLATFORM" = "wsl" ]; then
        if ! powershell.exe -Command "python --version" &> /dev/null; then
            echo_error "Windows Python is required but not found"
            echo_error "Install Python from python.org (not Windows Store)"
            exit 1
        fi
        PYTHON_VERSION=$(powershell.exe -Command "python -c \"import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')\"" | tr -d '\r')
        echo_info "Windows Python version: $PYTHON_VERSION"
    else
        if ! command -v python3 &> /dev/null; then
            echo_error "Python 3 is required but not found"
            exit 1
        fi
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo_info "Python version: $PYTHON_VERSION"
    fi
}

setup_venv() {
    echo_info "Setting up virtual environment..."

    if [ "$PLATFORM" = "wsl" ]; then
        if ! powershell.exe -Command "python -c 'import PyInstaller'" 2>/dev/null; then
            WIN_PATH=$(wslpath -w "$SCRIPT_DIR")
            echo_info "Installing dependencies via Windows pip..."
            powershell.exe -Command "cd '$WIN_PATH'; pip install -q -r requirements.txt" > /dev/null
            powershell.exe -Command "cd '$WIN_PATH'; pip install -q pyinstaller" > /dev/null
        else
            echo_info "Dependencies already installed, skipping..."
        fi
    else
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi

        if [ "$PLATFORM" = "windows" ]; then
            source venv/Scripts/activate
        else
            source venv/bin/activate
        fi

        echo_info "Installing dependencies..."
        pip install --upgrade pip > /dev/null
        pip install -r requirements.txt > /dev/null
        pip install pyinstaller > /dev/null
    fi
}

# Build the app (onedir → zip)
build_app() {
    if [ "$PLATFORM" = "macos" ]; then
        echo_info "Building macOS app..."
        APP_NAME="synchotic-app"
        ZIP_NAME="app-macos.zip"
    else
        echo_info "Building Windows app..."
        APP_NAME="synchotic-app"
        ZIP_NAME="app-windows.zip"
    fi

    rm -rf build dist/*.spec

    if [ "$PLATFORM" = "wsl" ]; then
        build_wsl "App" "dist/${ZIP_NAME}"
        return
    fi

    echo_info "Building app with --onedir..."
    pyinstaller \
        --onedir \
        --name "$APP_NAME" \
        --clean \
        --noconfirm \
        sync.py 2>/dev/null

    echo_info "Creating $ZIP_NAME..."
    cd dist

    # Copy VERSION into the app folder
    cp ../VERSION "$APP_NAME/.version"

    if [ "$PLATFORM" = "windows" ]; then
        powershell -Command "Compress-Archive -Path '$APP_NAME/*' -DestinationPath '$ZIP_NAME' -Force"
    else
        zip -r -q "$ZIP_NAME" "$APP_NAME"
    fi
    cd ..

    # Cleanup intermediate files
    rm -rf "dist/$APP_NAME"

    OUTPUT_FILE="dist/${ZIP_NAME}"
    if [ -f "$OUTPUT_FILE" ]; then
        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo_info "Built: $OUTPUT_FILE ($SIZE)"
    else
        echo_error "Build failed"
        exit 1
    fi
}

# Build via WSL using PowerShell
# Usage: build_wsl <mode> <output_file>
build_wsl() {
    local MODE="$1"
    local OUTPUT_FILE="$2"

    WIN_TEMP=$(powershell.exe -Command '[System.IO.Path]::GetTempPath()' | tr -d '\r' | sed 's/\\$//')
    BUILD_DIR="${WIN_TEMP}synchotic-build"
    WIN_SRC=$(wslpath -w "$SCRIPT_DIR")

    echo_info "Running PowerShell build script ($MODE mode)..."
    powershell.exe -ExecutionPolicy Bypass -File "$WIN_SRC\\build.ps1" -Mode "$MODE" -BuildDir "$BUILD_DIR" -SourceDir "$WIN_SRC"

    echo_info "Copying result back..."
    mkdir -p dist
    cp "$(wslpath "${BUILD_DIR}/dist/$(basename "$OUTPUT_FILE")")" dist/

    powershell.exe -Command "Remove-Item -Recurse -Force '$BUILD_DIR'" 2>/dev/null

    if [ -f "$OUTPUT_FILE" ]; then
        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo_info "Built: $OUTPUT_FILE ($SIZE)"
    else
        echo_error "Build failed"
        exit 1
    fi
}

# Build the launcher (tiny onefile)
build_launcher() {
    if [ "$PLATFORM" = "macos" ]; then
        echo_info "Building macOS launcher..."
        LAUNCHER_NAME="synchotic-launcher-macos"
    else
        echo_info "Building Windows launcher..."
        LAUNCHER_NAME="synchotic-launcher"
    fi

    rm -rf build dist/*.spec

    if [ "$PLATFORM" = "wsl" ]; then
        build_wsl "Launcher" "dist/${LAUNCHER_NAME}.exe"
        return
    fi

    echo_info "Building launcher with --onefile..."
    pyinstaller \
        --onefile \
        --name "$LAUNCHER_NAME" \
        --clean \
        --noconfirm \
        launcher.py 2>/dev/null

    if [ "$PLATFORM" = "windows" ]; then
        OUTPUT_FILE="dist/${LAUNCHER_NAME}.exe"
    else
        OUTPUT_FILE="dist/${LAUNCHER_NAME}"
    fi

    if [ -f "$OUTPUT_FILE" ]; then
        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo_info "Built: $OUTPUT_FILE ($SIZE)"
    else
        echo_error "Build failed"
        exit 1
    fi
}

clean() {
    echo_info "Cleaning build artifacts..."
    rm -rf build dist *.spec __pycache__ src/__pycache__
    echo_info "Clean complete"
}

# Build both launcher and app, copy to target dir for local testing
build_dev() {
    local TARGET_DIR="$1"

    if [ -z "$TARGET_DIR" ]; then
        echo_error "Target directory required: ./build.sh dev <dir>"
        exit 1
    fi

    # Resolve to absolute path
    TARGET_DIR=$(cd "$TARGET_DIR" 2>/dev/null && pwd || echo "$TARGET_DIR")

    if [ ! -d "$TARGET_DIR" ]; then
        echo_error "Target directory does not exist: $TARGET_DIR"
        exit 1
    fi

    echo_info "Dev build → $TARGET_DIR"
    echo ""

    # Build launcher
    build_launcher

    # Build app
    build_app

    # Determine filenames based on platform
    if [ "$PLATFORM" = "macos" ]; then
        LAUNCHER_FILE="dist/synchotic-launcher-macos"
        APP_ZIP="dist/app-macos.zip"
    else
        LAUNCHER_FILE="dist/synchotic-launcher.exe"
        APP_ZIP="dist/app-windows.zip"
    fi

    echo ""
    echo_info "Copying to $TARGET_DIR..."

    cp "$LAUNCHER_FILE" "$TARGET_DIR/"
    cp "$APP_ZIP" "$TARGET_DIR/"

    echo_info "Done! Files copied:"
    echo_info "  - $(basename "$LAUNCHER_FILE")"
    echo_info "  - $(basename "$APP_ZIP")"
    echo ""
    echo_info "Just double-click the launcher - it auto-detects the zip."
    echo_info "Use --clean flag for fresh install (nukes .dm-sync first)"
}

usage() {
    echo "Usage: $0 [mode]"
    echo ""
    echo "Modes:"
    echo "  (none)     Build app only (default, for CI)"
    echo "  app        Build app only (onedir → zip)"
    echo "  launcher   Build launcher only (tiny onefile)"
    echo "  dev <dir>  Build both and copy to target dir for local testing"
    echo "  --clean    Remove build artifacts"
    echo "  --help     Show this help"
    echo ""
    echo "Output is created in the 'dist' directory."
    echo ""
    echo "Dev mode example:"
    echo "  ./build.sh dev /mnt/t/TEMP"
    echo "  Then run: launcher.exe --dev"
}

main() {
    case "${1:-}" in
        --clean)
            clean
            ;;
        --help|-h)
            usage
            ;;
        app|"")
            detect_platform
            check_deps
            setup_venv
            build_app
            ;;
        launcher)
            detect_platform
            check_deps
            setup_venv
            build_launcher
            ;;
        dev)
            detect_platform
            check_deps
            setup_venv
            build_dev "$2"
            ;;
        *)
            echo_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"
