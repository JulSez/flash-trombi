#define MyAppName "Flash Trombi"
#define MyAppVersion "0.5.0"
#define MyAppPublisher "Flash Trombi"
#define MyAppExeName "FlashTrombi.exe"

[Setup]
AppId={{6C4B88A6-3D58-4F67-9BF8-0B3ED3F89561}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\FlashTrombi
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\installer-output
OutputBaseFilename=FlashTrombi-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: checkedonce

[Files]
Source: "..\dist\FlashTrombi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Flash Trombi"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Flash Trombi"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer Flash Trombi"; Flags: nowait postinstall skipifsilent
