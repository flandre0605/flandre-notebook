#ifndef AppVersion
  #define AppVersion "0.2.0-preview.1"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\FlandreNotebook"
#endif

[Setup]
AppId={{5A1BEF50-AEEB-4EE0-9627-475520E730E8}
AppName=芙兰错题本
AppVersion={#AppVersion}
AppPublisher=Flandre Notebook
AppPublisherURL=https://github.com/flandre0605/flandre-notebook
DefaultDirName={localappdata}\Programs\FlandreNotebook
DefaultGroupName=芙兰错题本
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=FlandreNotebook-{#AppVersion}-setup-x64
SetupIconFile=..\assets\flandre_icon.ico
UninstallDisplayIcon={app}\FlandreNotebook.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\芙兰错题本"; Filename: "{app}\FlandreNotebook.exe"
Name: "{autodesktop}\芙兰错题本"; Filename: "{app}\FlandreNotebook.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlandreNotebook.exe"; Description: "打开芙兰错题本"; Flags: nowait postinstall skipifsilent
