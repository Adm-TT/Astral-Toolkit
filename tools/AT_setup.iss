; AT 星际公民助手 安装程序（Inno Setup 6.7，2026-10-26）
; 由 tools\build_standalone.py --installer 调用：ISCC /DMyVersion=x.y.z /DSrcDir=…\dist\AT /DOutDir=… AT_setup.iss
; - 装到当前用户自己的目录（默认 %LOCALAPPDATA%\Programs\AT），不需要管理员权限
; - 升级 = 直接运行新的安装程序：只换程序文件，userdata（设置、路标、目标、日志）不动
; - 卸载时问要不要连设置和记录一起删（默认保留）

#ifndef MyVersion
  #error 需要 /DMyVersion=x.y.z
#endif
#ifndef SrcDir
  #error 需要 /DSrcDir=独立目录包的位置
#endif
#ifndef OutDir
  #define OutDir "."
#endif

[Setup]
AppId={{2FA2FDE9-6997-4C2B-8D7B-A7DBCBB941DB}
AppName=AT 星际公民助手
AppVersion={#MyVersion}
AppVerName=AT 星际公民助手 {#MyVersion}
AppPublisher=Adm_TT
AppPublisherURL=https://gitee.com/Adm_TT/Astral-Toolkit
AppSupportURL=https://gitee.com/Adm_TT/Astral-Toolkit
AppUpdatesURL=https://gitee.com/Adm_TT/Astral-Toolkit/releases
AppCopyright=© 2026 Adm_TT
VersionInfoVersion={#MyVersion}.0
VersionInfoDescription=AT 星际公民助手 安装程序
DefaultDirName={localappdata}\Programs\AT
DefaultGroupName=AT 星际公民助手
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=AT_Setup_{#MyVersion}
SetupIconFile={#SrcDir}\_internal\sc_mining\app\icon.ico
UninstallDisplayIcon={app}\AT.exe
UninstallDisplayName=AT 星际公民助手
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[InstallDelete]
; 旧版本的程序组件整个换掉，免得残留旧文件；userdata 不在这里，不受影响
Type: filesandordirs; Name: "{app}\_internal"
; 数据包记录：换成安装程序自带的数据后，下次「更新数据」重新下载最新数据包
Type: files; Name: "{app}\data\data_pack.json"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Excludes: "userdata\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AT 星际公民助手"; Filename: "{app}\AT.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AT 星际公民助手"; Filename: "{app}\AT.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; 普通安装：完成页勾选「运行 AT」；在线升级（静默安装）：装完自动重新打开
Filename: "{app}\AT.exe"; Description: "运行 AT 星际公民助手"; WorkingDir: "{app}"; Flags: nowait postinstall

[UninstallDelete]
; 游戏数据可以重新下载，卸载时删掉；userdata 由下面问玩家
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\selftest"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}\userdata')) then
  begin
    if UninstallSilent then
      exit;
    if MsgBox('是否同时删除 AT 的设置和记录（路标、目标、库存设置、日志等）？' + #13#10 + #13#10 +
              '选「否」保留，以后重新安装 AT 会接着使用。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}\userdata'), True, True, True);
  end;
end;
