"""验证网上的数据包：每轮只走一个来源（data.json 和下载地址都只留这一处），下载到临时目录、核对、
装进临时目录、读一件掉落明细（不碰开发目录的 data）。有任何一轮失败退出码 1。
用法：python -X utf8 tools/verify_pack.py [AT服务器|国内镜像|Gitee|GitHub ...]（默认 AT 服务器、国内镜像；Gitee / GitHub 已不再更新）"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sc_mining.update import data_pack as P, update_check as U  # noqa: E402
from sc_mining.crafting import loot  # noqa: E402


def rounds():
    """[(名字, data.json 所在 host, 数据包下载 host)]：没配置的来源不列"""
    out = []
    if U.OWN:
        out.append(("AT服务器", U.OWN, U.OWN))
    if U.COS:
        out.append(("国内镜像", U.COS, U.COS))
    if U.GITEE:
        out.append(("Gitee", "gitee.com", "gitee.com"))
    if U.GITHUB:
        out.append(("GitHub", "raw.githubusercontent.com", "github.com"))
    return out


def _host(url):
    return url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()


def check(which, mhost, dhost):
    """只用这一个来源验证一遍；成功返回 True。临时换掉的东西在 finally 里还原"""
    tmp = Path(tempfile.mkdtemp(prefix=f"at_verify_{which}_"))
    saved = (P.DATA, P.STAMP, P.manifest_urls, U._open, loot.DETAILS)
    real_urls, real_open = P.manifest_urls, U._open
    allowed = {mhost, dhost}

    def only_open(url, timeout):  # 保险：请求别的网站直接算失败，不会悄悄走别的来源
        if _host(url) not in allowed:
            raise RuntimeError(
                f"这一轮只该请求 {'、'.join(sorted(allowed))}，却要请求 {_host(url)}"
            )
        return real_open(url, timeout)

    try:
        P.DATA, P.STAMP, loot.DETAILS = (
            tmp,
            tmp / "data_pack.json",
            tmp / "loot_details.zip",
        )
        P.manifest_urls = lambda: [(w, u) for w, u in real_urls() if _host(u) == mhost]
        U._open = only_open
        loot.close_bundle()
        info, err = P.fetch()
        if info:  # 下载地址也只留这一处
            info["urls"] = [u for u in info["urls"] if _host(u) == dhost]
            if info.get("loot"):
                info["loot"]["urls"] = [
                    u for u in info["loot"]["urls"] if _host(u) == dhost
                ]
            if not info["urls"]:
                info, err = None, f"data.json 里没有 {dhost} 的下载地址"
        print(f"== {which}：data.json", "读取成功" if info else f"失败 {err}")
        if not info:
            return False
        t = time.time()
        P._download(info, tmp / info["file"], print)
        n = P.install(tmp / info["file"], info)
        print(
            f"   数据包 {info['version']}：下载+校验+安装 {n} 个文件，{time.time() - t:.1f} 秒"
        )
        t = time.time()
        P._update_loot(info, print)
        print(f"   掉落明细整包：{loot.details_version()}，{time.time() - t:.1f} 秒")
        idx = json.loads(
            (tmp / "loot_index.json").read_text(encoding="utf-8")
        )  # 刚装进临时目录的那份
        u = idx["rows"][0][0]
        ok = bool(loot._from_zip(u, idx["version"]))
        print(
            f"   从整包读一件掉落明细（{idx['rows'][0][5] or idx['rows'][0][1]}）：",
            "成功" if ok else "失败",
        )
        return ok
    except Exception as e:
        print("   出错：", e)
        return False
    finally:
        loot.close_bundle()
        P.DATA, P.STAMP, P.manifest_urls, U._open, loot.DETAILS = saved


def main(argv):
    todo = (
        [r for r in rounds() if r[0] in argv]
        if argv
        else [r for r in rounds() if r[0] in ("AT服务器", "国内镜像")]
    )
    if not todo:
        print(f"❌ 没有要验证的来源（可选：{'、'.join(r[0] for r in rounds())}）")
        return 1
    bad = [r[0] for r in todo if not check(*r)]
    if bad:
        print(f"❌ 没通过：{'、'.join(bad)}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
