"""关于、版本元数据、开源许可与免责声明"""

import time
import webbrowser

REFERRAL_URL = "https://www.robertsspaceindustries.com/enlist?referral=STAR-4CNY-K3YT"

# 数据来源：(名称, 网址, 提供什么)
DATA_SOURCES = (
    ("SCMiner", "https://scminer.rocks", "矿物、雷达信号、采矿地点、车矿和手采矿"),
    ("UEX", "https://uexcorp.space", "矿价、精炼站加成、商店售卖地点、玩家市场价"),
    ("SC Market", "https://scm.flowcld.com/market", "玩家市场价"),
    ("scmdb.net", "https://scmdb.net", "制造蓝图、维科洛兑换"),
    ("starmap.space", "https://starmap.space", "星图和地点坐标"),
    ("星际公民掉落查询", "https://scl.miao.network", "掉落数据"),
    (
        "Star Citizen Wiki API",
        "https://api.star-citizen.wiki",
        "物品数值、物品清单和说明",
    ),
    (
        "Star Citizen Wiki",
        "https://starcitizen.tools",
        "矿物品质分档（CC BY-SA 4.0 许可，改编使用）",
    ),
    ("erkul.games", "https://www.erkul.games", "舰船信号截面"),
    (
        "SC汉化盒子",
        "https://github.com/StarCitizenToolBox/app",
        "中文名称（及社区汉化项目）",
    ),
)

AGREE_TEXT = "本软件是免费软件"


def _version():
    from ...core.version import VERSION

    return VERSION


def _data_versions():
    from ...core import paths

    out = {}
    try:
        out["loc"] = (
            (paths.DATA / "loc" / "version.txt").read_text(encoding="utf-8").strip()
        )
    except Exception:
        out["loc"] = ""
    for key, name in (("shops", "shops.json"), ("starmap", "starmap.json")):
        p = paths.DATA / name
        out[key] = (
            time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
            if p.exists()
            else ""
        )
    try:
        from ...crafting.loot import load_index

        idx = load_index(False)
        out["loot"] = (idx or {}).get("version", "")
    except Exception:
        out["loot"] = ""
    from ...update.data_pack import local_version

    out["pack"] = (
        local_version()
    )  # 数据包版本（2026-10-26 起数据从 AT 发布的数据包更新）
    return out


def data_names_ready() -> bool:
    """本机数据包与汉化包版本戳都在（首页「未下载」都不亮），认为名字库侧数据已下载。

    不与服务器比新旧。F8 sure=False 时用来区分「没更新数据」和「汉化包里真没对上」
    （docs/superpowers/specs/2026-11-04-f8-unsure-data-hint.md）。
    """
    try:
        v = _data_versions()
        return bool(v.get("pack")) and bool(v.get("loc"))
    except Exception:
        return False


def about_info():
    """关于页：版权、数据来源"""
    return {
        "copyright": "© 2026 Adm_TT　AGPL-3.0 开源",
        "sources": [{"name": n, "url": u, "what": w} for n, u, w in DATA_SOURCES],
    }


def open_source_site(i=0):
    """关于页点数据来源：用系统默认浏览器打开（只开 DATA_SOURCES 里的网址）"""
    webbrowser.open(DATA_SOURCES[int(i)][1])
    return {"ok": True}


def third_party_licenses():
    """开源组件许可证原文（安装目录的「第三方许可.txt」，打包时由 tools/collect_licenses.py 生成）"""
    from ...core import paths

    p = paths.ROOT / "第三方许可.txt"
    try:
        return {"text": p.read_text(encoding="utf-8-sig")}
    except OSError:
        return {
            "text": "",
            "error": "未找到「第三方许可.txt」（开发目录里没有，打包时生成）",
        }


def open_referral():
    """用系统默认浏览器打开作者的星际公民邀请注册页（只能打开这一个固定网址）"""
    webbrowser.open(REFERRAL_URL)
    return {"ok": True}


def agree(text=""):
    """第一次打开：必须一字不差地输入「本软件是免费软件」才能用"""
    from ...core import settings
    from .settings import start_background
    from .status import status

    if (text or "").strip() != AGREE_TEXT:
        return {"error": f"需完整输入：{AGREE_TEXT}"}
    settings.update(agreed=True)
    start_background()
    return status()
