#!/bin/bash
# Tajmeea installer
#   curl -fsSL https://raw.githubusercontent.com/Khxxxxd/tajmeea/main/install.sh | bash
# Builds the latest release from source on your Mac (nothing prebuilt is downloaded), so macOS trusts it like your own.
# Messages stay in English and every variable is written ${like_this}: an Arabic letter next to a variable
# can break the script on someone else's Mac.
set -euo pipefail

REPO="${TAJMEEA_REPO:-Khxxxxd/tajmeea}"
SRC="${TAJMEEA_SRC:-}"
SUPPORT="${HOME}/Library/Application Support/Tajmeea"
DEST="${HOME}/Applications"

say() { printf '%s\n' "$*"; }
fail() { say ""; say "x ${*}"; exit 1; }

say "Tajmeea: getting ready..."

[ "$(uname -s)" = "Darwin" ] || fail "Tajmeea runs on macOS only."
MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "${MAJOR}" -ge 13 ] || fail "Tajmeea needs macOS 13 or newer."

if ! xcode-select -p >/dev/null 2>&1 || ! command -v swift >/dev/null 2>&1; then
  xcode-select --install >/dev/null 2>&1 || true
  fail "Apple's Command Line Tools are needed. A window from Apple just opened: click Install, then run this same command again."
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

if [ -z "${SRC}" ]; then
  # The newest numbered release, not whatever is on main right now.
  LATEST="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest")" \
    || fail "Couldn't reach GitHub. Check your internet connection and try again."
  TAG="${LATEST##*/}"
  case "${TAG}" in
    v[0-9]*) ;;
    *) fail "Couldn't find a Tajmeea release on GitHub." ;;
  esac
  say "- Downloading Tajmeea ${TAG}"
  curl -fsSL "https://github.com/${REPO}/archive/refs/tags/${TAG}.tar.gz" | tar -xz -C "${WORK}"
  SRC="$(find "${WORK}" -mindepth 1 -maxdepth 1 -type d | head -1)"
fi
[ -f "${SRC}/engine/requirements.txt" ] || fail "Some of Tajmeea's files are missing."

say "- Setting up the engine (about a minute the first time)"
mkdir -p "${SUPPORT}"
if [ ! -x "${SUPPORT}/venv/bin/python3" ]; then
  /usr/bin/python3 -m venv "${SUPPORT}/venv"
fi
"${SUPPORT}/venv/bin/python3" -m pip install --quiet --disable-pip-version-check --upgrade pip
"${SUPPORT}/venv/bin/python3" -m pip install --quiet --disable-pip-version-check -r "${SRC}/engine/requirements.txt"
# Optional: makes downloads several times faster. Only a ready-made build is used, never compiled here.
"${SUPPORT}/venv/bin/python3" -m pip install --quiet --disable-pip-version-check --only-binary=:all: "cryptg==0.5.2" >/dev/null 2>&1 || true

say "- Building the app"
APP="$(bash "${SRC}/scripts/build-app.sh" "${WORK}/dist" | tail -1)"
[ -d "${APP}" ] || fail "The build didn't work."

if pgrep -f "${DEST}/Tajmeea.app/Contents/MacOS/Tajmeea" >/dev/null 2>&1; then
  osascript -e 'tell application id "com.khaledcli.tajmeea" to quit' >/dev/null 2>&1 || true
  # Up to a minute: if a download is running, the app asks first.
  for _ in $(seq 1 240); do
    pgrep -f "${DEST}/Tajmeea.app/Contents/MacOS/Tajmeea" >/dev/null 2>&1 || break
    sleep 0.25
  done
  if pgrep -f "${DEST}/Tajmeea.app/Contents/MacOS/Tajmeea" >/dev/null 2>&1; then
    fail "Tajmeea is still open (maybe a download is running). Quit it and run this command again."
  fi
fi
mkdir -p "${DEST}"
rm -rf "${DEST}/Tajmeea.app"
cp -R "${APP}" "${DEST}/Tajmeea.app"

say ""
say "Done. Tajmeea is in your Applications folder, opening it now."
say "To update later, run the same command again."
open "${DEST}/Tajmeea.app"
