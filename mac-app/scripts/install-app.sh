#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
app_root=${script_dir:h}
repo_root=${app_root:h}
destination="${HOME}/Applications/Geode Transfer.app"
build_root="${app_root}/.build/release"

cd "$app_root"
swift build -c release

rm -rf "$destination"
mkdir -p "$destination/Contents/MacOS" "$destination/Contents/Resources"
cp "$build_root/GeodeTransfer" "$destination/Contents/MacOS/GeodeTransfer"
cp "$repo_root/geode_transfer.py" "$destination/Contents/Resources/geode_transfer.py"
cp "$app_root/App/Info.plist" "$destination/Contents/Info.plist"

codesign --force --sign - "$destination"
open "$destination"
