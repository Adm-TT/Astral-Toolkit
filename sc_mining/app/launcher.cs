// Dubhe.exe：只负责用 pythonw（不带黑色命令行窗口）启动助手。
// 由 Windows 自带的 C# 编译器生成：sc_mining/app/build_exe.py
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("天枢 Dubhe")]
[assembly: AssemblyProduct("天枢 Dubhe")]
[assembly: AssemblyDescription("天枢")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(root, @".venv\Scripts\pythonw.exe");
        if (!File.Exists(py))
        {
            MessageBox.Show("还没安装：先双击「首次安装.bat」，装好后再打开我。", "天枢",
                            MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        var psi = new ProcessStartInfo(py, "-X utf8 -m sc_mining.run menu");
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("启动失败：" + e.Message, "天枢", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
