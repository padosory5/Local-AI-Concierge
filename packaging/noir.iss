; Noir's Windows installer (Inno Setup, the same tool Ollama's installer uses).
; packaging/build.py runs it after PyInstaller: ISCC /DVersion=0.2.0 /DSource=..\dist\Noir noir.iss
; It installs for this user only, in their own Programs folder, so there is no
; admin prompt, and it never touches the data folder (chats, agents, settings),
; not even when uninstalling.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Source
  #define Source "..\dist\Noir"
#endif

[Setup]
AppId={{8E1C2F6A-3B4D-4E5F-9A1B-2C3D4E5F6A7B}
AppName=Noir Agents
AppVersion={#Version}
AppVerName=Noir Agents {#Version}
AppPublisher=Noir Agents
AppMutex=Local\NoirAgents.Noir
DefaultDirName={localappdata}\Programs\Noir
DefaultGroupName=Noir
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Noir-Setup-{#Version}
SetupIconFile=icons\noir.ico
UninstallDisplayIcon={app}\Noir.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put Noir on the desktop"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Noir"; Filename: "{app}\Noir.exe"
Name: "{autodesktop}\Noir"; Filename: "{app}\Noir.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Noir.exe"; Description: "Open Noir"; Flags: nowait postinstall skipifsilent
