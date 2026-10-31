#!/bin/bash
# Removes Tajmeea. Your downloaded files are never touched.
#   curl -fsSL https://raw.githubusercontent.com/Khxxxxd/tajmeea/main/uninstall.sh | bash
set -euo pipefail

SUPPORT="${HOME}/Library/Application Support/Tajmeea"
APP="${HOME}/Applications/Tajmeea.app"

osascript -e 'tell application id "com.khaledcli.tajmeea" to quit' >/dev/null 2>&1 || true
# Out of the Mac's login items too, while the app is still here to ask for it.
if [ -x "${APP}/Contents/MacOS/Tajmeea" ]; then
  "${APP}/Contents/MacOS/Tajmeea" --forget-login >/dev/null 2>&1 || true
fi
rm -rf "${APP}" "${SUPPORT}/venv" "${HOME}/Library/Caches/Tajmeea"

for item in api_id api_hash session; do
  security delete-generic-password -s Tajmeea -a "${item}" >/dev/null 2>&1 || true
done

echo "Done. Tajmeea, your Telegram key and your session are gone from this Mac."
echo "The files you downloaded stay where they are."
echo "Your library record is still here if you want it: ${SUPPORT}"
