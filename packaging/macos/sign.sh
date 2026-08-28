#!/usr/bin/env bash
# Shared codesigning for the two macOS bundles, sourced by build_app.sh and
# build_launcher_app.sh.
#
# MACOS_SIGN_IDENTITY picks the identity: CI exports a Developer ID and then
# notarizes the result, a local build leaves it unset and signs ad-hoc. Only a
# Developer ID signature can be notarized, and only a notarized bundle opens on
# someone else's Mac without the right-click-Open dance.

sign_bundle() {
  local app="$1"
  local here identity
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  identity="${MACOS_SIGN_IDENTITY:--}"

  local flags=(--force --options runtime
               --entitlements "$here/entitlements.plist"
               --sign "$identity")
  # A secure timestamp needs Apple's timestamp server and a real identity;
  # codesign rejects the flag outright when signing ad-hoc.
  if [ "$identity" != "-" ]; then
    flags+=(--timestamp)
  fi

  # Nested binaries first. codesign seals a bundle over whatever is inside it,
  # so signing an inner binary afterwards invalidates the outer signature.
  # --deep would do this in one call, but it is deprecated, it cannot apply
  # entitlements per binary, and Apple's own guidance is to sign inside out.
  local bin
  while IFS= read -r bin; do
    codesign "${flags[@]}" "$bin"
  done < <(find "$app/Contents" -type f -perm -111 -print0 \
             | xargs -0 file --mime-type \
             | awk -F': ' '$2 ~ /mach-binary/ {print $1}')

  codesign "${flags[@]}" "$app"
  codesign --verify --strict --deep "$app"
}
