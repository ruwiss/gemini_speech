#!/bin/sh
set -e
SRC=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST="${HOME}/.local/opt/GeminiSpeech"
mkdir -p "$DEST" "${HOME}/.local/share/applications" "${HOME}/.local/bin"
cp -R "$SRC/." "$DEST/"
chmod +x "$DEST/GeminiSpeech" "$DEST/cookie_host" "$DEST/cookie_host.sh" 2>/dev/null || true
cat > "${HOME}/.local/share/applications/gemini-speech.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gemini Speech
Comment=Type what you say
Exec=${DEST}/GeminiSpeech
Icon=${DEST}/assets/icon.png
Terminal=false
Categories=Utility;
EOF
ln -sfn "$DEST/GeminiSpeech" "${HOME}/.local/bin/gemini-speech"
"$DEST/GeminiSpeech" --install-host
echo "Installed to $DEST"
echo "Start it from the app menu, or run: $DEST/GeminiSpeech"
