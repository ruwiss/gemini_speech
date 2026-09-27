# Gemini Speech

Tray dictation for Windows, macOS, and Linux. Hold a shortcut, speak, and the text is pasted where you were typing.

The app calls the Gemini Developer API. `Alt+Z` writes what you said with `gemini-3.5-transcribe-live`. A second shortcut, set in Settings, translates that speech with `gemini-3.5-live-translate-preview` into the language you pick. `Esc` cancels the recording. The tray icon records in the spoken language. Right-click it for Settings and Quit.

Smart transcription removes filler words. A live session lasts up to 10 minutes. There is no browser cookie, extension, or ffmpeg in this path.

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
| Record | `Alt+Z` |
| Translate | none, choose one in Settings |
| Cancel | `Esc` |

Translate pastes the speech in the language selected in Settings. Record and Translate cannot share one shortcut.

## Releases

Publishing a GitHub release builds the installers and attaches only these files:

| System | File |
| --- | --- |
| Windows | `GeminiSpeechAPI-Setup.exe` |
| macOS | `GeminiSpeechAPI-macos.dmg` |
| Linux | `GeminiSpeechAPI-linux.tar.gz` |

The Windows setup is per user and can start with Windows. On Linux, unpack the archive and run `GeminiSpeechAPI/GeminiSpeechAPI`. On macOS, open the app from the disk image.

The installed app checks GitHub a few seconds after it starts, and again every six hours. When a newer release is published, it downloads that installer and updates itself. A checkout started with `python -m gemini_speech` is left as it is.

To build locally:

```bash
pip install -r requirements.txt pyinstaller
python packaging/build.py
```

Windows also needs [Inno Setup 6](https://jrsoftware.org/isinfo.php).

## Cookie fallback

[`cookie-fallback`](cookie-fallback) is the previous tray app. It talks to Gemini's web speech service with a browser cookie instead of an API key. A browser extension keeps that cookie fresh while Brave, Chrome, Edge, or Chromium is open. It needs ffmpeg. See its own README to run it.
