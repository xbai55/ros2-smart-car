#ifndef BundleDir
  #error BundleDir must point at the frozen application directory
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef AppVersion
  #define AppVersion "0.3.4"
#endif
[Setup]
AppId={{32704BFC-425A-42A1-A8CA-71395D422DAA}
AppName=InsightRover 智巡
AppVersion={#AppVersion}
AppPublisher=InsightRover
DefaultDirName={localappdata}\Programs\InsightRover
DefaultGroupName=InsightRover 智巡
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=InsightRover-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\insightrover.ico
AppMutex=Local\InsightRoverDesktop
UninstallDisplayIcon={app}\InsightRover.exe
CloseApplications=yes
DisableProgramGroupPage=yes
SetupLogging=yes
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\InsightRover 智巡"; Filename: "{app}\InsightRover.exe"; IconFilename: "{app}\_internal\desktop-assets\insightrover.ico"
Name: "{autodesktop}\InsightRover 智巡"; Filename: "{app}\InsightRover.exe"; IconFilename: "{app}\_internal\desktop-assets\insightrover.ico"; Tasks: desktopicon
[Run]
Filename: "{app}\InsightRover.exe"; Description: "打开 InsightRover 智巡"; Flags: nowait postinstall skipifsilent
