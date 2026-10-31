; AT 桥接安装程序（2026-10-27）：老的 Inno 安装版（1.0.x，装在 %LOCALAPPDATA%\Programs\AT）在线升级时下载的就是它
; 由 tools\build_velopack.py 调用：ISCC /DMyVersion=x.y.z /DSetupSha256=<AT-win-Setup.exe 的 SHA-256> /DOutDir=… AT_bridge.iss
; 本身不带 Velopack 安装包（150 MB 超过 Gitee 单个附件 100 MB，1.0.3 等老版本只认 Gitee / GitHub 的下载地址），
; 运行时从 AT 服务器下载 AT-win-Setup.exe（不通再试 GitHub），核对 SHA-256；旁边已经放着 AT-win-Setup.exe 就直接用（离线、沙盒测试）
; 做的事（全程不用管理员）：
;   1. 把老版的设置和记录 userdata 复制到新位置 %LOCALAPPDATA%\AT_userdata（新位置已经有就不动；Edge 窗口缓存、旧安装包不复制）
;   2. 静默运行 Velopack 安装程序，装到 %LOCALAPPDATA%\AT
;   3. 装好了才卸掉老的 Inno 版（静默卸载，老位置的 userdata 留着不删）
;   4. 打开新的 AT
; 自己不留下任何东西（不注册卸载项）。老版本 AT 带的是 Inno 的参数（/VERYSILENT 等），这个也是 Inno 做的，都认

#ifndef MyVersion
  #error 需要 /DMyVersion=x.y.z
#endif
#ifndef SetupSha256
  #error 需要 /DSetupSha256=AT-win-Setup.exe 的 SHA-256
#endif
#ifndef OutDir
  #define OutDir "."
#endif

