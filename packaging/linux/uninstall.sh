#!/bin/sh
set -e
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/GeminiSpeechAPI"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

rm -f "$BIN_DIR/gemini-speech-api"
rm -f "$APP_DIR/gemini-speech-api.desktop"
rm -rf "$DEST"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "GeminiSpeechAPI removed."
