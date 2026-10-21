#!/bin/sh
# Double-click this file in Finder to start the receipt app. Close the Terminal window to stop it.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed. macOS will offer to install it (Command Line Tools); accept, then run this again."
  xcode-select --install 2>/dev/null
  read -r _
  exit 1
fi
exec python3 server.py
