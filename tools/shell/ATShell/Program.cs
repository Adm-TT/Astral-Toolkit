// AT 窗口外壳（2026-10-27，老大定：WinUI 3 + WebView2，取代 Edge 应用窗口）
// AT（Python）用 ATShell.exe --url <界面地址> --data <WebView2 资料夹> --parent <AT 的进程号> 打开它。
// - 标题栏融进界面，最小化/最大化/关闭由 Windows 自己画（保住 Win11 分屏菜单），Mica 背景
// - 关窗口就是关窗口（AT 照旧在托盘里跑，和以前关 Edge 窗口一样）；AT 退出了它也跟着退
// - 记住窗口位置大小；外链用系统浏览器打开
// - 打不开 WebView2（电脑上没装运行库）：退出码 3，AT 改用 Edge 窗口
using System;
using System.Diagnostics;
using System.IO;
using Microsoft.UI;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Input;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace ATShell;

public static class Program
{
    public static string Url = "";
    public static string Data = "";
    public static int Parent;
    public static string LogFile = "";
    public static int Port;

    // 只认 AT 自己的本机界面：http、127.0.0.1、启动时给的端口、网址里不带用户名
    //（只比前缀的话 http://127.0.0.1:端口@别的网站/ 也能过，二审 2026-10-27）
    public static bool IsAt(string uri, int port = -1)
    {
        if (!Uri.TryCreate(uri, UriKind.Absolute, out var u)) return false;
        return u.Scheme == "http" && u.Host == "127.0.0.1" && u.UserInfo == "" && (port < 0 || u.Port == port);
    }

    public static void Log(string s)
    {
        try
        {
            if (LogFile != "")
                File.AppendAllText(LogFile, DateTime.Now.ToString("MM-dd HH:mm:ss ") + s + Environment.NewLine);
        }
        catch { }
    }

    // 窗口图标（2026-10-28）：icon.ico 同时登记到窗口（WM_SETICON）和窗口类上；应用标识用 Velopack 快捷方式的 velopack.AT
    //（AT 主程序随后也会把窗口标成 velopack.AT 并指定任务栏图标，见 app/winid.py）
    [System.Runtime.InteropServices.DllImport("shell32.dll")]
    static extern int SetCurrentProcessExplicitAppUserModelID([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string id);
    [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern IntPtr LoadImageW(IntPtr hInst, string name, uint type, int cx, int cy, uint flags);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern IntPtr SendMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern IntPtr SetClassLongPtrW(IntPtr hWnd, int index, IntPtr value);

    public static void ApplyIcon(IntPtr hwnd)
    {
        try
        {
            var f = Path.Combine(AppContext.BaseDirectory, "icon.ico");
            if (!File.Exists(f)) return;
            const uint IMAGE_ICON = 1, LR_LOADFROMFILE = 0x10, WM_SETICON = 0x80;
            var big = LoadImageW(IntPtr.Zero, f, IMAGE_ICON, 32, 32, LR_LOADFROMFILE);
            var small = LoadImageW(IntPtr.Zero, f, IMAGE_ICON, 16, 16, LR_LOADFROMFILE);
            if (big != IntPtr.Zero) SendMessageW(hwnd, WM_SETICON, (IntPtr)1, big);
            if (small != IntPtr.Zero) SendMessageW(hwnd, WM_SETICON, (IntPtr)0, small);
            const int GCLP_HICON = -14, GCLP_HICONSM = -34;
            if (big != IntPtr.Zero) SetClassLongPtrW(hwnd, GCLP_HICON, big);
            if (small != IntPtr.Zero) SetClassLongPtrW(hwnd, GCLP_HICONSM, small);
        }
        catch { }
    }

    [STAThread]
    public static int Main(string[] args)
    {
        try { SetCurrentProcessExplicitAppUserModelID("velopack.AT"); } catch { }
        for (int i = 0; i + 1 < args.Length; i++)
        {
            if (args[i] == "--url") Url = args[i + 1];
            else if (args[i] == "--data") Data = args[i + 1];
            else if (args[i] == "--parent") int.TryParse(args[i + 1], out Parent);
        }
        if (!IsAt(Url)) return 2;                                       // 只开 AT 自己的本机界面
        Port = new Uri(Url).Port;
        // 4. 先看有没有 WebView2 运行库：没有就直接退出码 3（AT 改开 Edge 窗口），不弹空窗口，也不靠窗口关闭后退出码能不能传出来
        try
        {
            if (string.IsNullOrEmpty(Microsoft.Web.WebView2.Core.CoreWebView2Environment.GetAvailableBrowserVersionString())) return 3;
        }
        catch { return 3; }
        if (Data == "") Data = Path.Combine(AppContext.BaseDirectory, "webview");
        Directory.CreateDirectory(Data);
        LogFile = Path.Combine(Data, "shell_log.txt");
        try { if (new FileInfo(LogFile).Length > 200_000) File.Delete(LogFile); } catch { }
        AppDomain.CurrentDomain.UnhandledException += (s, e) => Log("崩溃：" + e.ExceptionObject);
        WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            var ctx = new Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(
                Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread());
            System.Threading.SynchronizationContext.SetSynchronizationContext(ctx);
            _ = new App();
        });
        return Environment.ExitCode;
    }
}

