; MUSTACOM AQUA GESTION PRO — Inno Setup 6
; Build on Windows after PyInstaller creates dist\MustacomAquaGestionPro.
#define MyAppName "MUSTACOM AQUA GESTION PRO"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MUSTACOM SERVICES"
#define MyAppExeName "MustacomAquaGestionPro.exe"

[Setup]
AppId={{7E4A46B4-DBD2-4D83-96A0-7A11C0A20261}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=mailto:contact@mustacom.com
AppSupportURL=mailto:contact@mustacom.com
DefaultDirName={autopf}\MUSTACOM\AquaGestionPro
DefaultGroupName=MUSTACOM AQUA GESTION PRO
AllowNoIcons=yes
OutputDir=..\dist_installer
OutputBaseFilename=MustacomAquaGestionPro_Setup_1.0.0
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=1.0.0.0
VersionInfoCompany=MUSTACOM SERVICES
VersionInfoDescription=MUSTACOM AQUA GESTION PRO Installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"

[Files]
Source: "..\dist\MustacomAquaGestionPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MUSTACOM AQUA GESTION PRO"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\User guide"; Filename: "{app}\_internal\help\guide_ar.html"; WorkingDir: "{app}"
Name: "{autodesktop}\MUSTACOM AQUA GESTION PRO"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Uninstall MUSTACOM AQUA"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MUSTACOM AQUA GESTION PRO"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Application data is deliberately preserved to protect accounting history.

[UninstallDelete]
; No deletion of %LOCALAPPDATA%\MUSTACOM\MustacomAquaGestionPro.
; Users can remove it manually only after making a verified backup.
