# Gemini Speech

Tray dictation for Windows, macOS, and Linux. Press a shortcut, speak, press it again, and the text is pasted where you were typing.

The app calls the Gemini Developer API. Press `Alt+Z` to start and press it again to stop. The app writes what you said with `gemini-3.5-transcribe-live`. Settings can switch that to hold-to-talk. A second shortcut, set in Settings, translates that speech with `gemini-3.5-live-translate-preview` into the language you pick. That language starts as the language of the device. `Esc` cancels the recording. On Windows the words sit next to the pointer. On macOS and Linux they sit in a bar at the bottom center of the screen, above the Dock or panel. The tray icon records in the spoken language. Right-click it for Settings and Quit.

Smart transcription is the default. It removes filler words. Verbatim keeps every word, including fillers. Pick the microphone in Settings. A live session lasts up to 10 minutes. There is no browser cookie, extension, or ffmpeg in this path.

If you would rather use a signed-in Google session and no API key, the older build is in [`cookie-fallback`](cookie-fallback).

## Requirements

- Windows, macOS, or Linux
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- Python 3.11+ to run from source
 
## Run from source

```bash
pip install -r requirements.txt
python -m gemini_speech
```

The first window asks for the API key. Settings are stored here:

| System | Config |
| --- | --- |
| Windows | `%APPDATA%\GeminiSpeechAPI\config.json` |
| macOS | `~/Library/Application Support/GeminiSpeechAPI/config.json` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/GeminiSpeechAPI/config.json` |

## Shortcuts

| Action | Default |
| --- | --- |
| Record | `Alt+Z`, press to start and stop |
| Keys | Press to toggle. Hold is in Settings |
| Translate | none, choose one in Settings |
| Language | Device language |
| Transcript | Smart. Verbatim is in Settings |
| Microphone | System default |
| Cancel | `Esc` |

Translate pastes the speech in the language selected in Settings. On a new install that language is the device language. A language already saved by an older install stays as it is. Record and Translate cannot share one shortcut. The same press or hold choice applies to both. An older install with no Keys value uses press to toggle.

Paste types the text into the window you were using. If that keystroke does not land, the text stays on the clipboard and **Copy text** appears in the tray menu. A successful paste leaves that item hidden.

## Releases

Publishing a GitHub release builds the installers and attaches only these files:

| System | File |
| --- | --- |
| Windows | `GeminiSpeechAPI-Setup.exe` |
| macOS | `GeminiSpeechAPI-macos.dmg` |
| Linux | `GeminiSpeechAPI-linux.tar.gz` |

The Windows setup is per user and can start with Windows. On macOS, open the app from the disk image.

On Linux (including CachyOS / Arch), unpack and run the installer:

```bash
tar -xzf GeminiSpeechAPI-linux.tar.gz
./GeminiSpeechAPI/install.sh
```

That puts the app under `~/.local/share/GeminiSpeechAPI`, adds a desktop entry, and links `gemini-speech-api` into `~/.local/bin`. Uninstall with `~/.local/share/GeminiSpeechAPI/uninstall.sh`.

On Wayland (CachyOS default), KDE and Hyprland keep that bar at the bottom center of the screen you are using. Other compositors show the same window and place it themselves. Paste goes back to the window you were typing in. The text is always copied. If the account cannot open `/dev/uinput` and `ydotool` / `wtype` are not installed, KDE asks once to allow input control.

For a system-wide Arch / CachyOS package after the release asset exists:

```bash
curl -LO https://raw.githubusercontent.com/ruwiss/gemini_speech/main/packaging/arch/PKGBUILD
makepkg -si
```


The installed app checks GitHub a few seconds after it starts, and again every six hours. When a newer release is published, it downloads that installer and updates itself. A checkout started with `python -m gemini_speech` is left as it is.

To build locally:

```bash
pip install -r requirements.txt pyinstaller
python packaging/build.py
```

Windows also needs [Inno Setup 6](https://jrsoftware.org/isinfo.php).

## Cookie fallback

[`cookie-fallback`](cookie-fallback) is the previous tray app. It talks to Gemini's web speech service with a browser cookie instead of an API key. A browser extension keeps that cookie fresh while Brave, Chrome, Edge, or Chromium is open. It needs ffmpeg. See its own README to run it.
