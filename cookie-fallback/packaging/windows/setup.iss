#define AppName "Gemini Speech"
#define AppVersion "1.0.0"
#define SourceDir "..\..\dist\GeminiSpeech"

[Setup]
AppId={{A7C3E1B4-6D20-4F8A-9B15-2E4C8A1D6F30}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\GeminiSpeech
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=GeminiSpeech-Setup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\GeminiSpeech.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: startup; Description: "Start Gemini Speech when I sign in"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Gemini Speech"; Filename: "{app}\GeminiSpeech.exe"
Name: "{userstartup}\Gemini Speech"; Filename: "{app}\GeminiSpeech.exe"; Tasks: startup

[Run]
Filename: "{app}\GeminiSpeech.exe"; Description: "Launch Gemini Speech"; Flags: nowait postinstall skipifsilent
