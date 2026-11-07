#!/bin/bash
# Wrap Renderer — Mac launcher. Double-click in Finder.
# First run: finds Python 3, installs PyObjC into a private venv, puts "Wrap Renderer.app" on the Desktop.
cd "$(dirname "$0")" || exit 1
APPDIR="$(pwd)"
DATA="$HOME/Library/Application Support/WrapRenderer"
VENV="$DATA/venv"
mkdir -p "$DATA"

# ---- 1. find Python 3.8+ ----
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c 'import sys; assert sys.version_info >= (3, 8)' >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3 is needed. macOS will now offer to install the Command Line Tools (includes Python)."
  echo "Click Install, wait for it to finish, then double-click this file again."
  xcode-select --install >/dev/null 2>&1
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi

# ---- 2. private environment with PyObjC (first run only, ~30s) ----
if ! "$VENV/bin/python" -c 'import AppKit, PyObjCTools.AppHelper' >/dev/null 2>&1; then
  echo "First run: setting up Wrap Renderer (about 30 seconds)..."
  rm -rf "$VENV"
  "$PY" -m venv "$VENV" &&
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip &&
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check pyobjc-framework-Cocoa
  if ! "$VENV/bin/python" -c 'import AppKit' >/dev/null 2>&1; then
    echo "Setup failed (no internet?). Fix that and double-click this file again."
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
fi

# ---- 3. Desktop app (first run only) ----
APP="$HOME/Desktop/Wrap Renderer.app"
if [ ! -d "$APP" ]; then
  osacompile -o "$APP" -e "do shell script \"cd \" & quoted form of \"$APPDIR\" & \" && nohup \" & quoted form of \"$VENV/bin/python\" & \" wrap_renderer.py >/dev/null 2>&1 &\"" >/dev/null 2>&1 \
    && echo "Added 'Wrap Renderer' to your Desktop — use that from now on."
fi

# ---- 4. launch in the background ----
nohup "$VENV/bin/python" "$APPDIR/wrap_renderer.py" >/dev/null 2>&1 &
echo "Wrap Renderer is running — its menu-bar icon is ⫼. You can close this window."
sleep 2
osascript -e 'tell application "Terminal" to close (every window whose name contains "Start Wrap Renderer")' >/dev/null 2>&1 &
exit 0
