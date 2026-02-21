#!/bin/bash
set -euo pipefail

# Test the macOS launcher locally: build with signing, deploy to a test folder.
# Usage:
#   ./scripts/test-mac-launcher.sh          # Build production launcher
#   ./scripts/test-mac-launcher.sh --dev    # Build dev launcher (uses dev-latest channel)

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DIR="/Users/noahbaxter/Desktop/DM SYNC TEST"
VENV="$REPO_DIR/.venv/bin"
IDENTITY="Developer ID Application: Noah Baxter (KUP5WU7WPC)"

DEV_MODE=false
if [[ "${1:-}" == "--dev" ]]; then
  DEV_MODE=true
fi

BINARY_NAME="synchotic-launcher-macos"
if $DEV_MODE; then
  BINARY_NAME="synchotic-launcher-dev-macos"
fi

cd "$REPO_DIR"

# Inject dev release tag if building dev variant
if $DEV_MODE; then
  echo "=== Injecting dev release tag ==="
  sed -i '' 's/RELEASE_TAG = ""/RELEASE_TAG = "dev-latest"/' launcher.py
fi

echo "=== Building $BINARY_NAME (with codesign identity) ==="
CERTIFI_PATH=$("$VENV/python" -c "import certifi; print(certifi.where())")

# PyInstaller signs all embedded binaries during build when given --codesign-identity.
# This is required for --onefile since you can't sign the embedded libs after the fact.
"$VENV/pyinstaller" --onefile --name "$BINARY_NAME" --clean --noconfirm \
  --add-data "$CERTIFI_PATH:certifi" \
  --hidden-import certifi \
  --codesign-identity "$IDENTITY" \
  launcher.py

# Revert the sed change so we don't leave launcher.py dirty
if $DEV_MODE; then
  git -C "$REPO_DIR" checkout launcher.py
fi

echo ""
echo "=== Verifying signature ==="
codesign --verify --strict --verbose "dist/$BINARY_NAME"
codesign -dvv "dist/$BINARY_NAME"

echo ""
echo "=== Deploying to test directory ==="
mkdir -p "$TEST_DIR"
cp "dist/$BINARY_NAME" "$TEST_DIR/"
chmod +x "$TEST_DIR/$BINARY_NAME"

echo ""
echo "=== Done ==="
echo ""
echo "Deployed: $TEST_DIR/$BINARY_NAME"
echo ""
echo "To test:"
echo "  1. open '$TEST_DIR'"
echo "  2. Double-click $BINARY_NAME"
echo "  3. Check that .dm-sync/ is created in the test directory"
