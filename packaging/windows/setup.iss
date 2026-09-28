#define AppName "GeminiSpeechAPI"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define SourceDir "..\..\dist\GeminiSpeechAPI"

[Setup]
AppId={{B8E4F2C5-7E31-4A9B-8C26-3F5D9B2E7041}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\GeminiSpeechAPI
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=GeminiSpeechAPI-Setup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\GeminiSpeechAPI.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: startup; Description: "Start GeminiSpeechAPI when I sign in"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\GeminiSpeechAPI"; Filename: "{app}\GeminiSpeechAPI.exe"
Name: "{userstartup}\GeminiSpeechAPI"; Filename: "{app}\GeminiSpeechAPI.exe"; Tasks: startup

[Run]
Filename: "{app}\GeminiSpeechAPI.exe"; Description: "Launch GeminiSpeechAPI"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\GeminiSpeechAPI.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent
