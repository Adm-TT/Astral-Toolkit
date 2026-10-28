"""用户设置（settings.json，放在程序外层，更新程序不会覆盖）"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from .paths import USER
FILE = USER / "settings.json"

DEFAULTS = {
    "admin": None,              # True = 每次都用管理员身份打开；False = 不用；None = 还没问过
    "anti_afk": False,          # 防挂机（2026-10-27 老大：比较敏感，默认关、放到设置页最下面；已经开着的保持原样）
    "afk_seconds": 200,         # 多少秒没操作游戏就动一下（再加 1~30 秒随机，最晚约 3.8 分钟）。1.6.70 用户定默认 200
                                # 实测（2026-10-21 游戏日志）：没操作约 5 分钟就会被踢，留一半余量
    "afk_v3": False,            # 已经把旧版太长的防挂机时间改过一次
    "afk_v4": False,            # 已经把旧默认 120 秒改成新默认 200 秒（只改一次）
    "keys_v5": False,           # 已经把老玩家的「记录路标」「一键定位」热键清掉（只清一次，2026-10-27 用户定）
    "autorun": False,           # 双击 W 自动跑（同上，默认关）
    "autorun_sprint": True,     # 自动跑时同时按住 Shift（冲刺）
    "double_tap_ms": 250,       # 两次按 W 间隔多短算双击
    "game_log": None,           # 游戏日志 Game.log 的位置（自动找到后记下）
    "trade_capture_key": "F8",  # 交易界面里截图入库的热键（F1~F12）
    "mark_key": "",             # 记录路标：默认不绑（2026-10-27 用户定：玩家自己输 /showlocation，AT 盯剪贴板接住）
    "halo_qd": "Atlas (S1)",    # 小行星带导航：量子引擎（算安全窗口几秒）
    "fix_key": "",              # 一键定位：默认不绑（同上；导航、小行星带改成直接读右上角）
    "report_key": "F10",        # 问题反馈：识别不到 / 认错了，按一下把当时的截图和数据存下来            # 太空导航：一键定位（替你输 /showlocation）
    "live_key": "F5",           # 采矿助手开关（开着时 120 秒没看到扫描面板、也没认到信号就自动关）
    "count_key": "F6",          # 盘点开关
    "ore_key": "",              # 原矿记录：游戏里按这个键记下当前这块矿和坐标；默认不设，设置页自己选
    "stock_mode": None,         # 库存页：simple（简易）/ pro（经营）；None = 还没定（老用户有库存记录直接经营，新用户第一次打开问一次）
    "hud_scale": 1.0,           # 悬浮窗大小：0.5 / 0.75 / 1（1 = 按屏幕高度算的标准大小；2026-10-26 用户定，不再放大）
    "hud_plate": 0.72,          # 悬浮窗底板不透明度（字一直是不透明的）
    "hud_theme": "默认",         # 悬浮窗配色：默认 / 蓝金 / 浅色（2026-10-27）
    "theme": "dark",            # 窗口外观：dark 深色 / light 浅色（2026-10-25 AT 品牌配色）
    "ata": True,                # 窗口里显示阿塔（助手）
    "update_online": True,      # 启动时到网上检查新版本（只读一个小文件；下载要玩家点）
    "train_upload": True,       # 帮助改进识别：认字的错题（一行字的小截图 + 正确答案）发给作者训练（2026-10-27 老大定）
    "feedback_upload": True,    # 问题反馈存好后自动发给作者（2026-10-27 老大定，设置页能关）
    "legacy_checked": False,    # 安装版第一次打开时找过旧版天枢、问过要不要导入（1.0.1）
    "nav_marker": True,         # 导航时在游戏画面上画目标记号（画面外贴边画箭头）和瞄准环（2026-10-27）
    "fov_axis": "v",            # 右上角 FOV 是上下（v）还是左右（h）的视角：记号位置不对时改这个
    "nav_mode": "auto",         # 导航方式：auto / ground = 实时读右上角；space = 手动定位（只用 /showlocation）
    "live_on": False,           # 原矿扫描开着没有：天枢重启、一键升级后自动接着扫           # 游戏里按这个键：把当前位置记成路标（要开着右上角调试信息）
    "agreed": False,            # 第一次打开时确认过「本软件是免费软件」
    "mining_ship": None,        # 原矿扫描按哪条船的配置算：mole / prospector / golem；None = 还没选（窗口会先问）
    "mining_loadouts": {},      # 自己改过的配置 {船: {"heads": [[矿头, [模组…]], …], "crew": 几人}}；没改过的用默认
}


AFK_MAX = 240                   # 防挂机间隔上限（秒）：游戏约 5 分钟踢人，加上随机的 30 秒也要留余量


def load():
    with _LOCK:                                   # 迁移时的读-改-写也要连着（老大审查 2026-10-28：和 update 交错会把新设置写回旧的）
        return _load()


def _load():
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except OSError:                               # 被别的进程占着 / 杀毒软件在扫：这次用默认，文件别动，也别把默认值写回去
        data = {}
        _unread.flag = True
    except ValueError:                            # 真的是坏 JSON：留个副本再回默认，别悄悄覆盖（2026-10-28 整体审查）
        data = {}
        try:
            FILE.replace(FILE.with_suffix(".json.bad"))
        except OSError:
            pass
    if not isinstance(data, dict):
        data = {}
    cfg = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    try:
        cfg["afk_seconds"] = int(cfg["afk_seconds"])
    except (TypeError, ValueError):               # 手改坏了的设置文件：别每次启动都崩（细查 2026-10-28）
        cfg["afk_seconds"] = DEFAULTS["afk_seconds"]
    if data and not cfg["afk_v3"]:
        # 以前以为 15 分钟才踢（默认 690 秒），实际约 5 分钟：超过 4 分钟的一律改回新默认（只改一次）
        if cfg["afk_seconds"] > AFK_MAX:
            cfg["afk_seconds"] = DEFAULTS["afk_seconds"]
        cfg["afk_v3"] = True
        changed = True
    else:
        changed = False
    if data and not cfg["afk_v4"]:
        # 1.6.70：默认从 120 改成 200 秒。还停在旧默认 120 的改成 200（自己改过别的数的不动）
        if cfg["afk_seconds"] == 120:
            cfg["afk_seconds"] = DEFAULTS["afk_seconds"]
        cfg["afk_v4"] = True
        changed = True
    if data and not cfg["keys_v5"]:
        # 1.0.5：/showlocation 只在必要时用，F7、F9 空出来给玩家（老玩家存着的也清掉；想用的自己去设置里绑回）
        cfg["mark_key"] = cfg["fix_key"] = ""
        if cfg.get("nav_mode") == "space":       # 以前选了「太空导航」（只用 /showlocation）的改回实时
            cfg["nav_mode"] = "auto"
        cfg["keys_v5"] = True
        changed = True
    if changed:
        try:
            save(cfg)
        except Exception:
            pass
    return cfg


_LOCK = __import__("threading").RLock()      # 窗口线程、日志线程、识别线程都会改设置：读-改-写要连在一起（2026-10-28 整体审查）


def save(cfg):
    from .paths import write_json
    with _LOCK:
        write_json(FILE, cfg, indent=1)


_unread = __import__("threading").local()


def update(**kw):
    with _LOCK:
        _unread.flag = False
        cfg = load()
        cfg.update(kw)
        if getattr(_unread, "flag", False):      # 刚才没读到真实设置：只在内存里改，不落盘（否则会把默认值写回去，清掉玩家设置）
            print("设置文件暂时读不到，这次改动没有保存")
            return cfg
        save(cfg)
        return cfg
