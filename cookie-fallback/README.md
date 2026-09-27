# Gemini Speech

Tray app that types what you say. It uses Gemini's web speech service. There is no API key to paste. A browser extension keeps the Google cookie fresh while Brave, Chrome, Edge, or Chromium is open.

Record with the tray icon, or with the shortcut you set. Press it again to stop and paste. `Esc` cancels. Right-click the tray icon for Settings and Quit. There is no record shortcut until you save one.

## Requirements

- Windows, macOS, or Linux
- Brave, Chrome, Edge, or Chromium, signed in to Google
- [ffmpeg](https://ffmpeg.org). If it is missing, the first window shows the install command and notices when it appears.
- Python 3.11+ if you run from source

## Run from source

```bash
cd GeminiSpeech
pip install -r requirements.txt
python -m gemini_speech
```

First launch opens the setup window. After the extension has sent a cookie once, that window only shows the shortcuts.

## Install the extension

1. Open Brave, Chrome, Edge, or Chromium.
2. Type one of these in the address bar:
   - `brave://extensions`
   - `chrome://extensions`
   - `edge://extensions`
3. Turn on Developer mode.
4. Click Load unpacked.
5. Select the `extension` folder next to the app (from source, that is `GeminiSpeech/extension`).
6. Leave the browser open.

The extension id is fixed by the key in `extension/manifest.json`. Do not remove that key, or the native host will reject it.

## Cookies

The extension reads the Google cookies in the browser and sends them to a native host. Nothing else can refresh `__Secure-1PSID`. Firefox cookies are rejected by the speech service.

The host writes one file:

| System | Path |
| --- | --- |
| Windows | `%APPDATA%\GeminiSpeech\browser-cookies.txt` |
| macOS | `~/Library/Application Support/GeminiSpeech/browser-cookies.txt` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/GeminiSpeech/browser-cookies.txt` |

On first launch the app registers the native host for Chrome, Brave, Edge, and Chromium. On Linux it also writes the host file for Flatpak copies of those browsers when that Flatpak is installed.

Logs and settings live in the same config folder.

## Build an installer

From the project folder, on the system you want to ship for:

```bash
pip install -r requirements.txt pyinstaller
python packaging/build.py
```

| System | Result |
| --- | --- |
| Windows | `dist/GeminiSpeech-Setup.exe` if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed. Otherwise the app folder is `dist/GeminiSpeech`. |
| macOS | `dist/GeminiSpeech.dmg` |
| Linux | `dist/GeminiSpeech-linux.tar.gz`. Unpack it and run `./GeminiSpeech/install.sh`. |

The Windows setup is per-user. It does not need an administrator. It can add a startup shortcut.

The built app does not ship ffmpeg. On first launch it shows one install command for Windows, macOS, or Linux, and starts using ffmpeg as soon as that command finishes.

The cookie host is a separate console program (`cookie_host.exe` or `cookie_host`) so the browser can talk to it. The tray app is windowed and does not show a console.