[Setup]
AppId={{6C3C5B8E-3F8D-4C55-9E0B-AT0BRIDGE0001}
AppName=AT 星际公民助手
AppVersion={#MyVersion}
AppPublisher=Adm_TT
VersionInfoVersion={#MyVersion}.0
VersionInfoDescription=AT 星际公民助手 安装程序
CreateAppDir=no
Uninstallable=no
CreateUninstallRegKey=no
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=AT_Setup_{#MyVersion}
SetupIconFile=..\sc_mining\app\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Code]
const
  SetupUrl1 = 'https://dl.astral-trade.com/releases/v{#MyVersion}/AT-win-Setup.exe';
  SetupUrl2 = 'https://at-dl-1323647399.cos.ap-guangzhou.myqcloud.com/releases/v{#MyVersion}/AT-win-Setup.exe';   // 国内镜像（2026-10-29）
  SetupUrl3 = 'https://github.com/Adm-TT/Astral-Toolkit/releases/download/v{#MyVersion}/AT-win-Setup.exe';
  SetupSha = '{#SetupSha256}';
  OldKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{2FA2FDE9-6997-4C2B-8D7B-A7DBCBB941DB}_is1';

var
  OldDirCache: String;          // 老版位置只在一开始查一次：卸载后注册表项没了，再查会落到默认位置（复审 2026-10-27）
  ProgForm: TSetupForm;
  ProgBar: TNewProgressBar;
  ProgText: TNewStaticText;

procedure ShowProgress(const Msg: String; Marquee: Boolean);
begin
  // 进度小窗口（2026-10-27 老大要「安装程序显示进度」）：老版在线升级是静默运行的，以前下载 150 MB 时屏幕上什么都没有
  if ProgForm = nil then
  begin
    ProgForm := CreateCustomForm(ScaleX(420), ScaleY(96), False, False);
    ProgForm.Caption := 'AT 星际公民助手';
    ProgForm.BorderIcons := [];
    ProgText := TNewStaticText.Create(ProgForm);
    ProgText.Parent := ProgForm;
    ProgText.Left := ScaleX(20);
    ProgText.Top := ScaleY(18);
    ProgText.Width := ProgForm.ClientWidth - ScaleX(40);
    ProgText.AutoSize := False;
    ProgBar := TNewProgressBar.Create(ProgForm);
    ProgBar.Parent := ProgForm;
    ProgBar.Left := ScaleX(20);
    ProgBar.Top := ScaleY(48);
    ProgBar.Width := ProgForm.ClientWidth - ScaleX(40);
    ProgBar.Height := ScaleY(18);
    ProgBar.Min := 0;
    ProgBar.Max := 100;
    ProgForm.Position := poScreenCenter;
    ProgForm.Show;
  end;
  ProgText.Caption := Msg;
  if Marquee then
    ProgBar.Style := npbstMarquee
  else
    ProgBar.Style := npbstNormal;
  ProgForm.Repaint;
end;

type
  TWinMsg = record
    hwnd: HWND;
    message: UINT;
    wParam: Longint;
    lParam: Longint;
    time: DWORD;
    pt: TPoint;
  end;

function PeekMessage(var lpMsg: TWinMsg; hWnd: HWND; wMsgFilterMin, wMsgFilterMax, wRemoveMsg: UINT): BOOL;
  external 'PeekMessageW@user32.dll stdcall';
function TranslateMessage(const lpMsg: TWinMsg): BOOL;
  external 'TranslateMessage@user32.dll stdcall';
function DispatchMessage(const lpMsg: TWinMsg): Longint;
  external 'DispatchMessageW@user32.dll stdcall';

procedure PumpMessages();
var
  Msg: TWinMsg;
begin
  // 干等的时候也处理窗口消息：进度条照常动，不显示「未响应」（二审 2026-10-27）
  while PeekMessage(Msg, 0, 0, 0, 1) do
  begin
    TranslateMessage(Msg);
    DispatchMessage(Msg);
  end;
end;

procedure HideProgress();
begin
  if ProgForm <> nil then
  begin
    ProgForm.Close;
    ProgForm.Free;
    ProgForm := nil;
  end;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
var
  Pct: Integer;
begin
  Result := True;
  if (ProgForm = nil) or (ProgressMax <= 0) then
    exit;
  Pct := (Progress * 100) div ProgressMax;
  ProgBar.Position := Pct;
  ProgText.Caption := Format('正在下载新版 AT… %d%%（%d / %d MB）', [Pct, Integer(Progress div 1048576), Integer(ProgressMax div 1048576)]);
  ProgForm.Repaint;
end;

function OldDir(): String;
begin
  if OldDirCache <> '' then
  begin
    Result := OldDirCache;
    exit;
  end;
  Result := '';
  if not RegQueryStringValue(HKCU, OldKey, 'InstallLocation', Result) then
    Result := ExpandConstant('{localappdata}\Programs\AT\');
  Result := RemoveBackslash(Result);
  OldDirCache := Result;
end;

function CopyUserdata(): Boolean;
var
  Src, Dst: String;
  Code: Integer;
begin
  // 返回 False = 没搬成（调用方保持老版不动、重新打开老版）
  Result := True;
  Src := OldDir() + '\userdata';
  Dst := ExpandConstant('{localappdata}\AT_userdata');
  if not DirExists(Src) then
  begin
    Log('老版没有 userdata：' + Src);
    exit;
  end;
  if FileExists(Dst + '\.migrated_from_inno') then
  begin
    Log('以前已经搬过，不再搬：' + Dst);
    exit;
  end;
  // robocopy 返回 0–7 都算成功。不复制：Edge 窗口缓存（window）、旧安装包（updates）、老版的窗口地址和单实例锁、
  // 本安装程序正在写的日志 install.log（被占用会报错，二审 2026-10-27）。/XO：新位置里更新的文件不拿旧的盖
  Exec(ExpandConstant('{sys}\robocopy.exe'), '"' + Src + '" "' + Dst + '" /E /XO /XD window updates /XF window_url.txt instance.lock install.log /R:1 /W:1 /NFL /NDL /NJH /NJS',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Log('复制 userdata：robocopy 返回 ' + IntToStr(Code));
  if Code >= 8 then
  begin
    Result := False;
    exit;
  end;
end;

function GetSetup(var Path: String): Boolean;
var
  Local: String;
begin
  // 旁边放着同一个安装包（校验对得上）就用它；否则下载：AT 服务器 → 国内镜像 → GitHub，DownloadTemporaryFile 自己核对 SHA-256
  Result := False;
  Local := ExpandConstant('{src}\AT-win-Setup.exe');
  if FileExists(Local) then
  begin
    if GetSHA256OfFile(Local) = SetupSha then
    begin
      Path := Local;
      Result := True;
      Log('用旁边的安装包：' + Local);
      exit;
    end;
    Log('旁边的安装包校验不对，不用');
  end;
  try
    ShowProgress('正在下载新版 AT…', False);
    DownloadTemporaryFile(SetupUrl1, 'AT-win-Setup.exe', SetupSha, @OnDownloadProgress);
    Result := True;
  except
    Log('AT 服务器下载失败：' + GetExceptionMessage);
    try
      ShowProgress('AT 服务器无法连接，改从国内镜像下载…', False);
      DownloadTemporaryFile(SetupUrl2, 'AT-win-Setup.exe', SetupSha, @OnDownloadProgress);
      Result := True;
    except
      Log('国内镜像下载失败：' + GetExceptionMessage);
      try
        ShowProgress('国内镜像无法连接，改从 GitHub 下载…', False);
        DownloadTemporaryFile(SetupUrl3, 'AT-win-Setup.exe', SetupSha, @OnDownloadProgress);
        Result := True;
      except
        Log('GitHub 下载失败：' + GetExceptionMessage);
      end;
    end;
  end;
  if Result then
    Path := ExpandConstant('{tmp}\AT-win-Setup.exe');
end;

function CopyData(): Boolean;
var
  Code: Integer;
begin
  Result := True;
  // 老版 data 里下载来的东西（汉化包 loc、掉落明细、scmdb 原始数据）不在安装包里，卸老版会一起删：先复制到新位置
  //（2026-10-27 在老大电脑上发现升级完「汉化包：未下载」）。安装包自带的那些新版第一次启动会用自带的覆盖
  if not DirExists(OldDir() + '\data') then
    exit;
  // robocopy 返回 0–7 是成功（有没有复制、有没有多出的文件），8 以上是有文件没复制成（二审 2026-10-27）
  if not Exec(ExpandConstant('{sys}\robocopy.exe'), '"' + OldDir() + '\data" "' + ExpandConstant('{localappdata}\AT\data') + '" /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS',
       '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := 16;
  Log('复制 data：robocopy 返回 ' + IntToStr(Code));
  Result := Code < 8;
end;

procedure ReopenOld();
var
  Code: Integer;
begin
  // 出问题就把老版重新打开：老版在线升级前已经自己退出了（二审 2026-10-27）
  if FileExists(OldDir() + '\AT.exe') then
    ExecAsOriginalUser(OldDir() + '\AT.exe', '', OldDir(), SW_SHOW, ewNoWait, Code);
end;

procedure UninstallOld();
var
  Cmd: String;
  Code: Integer;
begin
  if not RegQueryStringValue(HKCU, OldKey, 'UninstallString', Cmd) then
  begin
    Log('没找到老版的卸载程序');
    exit;
  end;
  Cmd := RemoveQuotes(Cmd);
  if FileExists(Cmd) then
  begin
    Exec(Cmd, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Log('卸载老版：返回 ' + IntToStr(Code));
  end;
end;

function NewExe(): String;
begin
  // Velopack 的启动器按程序名叫「AT 星际公民助手.exe」（在 %LOCALAPPDATA%\AT），真正的程序在 current\AT.exe
  Result := ExpandConstant('{localappdata}\AT\AT 星际公民助手.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{localappdata}\AT\current\AT.exe');
end;

procedure WaitOldGone();
var
  I: Integer;
begin
  // Inno 的卸载程序会先把自己复制到临时文件夹再卸载，调用马上返回：等老版的 AT.exe 真没了再往下
  for I := 1 to 600 do
  begin
    if not FileExists(OldDir() + '\AT.exe') then
      exit;
    PumpMessages();
    Sleep(50);
  end;
  Log('等老版卸载超时');
end;

procedure FixShortcuts();
var
  Target: String;
begin
  // 老版卸载会删掉同名的桌面、开始菜单快捷方式（Velopack 刚建的也叫这个名字）：没了就重建，指向新版
  Target := NewExe();
  if not FileExists(ExpandConstant('{userdesktop}\AT 星际公民助手.lnk')) then
    CreateShellLink(ExpandConstant('{userdesktop}\AT 星际公民助手.lnk'), 'AT 星际公民助手', Target, '', ExtractFileDir(Target), '', 0, SW_SHOWNORMAL);
  if not FileExists(ExpandConstant('{userprograms}\AT 星际公民助手.lnk')) then
    CreateShellLink(ExpandConstant('{userprograms}\AT 星际公民助手.lnk'), 'AT 星际公民助手', Target, '', ExtractFileDir(Target), '', 0, SW_SHOWNORMAL);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  SetupPath: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  OldDir();                                // 先记下老版位置（自选安装位置的老玩家）
  if not CopyUserdata() then
  begin
    Log('复制设置和记录失败，不升级');
    if not WizardSilent then
      MsgBox('复制设置和记录失败，未升级。原来的 AT 未改动，可继续使用。', mbError, MB_OK);
    ReopenOld();
    exit;
  end;
  if not GetSetup(SetupPath) then
  begin
    HideProgress();
    Log('下载新版安装包失败，不升级');
    if not WizardSilent then
      MsgBox('下载新版 AT 失败。检查网络后重试；原来的 AT 未改动，可继续使用。', mbError, MB_OK);
    ReopenOld();
    exit;
  end;
  ShowProgress('正在安装新版 AT…', True);
  if not Exec(SetupPath, '--silent', '', SW_SHOW, ewWaitUntilTerminated, Code) or (Code <> 0) then
  begin
    HideProgress();
    Log('Velopack 安装失败：返回 ' + IntToStr(Code));
    if not WizardSilent then
      MsgBox('安装新版 AT 失败（代码 ' + IntToStr(Code) + '）。原来的 AT 未改动，可继续使用。', mbError, MB_OK);
    ReopenOld();
    exit;
  end;
  if not FileExists(ExpandConstant('{localappdata}\AT\current\AT.exe')) then
  begin
    HideProgress();
    Log('没找到装好的新版 AT：' + ExpandConstant('{localappdata}\AT\current\AT.exe'));
    ReopenOld();
    exit;
  end;
  ShowProgress('正在复制数据、卸载旧版…', True);
  if not CopyData() then
  begin
    // 数据没搬全就不卸老版（老版卸载会删掉它的 data），也不写「已搬过」标记，下次升级重新搬（二审 2026-10-27）
    // 新版已经装好、快捷方式也指向新版：以新版为准、打开新版，不再打开旧版（免得两个版本都在用，复审 2026-10-27）。
    // 旧版先不卸载，它的 data 还留着
    HideProgress();
    Log('复制 data 失败，不卸载旧版，打开新版');
    if not WizardSilent then
      MsgBox('部分数据未复制完整（磁盘空间不足或文件被占用）。新版 AT 已安装并打开，在新版中点「更新数据」可补齐；旧版暂时保留。', mbInformation, MB_OK);
    SaveStringToFile(ExpandConstant('{localappdata}\AT_userdata\.migrated_from_inno'), 'bridge', False);
    FixShortcuts();
    ExecAsOriginalUser(NewExe(), '', ExtractFileDir(NewExe()), SW_SHOW, ewNoWait, Code);
    exit;
  end;
  // 装成功、数据也搬全了才写「已搬过」标记：失败时老版会继续用，下次升级要重新搬（只拿新的文件盖旧的，复审 2026-10-27）
  SaveStringToFile(ExpandConstant('{localappdata}\AT_userdata\.migrated_from_inno'), 'bridge', False);
  UninstallOld();
  WaitOldGone();
  FixShortcuts();
  HideProgress();
  ExecAsOriginalUser(NewExe(), '', ExtractFileDir(NewExe()), SW_SHOW, ewNoWait, Code);
end;
