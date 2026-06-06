; =====================================================================
;  Setlist Manager - Inno Setup installer script
;  Builds SetlistManagerSetup.exe that the end user just double-clicks.
;
;  How to build:
;    1. First run build_windows.bat (produces dist\SetlistManager.exe)
;    2. Install Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;    3. Open this file in Inno Setup Compiler and press F9 (Compile)
;    4. Output\SetlistManagerSetup.exe is the final installer
; =====================================================================

#define MyAppName      "Setlist Manager"
; Versionen kommer normalt fra env-variabel APP_VERSION som sættes af
; build_windows.bat eller GitHub Actions. Falder tilbage til 1.0.0
; hvis variablen ikke er sat.
#ifdef APP_VERSION
  #define MyAppVersion APP_VERSION
#else
  #define MyAppVersion GetEnv("APP_VERSION")
  #if MyAppVersion == ""
    #define MyAppVersion "1.0.0"
  #endif
#endif
#define MyAppPublisher "Setlist Manager"
#define MyAppExeName   "SetlistManager.exe"

[Setup]
AppId={{B3F3D0A1-7B6E-4A4E-9F2D-2E0B1C8A7E10}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=SetlistManagerSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
; CloseApplications/RestartApplications fjernet bevidst — de skabte race
; condition med PyInstaller --onefile's _MEI temp-mappe (resulterede i
; 'Failed to load Python DLL python312.dll'-fejl). Brugeren får i stedet
; en almindelig "Start [appname]"-checkbox til sidst i wizarden.
#if FileExists("assets\app.ico")
SetupIconFile=assets\app.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "danish";  MessagesFile: "compiler:Languages\Danish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; --onedir output: HELE dist\SetlistManager\ mappen kopieres til {app}.
; Det inkluderer SetlistManager.exe + python312.dll + _internal\* osv.
; Brugeren mærker intet — de dobbeltklikker bare "Setlist Manager"
; genvejen i Start-menuen som peger på SetlistManager.exe.
Source: "dist\SetlistManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md";             DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";     Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
