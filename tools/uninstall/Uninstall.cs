// Uninstall.exe：AT 的干净卸载（2026-11-13 负责人定：安装目录里放一个，像一般软件那样）。
// 「应用和功能」里的普通卸载只删程序和游戏数据，设置和库存留着；这个可以连它们一起删，重要的东西先问。
// 由 Windows 自带的 C# 编译器生成（.NET Framework 4，每台 Windows 10/11 都有）：tools/build_standalone.py 的 build_uninstaller。
//
// 做的事：
//   1. 自己在要删的文件夹里，先复制到临时文件夹再跑（--root 带上安装位置）
//   2. 问玩家：设置 / 路标 / 目标这些记录删不删、库存记录删不删（默认都不删）
//   3. 调 Velopack 的正常卸载（Update.exe --uninstall --silent：删程序、快捷方式、「应用和功能」里的条目）
//   4. 删剩下的：安装文件夹残留、日志截图这些随手产生的；玩家勾了的才删设置和库存
// 只删这几个位置（都在安装位置的上一层，一般是 %LOCALAPPDATA%）：AT、AT_userdata、Programs\AT\userdata（老安装版留下的）、
// SCTradeCompanion 里 AT 自己的库存文件。SCTradeCompanion\inventory.db 是和原来的交易助手共用的，不删。
// 命令行（沙盒测试用）：--silent 不出窗口，这时要删设置加 --delete-settings、要删库存加 --delete-inventory。
// 从安装目录里起的那一份马上返回 0，真正干活的是临时文件夹里那份（AT_Uninstall_<编号>.exe），结果看它。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("卸载 AT 星际公民助手")]
[assembly: AssemblyProduct("AT 星际公民助手")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Uninstall
{
    const string Title = "卸载 AT 星际公民助手";
    // AT_userdata 里随手产生、不算玩家记录的：不管选什么都删
    static readonly string[] Disposable = { "logs", "shots", "shell", "window", "train", "updates" };
    static readonly string[] DisposableFiles = { "instance.lock", "window_url.txt" };
    static readonly List<string> failed = new List<string>();

    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        string root = null;
        bool silent = false, delSettings = false, delInventory = false;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--root" && i + 1 < args.Length) root = args[++i];
            else if (args[i] == "--silent") silent = true;
            else if (args[i] == "--delete-settings") delSettings = true;
            else if (args[i] == "--delete-inventory") delInventory = true;
        }
        if (root == null)
            return Stage(args);
        try
        {
            return Run(root.TrimEnd('\\'), silent, delSettings, delInventory);
        }
        catch (Exception e)
        {
            if (!silent)
                MessageBox.Show("卸载中途出错：" + e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 3;
        }
        finally
        {
            SelfDelete();       // 不管卸没卸成（取消、AT 还开着），临时文件夹里的这份自己都清掉
        }
    }

    // 从安装目录里双击起来的：确认这里是安装版，把自己复制到临时文件夹再跑（不然删不掉自己所在的文件夹）
    static int Stage(string[] args)
    {
        string here = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string parent = Path.GetDirectoryName(here);
        bool silent = Array.IndexOf(args, "--silent") >= 0;
        if (!IsInstallRoot(parent) || !String.Equals(Path.GetFileName(here), "current", StringComparison.OrdinalIgnoreCase))
        {
            if (!silent)
                MessageBox.Show("这里不是安装版（压缩包版或源码版）：退出 AT 后直接删除整个文件夹即可。\n\n库存记录另放在 %LOCALAPPDATA%\\SCTradeCompanion\\dubhe_inventory.db。",
                                Title, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        string tmp = Path.Combine(Path.GetTempPath(), "AT_Uninstall_" + Process.GetCurrentProcess().Id + ".exe");
        File.Copy(Application.ExecutablePath, tmp, true);
        var psi = new ProcessStartInfo(tmp, "--root \"" + parent + "\" " + String.Join(" ", args));
        psi.UseShellExecute = false;
        psi.WorkingDirectory = Path.GetTempPath();
        // 不等它：正常卸载会把安装文件夹里还在跑的程序（包括这一份）都结束掉，等也等不到结果
        using (Process.Start(psi))
            return 0;
    }

    // 安装位置长这样：文件夹叫 AT，里面有 Velopack 的 Update.exe
    static bool IsInstallRoot(string root)
    {
        return root != null && String.Equals(Path.GetFileName(root), "AT", StringComparison.OrdinalIgnoreCase)
            && File.Exists(Path.Combine(root, "Update.exe"));
    }

    static int Run(string root, bool silent, bool delSettings, bool delInventory)
    {
        if (!IsInstallRoot(root))
        {
            if (!silent)
                MessageBox.Show("没找到 AT 的安装位置：" + root, Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        string local = Path.GetDirectoryName(root);
        string user = Path.Combine(local, "AT_userdata");
        string inv = Path.Combine(local, "SCTradeCompanion");
        string oldInno = Path.Combine(local, @"Programs\AT");

        if (!silent)
        {
            bool[] pick = Ask(user, inv);
            if (pick == null) return 4;       // 取消
            delSettings = pick[0];
            delInventory = pick[1];
        }
        while (AtRunning())
        {
            if (silent) return 2;
            if (MessageBox.Show("AT 还开着。请先退出 AT（右下角托盘图标 → 退出），再点「重试」。", Title,
                                MessageBoxButtons.RetryCancel, MessageBoxIcon.Warning) != DialogResult.Retry)
                return 4;
        }

        // 正常卸载：删程序、快捷方式、「应用和功能」里的条目
        var psi = new ProcessStartInfo(Path.Combine(root, "Update.exe"), "--uninstall --silent");
        psi.UseShellExecute = false;
        psi.WorkingDirectory = root;
        using (Process p = Process.Start(psi))
            p.WaitForExit(120000);
        for (int i = 0; i < 50 && Directory.Exists(root); i++)   // Update.exe 最后删自己，稍等一下
            Thread.Sleep(200);

        DeleteTree(root, local);
        foreach (string d in Disposable)
            DeleteTree(Path.Combine(user, d), local);
        foreach (string f in DisposableFiles)
            DeleteFile(Path.Combine(user, f));
        bool oldGone = !File.Exists(Path.Combine(oldInno, "AT.exe"));   // 老安装版还装着就不碰它的文件夹
        if (delSettings)
        {
            DeleteTree(user, local);
            if (oldGone) DeleteTree(Path.Combine(oldInno, "userdata"), local);
        }
        if (delInventory && Directory.Exists(inv))
        {
            foreach (string f in Directory.GetFiles(inv, "dubhe_inventory.db*"))
                DeleteFile(f);
            foreach (string f in Directory.GetFiles(inv, "inventory_换算前备份_*.db"))
                DeleteFile(f);
        }
        RemoveIfEmpty(user);
        if (oldGone) RemoveIfEmpty(oldInno);
        RemoveIfEmpty(inv);

        if (!silent)
        {
            string msg = "AT 已卸载。";
            if (!delSettings && Directory.Exists(user)) msg += "\n\n设置、路标、目标清单留在：\n" + user;
            if (!delInventory && File.Exists(Path.Combine(inv, "dubhe_inventory.db"))) msg += "\n\n库存记录留在：\n" + inv;
            if (failed.Count > 0) msg += "\n\n下面这些没删掉（可能被占用），可以手动删除：\n" + String.Join("\n", failed.ToArray());
            MessageBox.Show(msg, Title, MessageBoxButtons.OK, failed.Count > 0 ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
        }
        return failed.Count > 0 ? 5 : 0;
    }

    static bool AtRunning()
    {
        foreach (string name in new[] { "AT", "ATShell" })
        {
            Process[] ps = Process.GetProcessesByName(name);
            foreach (Process p in ps) p.Dispose();
            if (ps.Length > 0) return true;
        }
        return false;
    }

    // 问玩家：返回 {删设置, 删库存}；取消返回 null
    static bool[] Ask(string user, string inv)
    {
        var form = new Form();
        form.Text = Title;
        form.FormBorderStyle = FormBorderStyle.FixedDialog;
        form.MaximizeBox = false;
        form.MinimizeBox = false;
        form.StartPosition = FormStartPosition.CenterScreen;
        form.Font = new Font("Microsoft YaHei UI", 9F);
        form.ClientSize = new Size(520, 330);
        try { form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }

        var head = new Label();
        head.Text = "将卸载 AT 程序和游戏数据（游戏数据重装后可以重新下载）。\n\n下面两样是你自己的记录，默认保留。要一起删掉就勾上：";
        head.SetBounds(20, 16, 480, 64);

        var cbSettings = new CheckBox();
        cbSettings.Text = "同时删除设置、路标、目标清单（删了找不回来）";
        cbSettings.SetBounds(20, 90, 480, 24);
        var pathSettings = new Label();
        pathSettings.Text = user;
        pathSettings.ForeColor = SystemColors.GrayText;
        pathSettings.SetBounds(40, 114, 460, 20);
        pathSettings.AutoEllipsis = true;
        cbSettings.Enabled = Directory.Exists(user);

        var cbInventory = new CheckBox();
        cbInventory.Text = "同时删除库存记录（删了找不回来）";
        cbInventory.SetBounds(20, 150, 480, 24);
        var pathInventory = new Label();
        pathInventory.Text = Path.Combine(inv, "dubhe_inventory.db");
        pathInventory.ForeColor = SystemColors.GrayText;
        pathInventory.SetBounds(40, 174, 460, 20);
        pathInventory.AutoEllipsis = true;
        cbInventory.Enabled = File.Exists(Path.Combine(inv, "dubhe_inventory.db"));

        var note = new Label();
        note.Text = "日志、截图这些随手产生的文件会一起清掉。卸载前请先退出 AT。";
        note.ForeColor = SystemColors.GrayText;
        note.SetBounds(20, 214, 480, 40);

        var ok = new Button();
        ok.Text = "卸载";
        ok.SetBounds(300, 280, 96, 32);
        var cancel = new Button();
        cancel.Text = "取消";
        cancel.DialogResult = DialogResult.Cancel;
        cancel.SetBounds(404, 280, 96, 32);
        ok.Click += delegate
        {
            if (cbSettings.Checked || cbInventory.Checked)
            {
                string what = (cbSettings.Checked ? "· 设置、路标、目标清单\n" : "") + (cbInventory.Checked ? "· 库存记录\n" : "");
                if (MessageBox.Show(form, "下面这些会被永久删除，无法恢复：\n\n" + what + "\n确定要删吗？", Title, MessageBoxButtons.YesNo,
                                    MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                    return;
            }
            form.DialogResult = DialogResult.OK;
        };
        form.Controls.AddRange(new Control[] { head, cbSettings, pathSettings, cbInventory, pathInventory, note, ok, cancel });
        form.CancelButton = cancel;
        form.ActiveControl = cancel;        // 回车 / 空格不会误触发卸载
        using (form)
        {
            if (form.ShowDialog() != DialogResult.OK) return null;
            return new[] { cbSettings.Checked, cbInventory.Checked };
        }
    }

    // 只删 local 下面的东西；遇到指到别处的链接（junction / 符号链接）只摘掉链接，不进去删
    static void DeleteTree(string path, string local)
    {
        if (!Directory.Exists(path)) return;
        string full = Path.GetFullPath(path).TrimEnd('\\');
        string baseDir = Path.GetFullPath(local).TrimEnd('\\') + "\\";
        if (!full.StartsWith(baseDir, StringComparison.OrdinalIgnoreCase) || full.Length <= baseDir.Length)
        {
            failed.Add(path + "（不在安装位置旁边，没动）");
            return;
        }
        DeleteDir(new DirectoryInfo(full));
    }

    static void DeleteDir(DirectoryInfo dir)
    {
        try
        {
            if ((dir.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                dir.Delete(false);
                return;
            }
            foreach (FileInfo f in dir.GetFiles())
                DeleteFile(f.FullName);
            foreach (DirectoryInfo d in dir.GetDirectories())
                DeleteDir(d);
            dir.Attributes = FileAttributes.Directory;
            dir.Delete(false);
        }
        catch (Exception)
        {
            failed.Add(dir.FullName);
        }
    }

    static void DeleteFile(string path)
    {
        try
        {
            if (!File.Exists(path)) return;
            File.SetAttributes(path, FileAttributes.Normal);
            File.Delete(path);
        }
        catch (Exception)
        {
            failed.Add(path);
        }
    }

    static void RemoveIfEmpty(string dir)
    {
        try
        {
            if (Directory.Exists(dir) && Directory.GetFileSystemEntries(dir).Length == 0)
                Directory.Delete(dir, false);
        }
        catch (Exception) { }
    }

    // 临时文件夹里的这份自己：退出后几秒由 cmd 删掉
    static void SelfDelete()
    {
        try
        {
            string tmp = Path.GetFullPath(Path.GetTempPath());
            if (!Path.GetFullPath(Application.ExecutablePath).StartsWith(tmp, StringComparison.OrdinalIgnoreCase))
                return;     // 不是临时文件夹里那份（有人直接带 --root 跑安装目录里的）：别把正主删了
            var psi = new ProcessStartInfo("cmd.exe", "/c ping -n 3 127.0.0.1 >nul & del /q \"" + Application.ExecutablePath + "\"");
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
        }
        catch (Exception) { }
    }
}
