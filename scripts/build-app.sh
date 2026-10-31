#!/bin/bash
# Builds Tajmeea.app from source. Usage: scripts/build-app.sh [output-folder]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-${ROOT}/dist}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${ROOT}/engine/tajmeea_engine/__init__.py")"
APP="${OUT}/Tajmeea.app"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

if ! swift build -c release --package-path "${ROOT}/app" >"${TMP}/build.log" 2>&1; then
  cat "${TMP}/build.log" >&2
  exit 1
fi
BIN="$(swift build -c release --package-path "${ROOT}/app" --show-bin-path)/Tajmeea"

rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/Resources/engine" "${APP}/Contents/Resources/ar.lproj" "${APP}/Contents/Resources/en.lproj"
cp "${BIN}" "${APP}/Contents/MacOS/Tajmeea"
rsync -a --exclude ".DS_Store" "${ROOT}/ui/" "${APP}/Contents/Resources/ui/"
rsync -a --exclude "__pycache__" --exclude "*.pyc" "${ROOT}/engine/tajmeea_engine" "${APP}/Contents/Resources/engine/"
cp "${ROOT}/engine/requirements.txt" "${APP}/Contents/Resources/engine/"

cat > "${APP}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Tajmeea</string>
  <key>CFBundleDisplayName</key><string>تجميعة</string>
  <key>CFBundleIdentifier</key><string>com.khaledcli.tajmeea</string>
  <key>CFBundleExecutable</key><string>Tajmeea</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleDevelopmentRegion</key><string>ar</string>
  <key>CFBundleLocalizations</key><array><string>ar</string><string>en</string></array>
  <key>LSHasLocalizedDisplayName</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>تجميعة · تستخدم واجهة تيليجرام الرسمية، ومو تطبيق رسمي من تيليجرام.</string>
</dict>
</plist>
PLIST
printf '"CFBundleDisplayName" = "تجميعة";\n"CFBundleName" = "تجميعة";\n' > "${APP}/Contents/Resources/ar.lproj/InfoPlist.strings"
printf '"CFBundleDisplayName" = "Tajmeea";\n"CFBundleName" = "Tajmeea";\n' > "${APP}/Contents/Resources/en.lproj/InfoPlist.strings"

swift "${ROOT}/scripts/make-icon.swift" "${TMP}/AppIcon.iconset" >/dev/null
iconutil -c icns -o "${APP}/Contents/Resources/AppIcon.icns" "${TMP}/AppIcon.iconset"

codesign --force --deep --sign - "${APP}" >/dev/null 2>&1
echo "${APP}"
