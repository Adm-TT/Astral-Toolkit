"""用户设置（settings.json，放在程序外层，更新程序不会覆盖）"""

import copy
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from .paths import USER  # noqa: E402

FILE = USER / "settings.json"

DEFAULTS = {
    "admin": None,  # True = 每次都用管理员身份打开；False = 不用；None = 还没问过
    "keys_v5": False,  # 已经把老玩家的「记录路标」「一键定位」热键清掉（只清一次，2026-10-27 用户定）
    "game_log": None,  # 游戏日志 Game.log 的位置（自动找到后记下）
    "trade_capture_key": "F8",  # 交易界面里截图入库的热键（F1~F12）
    "mark_key": "",  # 记录路标：默认不绑（2026-10-27 用户定：玩家自己输 /showlocation，AT 盯剪贴板接住）
    "halo_qd": "Atlas (S1)",  # 小行星带导航：量子引擎（算安全窗口几秒）
    "fix_key": "",  # 一键定位：默认不绑（同上；导航、小行星带改成直接读右上角）
    "report_key": "F10",  # 问题反馈：识别不到 / 认错了，按一下把当时的截图和数据存下来
    "live_key": "F5",  # 采矿助手开关（自动关闭时间见 mining_idle_close）
    "mining_idle_close": 120,  # 采矿助手所有通道都没看到时，多少秒后自动关闭（30–1800）
    "mining_focus": None,  # 悬浮窗关注的矿物英文名列表；None = 全部，[] = 都不显示
    "count_key": "F6",  # 盘点开关
    "ore_key": "",  # 原矿记录：游戏里按这个键记下当前这块矿和坐标；默认不设，设置页自己选
    "stock_mode": None,  # 库存页：simple（简易）/ pro（经营）；None = 还没定（老用户有库存记录直接经营，新用户第一次打开问一次）
    "hud_scale": 1.0,  # 悬浮窗大小：0.5 / 0.75 / 1（1 = 按屏幕高度算的标准大小；2026-10-26 用户定，不再放大）
    "hud_plate": 0.72,  # 悬浮窗底板不透明度（字一直是不透明的）
    "hud_theme": "默认",  # 悬浮窗配色：默认 / 蓝金 / 浅色（2026-10-27）
    "theme": "dark",  # 窗口外观：dark 深色 / light 浅色（2026-10-25 AT 品牌配色）
    "ata": True,  # 窗口里显示阿塔（助手）
    "update_online": True,  # 启动时到网上检查新版本（只读一个小文件；下载要玩家点）
    "ocr_device": "cpu",  # 文字识别设备：cpu (处理器，默认) / gpu (显卡 DirectML：F8 每次约快 0.2 秒，但认过一次字 AT 就多占两三百 MB 内存；2026-11-08 老大定默认处理器)
    "always_use_gpu": False,  # 兼容旧配置项
    "ocr_v2": True,  # 识别默认改处理器那次的一次性迁移做过了：老版本存的设置文件里没有这一项（见 _load）
    "debug_mode": False,  # 调试模式：开着时 F8/盘点每一步的裁切、耗时、停因写进 logs/debug_日期.log（只进文件、不进窗口运行日志，2026-11-08 老大定）、在 userdata/shots/debug/ 落识别区域调试图；导航读右上角的诊断（logs/di_log.txt、shots/di_fail、记号收起原因）也只在开着时写（NV-B5）。仅本机，不上传；默认关
    "train_upload": True,  # 帮助改进识别：认字的错题（一行字的小截图 + 正确答案）发给作者训练（2026-10-27 负责人定）
    "feedback_upload": True,  # 问题反馈存好后自动发给作者（2026-10-27 负责人定，设置页能关）
    "nav_marker": True,  # 导航时在游戏画面上画目标记号（画面外贴边画箭头）和瞄准环（2026-10-27）
    "fov_axis": "v",  # 右上角 FOV 是上下（v）还是左右（h）的视角：记号位置不对时改这个
    "nav_mode": "auto",  # 导航方式：auto / ground = 实时读右上角；space = 手动定位（只用 /showlocation）
    "nav_fps": 5,  # 导航帧数：导航时每秒读几次右上角、刷新几次记号（5–30；越高越跟手、越占 CPU；老大 11-05 定，60 档实测只读到约 31 次，当晚改成 5–30）
    "live_on": False,  # 原矿扫描开着没有：AT 重启、一键升级后自动接着扫           # 游戏里按这个键：把当前位置记成路标（要开着右上角调试信息）
    "agreed": False,  # 第一次打开时确认过「本软件是免费软件」
    "mining_ship": None,  # 原矿扫描按哪条船的配置算：mole / prospector / golem；None = 还没选（窗口会先问）
    "mining_loadouts": {},  # 自己改过的配置 {船: {"heads": [[矿头, [模组…]], …], "crew": 几人}}；没改过的用默认
    # 带了哪些手持工具（列表，键见 mining/data.GADGETS）；None = 没设过、全都带（老大 11-04 定）。
    # 以前漏了这一项：存了也读不到，下次存别的设置时还会被抹掉（s1 第三轮复查）
    "mining_gadgets": None,
}


NAV_FPS = (5, 30)  # 导航帧数能选的范围（老大 11-05 定 5–60，实机后改 5–30）


def nav_fps(value):
    """导航帧数：取整、限在 5–30；不像数字（手改坏了、没设）按 5"""
    lo, hi = NAV_FPS
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return lo
    return max(lo, min(hi, v))


def mining_idle_seconds(value):
    """采矿助手自动关闭秒数：30–1800；坏值按默认 120。"""
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 120
    return max(30, min(1800, seconds))


# 每个设置文件这个进程最后一次读到的设置（暂时读不到时先用它）；迁移存盘失败过的设置文件（不再每次读都重试）
_LAST_GOOD: dict[str, dict] = {}
_SAVE_FAILED: set[str] = set()


def load():
    with (
        _LOCK
    ):  # 迁移时的读-改-写也要连着（审查 2026-10-28：和 update 交错会把新设置写回旧的）
        return _load()


def _load():
    key = str(FILE)
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except OSError:
        # 被别的进程占着 / 杀毒软件在扫：文件别动，也别把默认值写回去。这个进程读到过就先用上次读到的，
        # 别让窗口、悬浮窗、识别一下子退回默认值（窗口闪回深色、设置页显示默认值、按默认值查撞键；s1 第二轮复查）
        _unread.flag = True
        if key in _LAST_GOOD:
            return copy.deepcopy(_LAST_GOOD[key])
        data = {}
    except ValueError:
        # 真的是坏 JSON：留个副本再回默认，别悄悄覆盖（2026-10-28 整体审查）
        data = {}
        try:
            FILE.replace(FILE.with_suffix(".json.bad"))
        except OSError:
            pass
    if not isinstance(data, dict):
        data = {}
    cfg = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    changed = False
    if data and not cfg["keys_v5"]:
        # 1.0.5：/showlocation 只在必要时用，F7、F9 空出来给玩家（老玩家存着的也清掉；想用的自己去设置里绑回）
        cfg["mark_key"] = cfg["fix_key"] = ""
        if (
            cfg.get("nav_mode") == "space"
        ):  # 以前选了「太空导航」（只用 /showlocation）的改回实时
            cfg["nav_mode"] = "auto"
        cfg["keys_v5"] = True
        changed = True
    if data and "ocr_v2" not in data:
        # 识别默认改处理器（显卡认过一次字 AT 就多占两三百 MB 内存）。以前默认显卡、存设置时连它一起写进了文件，
        # 分不出谁是自己选的：老文件统一改一次处理器。这一项按「文件里有没有」认，新存的文件都带着它，
        # 之后玩家在设置页切回显卡就一直是显卡（2026-11-08 老大定）
        cfg["ocr_device"] = "cpu"
        cfg["always_use_gpu"] = False
        cfg["ocr_v2"] = True
        changed = True
    if changed and key not in _SAVE_FAILED:
        try:
            save(cfg)
        except Exception:
            # 一直写不进去（比如设置文件带了只读）：这个进程里不再每次读都重试——每次要卡约 0.25 秒，读设置的地方很多；
            # 迁移只在内存里做，下次改设置存盘时连它一起存上（s1 第二轮复查）
            _SAVE_FAILED.add(key)
    _LAST_GOOD[key] = copy.deepcopy(cfg)
    return cfg


_LOCK = (
    __import__("threading").RLock()
)  # 窗口线程、日志线程、识别线程都会改设置：读-改-写要连在一起（2026-10-28 整体审查）


# 本进程存过几次设置（save 每存一次加 1）：View 看它变了才重读文件（NV-B5）
_SAVED = [0]


def save(cfg):
    from .paths import write_json

    with _LOCK:
        write_json(FILE, cfg, indent=1)
        _SAVED[0] += 1
        # 刚存上的就是最新的：存完马上读不到（杀毒、同步软件常在文件刚改完时去扫）也给刚存的，别闪回改之前的
        # （窗口外观、识别设备；s1 第三轮复查）。和读文件时一样只留认得的项
        _LAST_GOOD[str(FILE)] = copy.deepcopy(
            {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}
        )


_unread = __import__("threading").local()


def update(**kw):
    with _LOCK:
        _unread.flag = False
        cfg = load()
        cfg.update(kw)
        if getattr(
            _unread, "flag", False
        ):  # 刚才没读到真实设置：只在内存里改，不落盘（否则会把默认值写回去，清掉玩家设置）
            print("设置文件暂时读不到，这次改动没有保存")
            return cfg
        save(cfg)
        return cfg


class NotSaved(OSError):
    """这次改动没存上：设置文件暂时读不到（被杀毒、同步软件占着）"""


_NOT_READ = "设置文件暂时读不到（可能被杀毒或同步软件占着），这次没存上，再点一次"
NOT_WRITTEN = "设置文件写不进去（可能被杀毒或同步软件占着），这次没存上，再点一次"


def update_checked(**kw):
    """和 update 一样，但设置文件暂时读不到、这次没存上时抛 NotSaved：设置页要告诉玩家再点一次
    （以前只在控制台打一行，设置页显示改了其实没存上）。写不进去照旧抛原来的 OSError"""
    with _LOCK:
        _unread.flag = False
        cfg = update(**kw)
        if getattr(_unread, "flag", False):
            raise NotSaved(_NOT_READ)
        return cfg


def load_checked():
    """和 load 一样，但设置文件暂时读不到时抛 NotSaved（这时拿到的是这次运行上次读到 / 存上的，没有就是默认值，
    不一定是文件里现在的）：改热键前查撞键不能拿它查，会误报「已用于…」（s1 复查）"""
    with _LOCK:
        _unread.flag = False
        cfg = load()
        if getattr(_unread, "flag", False):
            raise NotSaved(_NOT_READ)
        return cfg


class View:
    """每帧都要看的设置（调试模式、导航记号……）：内存里留一份，平时不读盘（NV-B5）。

    本进程存过设置以后，下一次取才重读文件：设置页保存、settings.update 都走 save，所以一改马上生效。
    这次没读到真实设置（文件被别的程序占着）：先用 load 给的（这次运行上次读到 / 存上的，没有就是默认值），RETRY 秒后再读。
    手改 settings.json 不会马上生效：重开 AT，或在设置页随便改一项。
    取到的字典是大家共用的，只读，别改它。"""

    RETRY = 1.0

    def __init__(self):
        # 上次读文件时的 _SAVED[0]；None = 还没读过 / 上次没读到真实设置
        self._seen = None
        self._retry_at = 0.0
        self._cfg = dict(DEFAULTS)

    def all(self):
        """整份设置（共用的字典，只读）"""
        if _SAVED[0] == self._seen:
            return self._cfg
        now = time.monotonic()
        if self._seen is None and now < self._retry_at:
            return self._cfg
        with _LOCK:
            saved = _SAVED[0]
            _unread.flag = False
            cfg = load()
            unread = getattr(_unread, "flag", False)
        self._cfg = cfg
        if unread:
            self._seen = None
            self._retry_at = now + self.RETRY
        else:
            self._seen = saved
        return cfg

    def get(self, key, default=None):
        return self.all().get(key, default)
