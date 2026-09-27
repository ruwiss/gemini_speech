#!/bin/sh
set -e
SRC=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/GeminiSpeechAPI"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_SRC=""

if [ ! -x "$SRC/GeminiSpeechAPI" ]; then
  echo "GeminiSpeechAPI binary not found next to install.sh" >&2
  exit 1
fi

mkdir -p "$DEST" "$BIN_DIR" "$APP_DIR"
# Keep the installed tree replaceable by the in-app updater.
rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$SRC"/. "$DEST"/
chmod +x "$DEST/GeminiSpeechAPI" "$DEST/install.sh" "$DEST/uninstall.sh" 2>/dev/null || true

if [ -f "$DEST/assets/icon.png" ]; then
  ICON_SRC="$DEST/assets/icon.png"
elif [ -f "$DEST/_internal/assets/icon.png" ]; then
  ICON_SRC="$DEST/_internal/assets/icon.png"
fi

cat > "$APP_DIR/gemini-speech-api.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GeminiSpeechAPI
Comment=Tray dictation with Gemini
Exec=$DEST/GeminiSpeechAPI
Icon=${ICON_SRC:-gemini-speech-api}
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=false
EOF

ln -sfn "$DEST/GeminiSpeechAPI" "$BIN_DIR/gemini-speech-api"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo "Add $BIN_DIR to your PATH if the command is not found."
    ;;
esac

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "Installed to $DEST"
echo "Start from the app menu, or run: gemini-speech-api"
echo "Uninstall with: $DEST/uninstall.sh"
