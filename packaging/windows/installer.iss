#ifndef Payload
  #define Payload "payload"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0-beta.3"
#endif
[Setup]
AppId={{3F30FA64-8C2D-4C9B-A560-32BD9FEF5F81}
AppName=LungSight
AppVersion={#AppVersion}
AppPublisher=QIONX
DefaultDirName={localappdata}\Programs\LungSight
DefaultGroupName=LungSight
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=releases
OutputBaseFilename=LungSight-Setup-{#AppVersion}-win-x64
Compression=lzma2/fast
SolidCompression=yes
LZMANumBlockThreads=2
WizardStyle=modern
SetupIconFile=app-icon.ico
UninstallDisplayIcon={app}\LungSight.exe
SetupLogging=yes
CloseApplications=no
InfoBeforeFile=INSTALL_README.txt
[Languages]
Name: "chinesesimplified"; MessagesFile: "tools\ChineseSimplified.isl"
[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："
[Icons]
Name: "{group}\LungSight"; Filename: "{app}\LungSight.exe"
Name: "{autodesktop}\LungSight"; Filename: "{app}\LungSight.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\LungSight.exe"; Description: "Launch LungSight"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\LungSight.exe"; Parameters: "--shutdown"; Flags: runhidden waituntilterminated; RunOnceId: "StopLungSight"
[Code]
function HasVCRuntime(): Boolean;
var Installed, MajorVersion, MinorVersion, BuildVersion: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1)
    and RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Major', MajorVersion)
    and RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Minor', MinorVersion)
    and RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Bld', BuildVersion)
    and ((MajorVersion > 14) or ((MajorVersion = 14) and ((MinorVersion > 51) or ((MinorVersion = 51) and (BuildVersion >= 36247)))));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\LungSight.exe')) then
    if not Exec(ExpandConstant('{app}\LungSight.exe'), '--shutdown', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      Result := 'Please close LungSight before updating.';
  if (Result <> '') or HasVCRuntime() then Exit;
  if WizardSilent() then begin
    Result := 'Microsoft Visual C++ x64 Runtime is required. Install it from Microsoft before silent setup.';
    Exit;
  end;
  if MsgBox('首次运行需要 Microsoft VC++ x64 运行库。是否从微软官网下载并打开其安装向导？需要联网和管理员确认；请在微软向导中阅读并接受许可。', mbConfirmation, MB_YESNO) <> IDYES then begin
    Result := '请先安装 Microsoft VC++ x64 运行库，然后重新运行安装程序。';
    Exit;
  end;
  try
    DownloadTemporaryFile('https://download.visualstudio.microsoft.com/download/pr/ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C/VC_redist.x64.exe', 'VC_redist.x64.exe', '843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C', nil);
    if not ShellExec('runas', ExpandConstant('{tmp}\VC_redist.x64.exe'), '/install /norestart', '', SW_SHOW, ewWaitUntilTerminated, ExitCode) then
      Result := '微软运行库安装未完成，请完成安装后重试。'
    else if ExitCode = 3010 then begin
      NeedsRestart := True;
    end else if (ExitCode <> 0) or not HasVCRuntime() then
      Result := '微软运行库安装未成功，请完成安装后重试。';
  except
    Result := '无法从微软官网下载或验证运行库，请检查网络后重试。';
  end;
end;