public class App : Application
{
    Window? _w;

    public App() { RequestedTheme = ApplicationTheme.Dark; }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        UnhandledException += (s, e) => { Program.Log("未处理：" + e.Exception); };
        _w = new ShellWindow();
        _w.Activate();
    }
}

public class WinBox
{
    public int X, Y, W, H;
    public bool Max;

    // 存成一行：x,y,宽,高,是否最大化（不用 JSON：裁剪后的程序里 JSON 反射不保险）
    public override string ToString() => $"{X},{Y},{W},{H},{(Max ? 1 : 0)}";

    public static WinBox? Parse(string t)
    {
        var a = t.Trim().Split(',');
        if (a.Length != 5) return null;
        try
        {
            return new WinBox { X = int.Parse(a[0]), Y = int.Parse(a[1]), W = int.Parse(a[2]), H = int.Parse(a[3]), Max = a[4] == "1" };
        }
        catch { return null; }
    }
}

public class ShellWindow : Window
{
    // 颜色都取自 DESIGN.md / AT 界面（2026-10-27 换蓝金）：标题栏 #101e3c（和侧栏一样）、文字 #e9edf5、金 #c6ab6c
    static readonly Color Bg = Color.FromArgb(255, 0x10, 0x1E, 0x3C);
    static readonly Color Text = Color.FromArgb(255, 0xE9, 0xED, 0xF5);
    static readonly Color Dim = Color.FromArgb(255, 0x97, 0xA3, 0xB8);
    static readonly Color Amber = Color.FromArgb(255, 0xC6, 0xAB, 0x6C);
    const string Title_ = "AT 星际公民助手";        // 和 index.html 的 <title>、winid.TITLE 一样：AT 按标题找窗口
    readonly WebView2 _web;
    readonly string _boundsFile;
    // 顶条（2026-10-27 老大要：和我们的风格统一）：左段和侧边栏同色、右段和页面同色，三个按钮自己画
    readonly Grid _bar = new() { Height = BarH };
    readonly Border _railPart = new();
    readonly Border _railLine = new() { Width = 1, HorizontalAlignment = HorizontalAlignment.Right };
    readonly Border _rest = new();
    readonly TextBlock _brand = new() { Text = "AT", FontSize = 15, CharacterSpacing = 150, VerticalAlignment = VerticalAlignment.Center };
    readonly TextBlock _brandSub = new() { Text = "星际公民助手", FontSize = 12, CharacterSpacing = 80, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 1, 0, 0) };
    readonly Grid _drag = new();
    readonly (Border box, Border plate, Canvas glyph)[] _btns = new (Border, Border, Canvas)[3];   // 最小化、最大化、关闭
    readonly Image _mark = new() { Width = 22, Height = 22, VerticalAlignment = VerticalAlignment.Center };   // AT 标志（和网页侧栏里的同一个 SVG）
    // 三个按钮自己画（2026-10-28 用户：做个图标），不靠系统图标字体，也不用 XAML 解析（裁剪过的发布包里没有它，会崩）：
    // 10×10 的画布上放几条线，最大化 / 还原两个样子
    const int IMin = 0, IMax = 1, IRestore = 2, IClose = 3;

    static Canvas Icon(int kind)
    {
        var c = new Canvas { Width = 10, Height = 10, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        void L(double x1, double y1, double x2, double y2) =>
            c.Children.Add(new Microsoft.UI.Xaml.Shapes.Line { X1 = x1, Y1 = y1, X2 = x2, Y2 = y2, StrokeThickness = 1.2 });
        void R(double x, double y, double w, double h) =>
            c.Children.Add(new Microsoft.UI.Xaml.Shapes.Rectangle { Width = w, Height = h, StrokeThickness = 1.2, Margin = new Thickness(x, y, 0, 0) });
        switch (kind)
        {
            case IMin: L(0, 5, 10, 5); break;
            case IMax: R(0, 0, 10, 10); break;
            case IRestore: R(0, 2.5, 7.5, 7.5); L(2.5, 2.5, 2.5, 0.5); L(2.5, 0.5, 9.5, 0.5); L(9.5, 0.5, 9.5, 7.5); L(9.5, 7.5, 7.5, 7.5); break;
            default: L(0.5, 0.5, 9.5, 9.5); L(9.5, 0.5, 0.5, 9.5); break;
        }
        return c;
    }

    static void Tint(Canvas c, Color color)
    {
        var b = new SolidColorBrush(color);
        foreach (var ch in c.Children)
            if (ch is Microsoft.UI.Xaml.Shapes.Shape s) s.Stroke = b;
    }

    static void SetIcon(Canvas c, int kind)
    {
        c.Children.Clear();
        var fresh = Icon(kind);
        var items = new System.Collections.Generic.List<UIElement>(fresh.Children);
        fresh.Children.Clear();
        foreach (var it in items) c.Children.Add(it);
    }
    InputNonClientPointerSource? _nc;
    bool _light, _active = true;
    double _railW = 224;
    int _hover = -1, _press = -1;
    const double BarH = 40, BtnW = 46;

    // 两套主题的颜色，和 DESIGN.md 第 1 节一样（2026-10-27 深色换蓝金：左段 = 侧栏 --side、右段 = 页面底 --ink；浅色不改）
    static Color C(uint v) => Color.FromArgb(255, (byte)(v >> 16), (byte)(v >> 8), (byte)v);
    Color Ink => _light ? C(0xF2EFE8) : C(0x152851);
    Color Panel => _light ? C(0xFFFFFF) : C(0x101E3C);
    Color Raised => _light ? C(0xF6F4EF) : C(0x24396A);
    Color Hover => _light ? C(0xECE8DE) : C(0x203A6D);
    Color Line => _light ? C(0xE2DDD2) : C(0x2A4278);
    Color Fg => _light ? C(0x172538) : C(0xE9EDF5);
    Color Muted => _light ? C(0x3E4D60) : C(0xB4BED0);
    Color Faint => _light ? C(0x55647A) : C(0x97A3B8);
    Color Bad => _light ? C(0xA64B12) : C(0xFFB067);
    Color OnBad => _light ? C(0xFFFFFF) : C(0x172538);

    public ShellWindow()
    {
        Title = Title_;
        _boundsFile = Path.Combine(Program.Data, "window.txt");
        // 不要系统的标题栏和三个按钮（自己画），保留边框：拖边改大小、圆角、阴影照旧
        if (AppWindow.Presenter is OverlappedPresenter op)
        {
            op.SetBorderAndTitleBar(true, false);
            op.PreferredMinimumWidth = 900;
            op.PreferredMinimumHeight = 600;
        }

        var root = new Grid { Background = new SolidColorBrush(Bg) };
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(BarH) });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        _bar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(_railW) });
        _bar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        _bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        // 顶条左段画品牌（2026-10-28 用户：左上角留白意义不明）；网页里的品牌行在外壳里收起
        _brand.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
        var brandRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(16, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        _mark.Margin = new Thickness(0, 0, 10, 0);
        brandRow.Children.Add(_mark);
        brandRow.Children.Add(_brand);
        brandRow.Children.Add(_brandSub);
        var railGrid = new Grid();
        railGrid.Children.Add(brandRow);
        railGrid.Children.Add(_railLine);
        _railPart.Child = railGrid;                                   // 侧边栏右边那条线一直通到顶
        Grid.SetColumn(_railPart, 0);
        Grid.SetColumn(_rest, 1);
        Grid.SetColumnSpan(_rest, 2);
        _bar.Children.Add(_railPart);
        _bar.Children.Add(_rest);
        Grid.SetColumnSpan(_drag, 2);                                 // 拖动区：按钮以外的整条
        _bar.Children.Add(_drag);
        var btns = new StackPanel { Orientation = Orientation.Horizontal };
        int[] glyphs = { IMin, IMax, IClose };
        for (int i = 0; i < 3; i++)
        {
            var g = Icon(glyphs[i]);
            var plate = new Border { CornerRadius = new CornerRadius(6), Margin = new Thickness(5, 6, 5, 6), Child = g };
            var box = new Border { Width = BtnW, Height = BarH, Background = new SolidColorBrush(Colors.Transparent), Child = plate };
            int k = i;
            if (k != 1)                                                // 最大化交给 Windows（分屏菜单），另外两个自己处理
            {
                box.PointerEntered += (s, e) => { _hover = k; Paint(); };
                box.PointerExited += (s, e) => { if (_hover == k) _hover = -1; _press = -1; Paint(); };
                box.PointerPressed += (s, e) => { _press = k; Paint(); };
                box.PointerReleased += (s, e) =>
                {
                    bool hit = _press == k;
                    _press = -1; Paint();
                    if (!hit) return;
                    if (k == 0) (AppWindow.Presenter as OverlappedPresenter)?.Minimize();
                    else Close();
                };
            }
            _btns[i] = (box, plate, g);
            btns.Children.Add(box);
        }
        Grid.SetColumn(btns, 2);
        _bar.Children.Add(btns);
        Grid.SetRow(_bar, 0);
        root.Children.Add(_bar);

        _web = new WebView2 { DefaultBackgroundColor = Bg };
        Grid.SetRow(_web, 1);
        root.Children.Add(_web);
        Content = root;

        try { AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "icon.ico")); } catch { }
        try { Program.ApplyIcon(WinRT.Interop.WindowNative.GetWindowHandle(this)); } catch { }
        _nc = InputNonClientPointerSource.GetForWindowId(AppWindow.Id);
        _nc.PointerEntered += (s, e) => { if (e.RegionKind == NonClientRegionKind.Maximize) { _hover = 1; Paint(); } };
        _nc.PointerExited += (s, e) => { if (_hover == 1) { _hover = -1; _press = -1; Paint(); } };
        _nc.PointerPressed += (s, e) => { if (e.RegionKind == NonClientRegionKind.Maximize) { _press = 1; Paint(); } };
        _nc.PointerReleased += (s, e) => { _press = -1; Paint(); };
        root.SizeChanged += (s, e) => Regions();
        root.Loaded += (s, e) => Regions();
        AppWindow.Changed += (s, e) => { if (e.DidPresenterChange || e.DidSizeChange) { SetMaxGlyph(); Regions(); } };
        Activated += (s, e) => { _active = e.WindowActivationState != WindowActivationState.Deactivated; Paint(); };
        Paint();
        RestoreBounds();
        Closed += (s, e) => SaveBounds();
        WatchParent();
        _ = Load();
    }

    // 顶条和按钮的颜色：跟着主题、窗口在不在前台、鼠标停在哪个按钮上
    void Paint()
    {
        _railPart.Background = new SolidColorBrush(Panel);
        _railLine.Background = new SolidColorBrush(Line);
        _brand.Foreground = new SolidColorBrush(Fg);
        _brandSub.Foreground = new SolidColorBrush(Faint);
        try
        {
            var f = Path.Combine(AppContext.BaseDirectory, _light ? "at-mark-light.svg" : "at-mark-dark.svg");
            if (File.Exists(f) && (_mark.Tag as string) != f)
            {
                _mark.Source = new Microsoft.UI.Xaml.Media.Imaging.SvgImageSource(new Uri(f));
                _mark.Tag = f;
            }
        }
        catch { }
        _rest.Background = new SolidColorBrush(Ink);
        _bar.ColumnDefinitions[0].Width = new GridLength(_railW);
        for (int i = 0; i < 3; i++)
        {
            var (box, plate, g) = _btns[i];
            bool hot = _hover == i, down = _press == i;
            if (i == 2 && (hot || down))
            {
                plate.Background = new SolidColorBrush(Bad);            // 关闭：规范里「危险」的橙色
                Tint(g, OnBad);
            }
            else
            {
                plate.Background = new SolidColorBrush(down ? Hover : hot ? Raised : Colors.Transparent);
                Tint(g, hot || down ? Fg : _active ? Muted : Faint);
            }
        }
    }

    void SetMaxGlyph()
    {
        var max = (AppWindow.Presenter as OverlappedPresenter)?.State == OverlappedPresenterState.Maximized;
        SetIcon(_btns[1].glyph, max ? IRestore : IMax);                 // 最大化 / 还原
        Paint();
    }

    // 告诉 Windows：拖动区（双击放大、右键系统菜单）和「最大化」按钮在哪（这样鼠标停上去有 Win11 分屏菜单）
    void Regions()
    {
        if (_nc == null || Content?.XamlRoot == null) return;
        double sc = Content.XamlRoot.RasterizationScale;
        Windows.Graphics.RectInt32 R(FrameworkElement el)
        {
            var pt = el.TransformToVisual(Content).TransformPoint(new Windows.Foundation.Point(0, 0));
            return new Windows.Graphics.RectInt32((int)Math.Round(pt.X * sc), (int)Math.Round(pt.Y * sc),
                                                  (int)Math.Round(el.ActualWidth * sc), (int)Math.Round(el.ActualHeight * sc));
        }
        try
        {
            _nc.SetRegionRects(NonClientRegionKind.Caption, new[] { R(_drag) });
            _nc.SetRegionRects(NonClientRegionKind.Maximize, new[] { R(_btns[1].box) });
        }
        catch (Exception e) { Program.Log("设置顶条区域失败：" + e.Message); }
    }

    void RestoreBounds()
    {
        try
        {
            var b = WinBox.Parse(File.ReadAllText(_boundsFile));
            if (b != null && b.W >= 600 && b.H >= 400)
            {
                var area = DisplayArea.GetFromRect(new Windows.Graphics.RectInt32(b.X, b.Y, b.W, b.H), DisplayAreaFallback.Nearest);
                var wa = area.WorkArea;
                int w = Math.Min(b.W, wa.Width), h = Math.Min(b.H, wa.Height);
                int x = Math.Clamp(b.X, wa.X, wa.X + wa.Width - w), y = Math.Clamp(b.Y, wa.Y, wa.Y + wa.Height - h);
                AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(x, y, w, h));       // 显示器换了也不会跑到屏幕外
                if (b.Max) (AppWindow.Presenter as OverlappedPresenter)?.Maximize();
                return;
            }
        }
        catch { }
        var d = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary).WorkArea;
        int dw = Math.Min(1400, d.Width - 80), dh = Math.Min(900, d.Height - 80);
        AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(d.X + (d.Width - dw) / 2, d.Y + (d.Height - dh) / 2, dw, dh));
    }

    void SaveBounds()
    {
        try
        {
            var op = AppWindow.Presenter as OverlappedPresenter;
            var max = op?.State == OverlappedPresenterState.Maximized;
            if (op?.State == OverlappedPresenterState.Minimized) return;
            var b = new WinBox { X = AppWindow.Position.X, Y = AppWindow.Position.Y, W = AppWindow.Size.Width, H = AppWindow.Size.Height, Max = max };
            if (max && File.Exists(_boundsFile))
            {
                var old = WinBox.Parse(File.ReadAllText(_boundsFile));     // 最大化时记住还原后的大小
                if (old != null) { b.X = old.X; b.Y = old.Y; b.W = old.W; b.H = old.H; }
            }
            File.WriteAllText(_boundsFile, b.ToString());
        }
        catch { }
    }

    void WatchParent()
    {
        if (Program.Parent <= 0) return;
        Process? p = null;
        try { p = Process.GetProcessById(Program.Parent); } catch { }
        if (p == null) { Program.Log("AT 已经退出"); Close(); return; }
        var q = DispatcherQueue;
        new System.Threading.Thread(() =>
        {
            try { p.WaitForExit(); } catch { }
            q.TryEnqueue(() => Close());                 // AT 退了，窗口跟着关
        }) { IsBackground = true }.Start();
    }

    async System.Threading.Tasks.Task Load()
    {
        try
        {
            Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", Path.Combine(Program.Data, "wv2"));
            await _web.EnsureCoreWebView2Async();
        }
        catch (Exception e)
        {
            Program.Log("WebView2 打不开：" + e.Message);
            Environment.ExitCode = 3;                    // AT 看到 3 就改用 Edge 窗口
            Close();
            return;
        }
        var core = _web.CoreWebView2;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = true;
        core.Settings.IsZoomControlEnabled = false;          // 缩放了顶条左段就和侧边栏对不齐
        core.WebMessageReceived += (s, e) =>                // 网页发来：{"type":"chrome","light":true/false,"rail":224}
        {
            try
            {
                var j = System.Text.Json.JsonDocument.Parse(e.WebMessageAsJson).RootElement;
                if (j.GetProperty("type").GetString() != "chrome") return;
                _light = j.GetProperty("light").GetBoolean();
                var w = j.GetProperty("rail").GetDouble();
                if (w >= 0 && w < 600) _railW = w;
                _web.DefaultBackgroundColor = Ink;
                Paint();
            }
            catch { }
        };
        core.NewWindowRequested += (s, e) =>            // 外链：用系统浏览器打开
        {
            e.Handled = true;
            Open(e.Uri);
        };
        core.NavigationStarting += (s, e) =>            // 窗口里只开 AT 自己的界面，别的网址交给浏览器
        {
            if (!Program.IsAt(e.Uri, Program.Port) && !e.Uri.StartsWith("about:"))
            {
                e.Cancel = true;
                Open(e.Uri);
            }
        };
        core.DocumentTitleChanged += (s, e) => { };
        _web.Source = new Uri(Program.Url);
    }

    static void Open(string uri)
    {
        if (!uri.StartsWith("https://") && !uri.StartsWith("http://")) return;
        try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true }); } catch { }
    }
}
