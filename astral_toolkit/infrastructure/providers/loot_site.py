"""scl.miao.network（从游戏文件解析的掉落表）的下载适配（目录迁移 Q3 从 crafting/loot.py 拆出来）：
站点当前的数据版本、某个版本的清单和物品索引、单件物品的掉落明细。只管发请求、解析响应，出错原样抛给调用方；
存哪、什么时候下、下不到怎么办由调用方定（掉落数据更新 update/loot.py：只有作者发布数据包时用，玩家端不联这个站，2026-11-13）。
core.net.read 在函数里现取（测试和行为基线换它就能断网）。"""

import json
import re
import urllib.request

BASE = "https://scl.miao.network/d/"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://scl.miao.network/",
}


def get_json(url, timeout=60):
    """GET 一个 JSON（带上面的浏览器 UA）"""
    from ...core.net import read

    return json.loads(
        read(urllib.request.Request(url, headers=UA), timeout=timeout).decode("utf-8")
    )


def latest_version():
    """站点当前的数据版本（例如 4.10.2LIVE）：从首页脚本里的 manifest 地址取；取不到返回 None（调用方用本机索引里的）"""
    try:
        from ...core.net import read

        html = read(
            urllib.request.Request("https://scl.miao.network/", headers=UA), timeout=30
        ).decode("utf-8", "replace")
        m = re.search(r"/d/([0-9.]+(?:LIVE|PTU)?)/", html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def manifest(version):
    """某个数据版本的清单（{"version": …}）"""
    return get_json(f"{BASE}{version}/manifest.json")


def search_rows(version):
    """某个数据版本的物品索引 search.json 的行（约 1.5 MB，1.3 万项，中英文名都有）"""
    return get_json(f"{BASE}{version}/search.json", timeout=120)


def item_detail_raw(version, uuid):
    """作者发布数据用：单件物品掉落明细的原始字节，UA 后面注明是 AT 镜像数据；HTTP 错误（限流 429、拒绝 403）原样抛"""
    from ...core.net import read

    ua = {**UA, "User-Agent": UA["User-Agent"] + " AT-Astral-Toolkit/data-mirror"}
    return read(
        urllib.request.Request(f"{BASE}{version}/q/{uuid}.json", headers=ua),
        timeout=30,
    )
