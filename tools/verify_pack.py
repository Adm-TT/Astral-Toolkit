# 验证 Gitee / GitHub 上的数据包：下载到临时目录、核对、读一件掉落明细（不碰开发目录的 data）
import sys, time, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sc_mining import data_pack as P, loot, update_check as U
for which in ("Gitee", "GitHub"):
    tmp = Path(tempfile.mkdtemp(prefix=f"at_verify_{which}_"))
    P.DATA = tmp; P.STAMP = tmp / "data_pack.json"; loot.DETAILS = tmp / "loot_details.zip"; loot.close_bundle()
    keep = U.GITHUB if which == "GitHub" else ""
    g0, h0 = U.GITEE, U.GITHUB
    if which == "GitHub":
        U.GITEE = ""
    info, err = P.fetch()
    if which == "GitHub":
        # 只走 GitHub：下载地址也只留 GitHub 的
        if info:
            info["urls"] = [u for u in info["urls"] if "github" in u]
            if info.get("loot"): info["loot"]["urls"] = [u for u in info["loot"]["urls"] if "github" in u]
    print(f"== {which}：data.json", "读取成功" if info else f"失败 {err}")
    if info:
        t = time.time()
        tmpz = tmp / info["file"]
        try:
            P._download(info, tmpz, print); n = P.install(tmpz, info)
            print(f"   数据包 {info['version']}：下载+校验+安装 {n} 个文件，{time.time()-t:.1f} 秒")
            t = time.time(); P._update_loot(info, print)
            print(f"   掉落明细整包：{loot.details_version()}，{time.time()-t:.1f} 秒")
            idx = json.loads(open(Path(__file__).resolve().parent.parent / "data" / "loot_index.json", encoding="utf-8").read())
            u = idx["rows"][0][0]
            print(f"   从整包读一件掉落明细（{idx['rows'][0][5] or idx['rows'][0][1]}）：", "成功" if loot._from_zip(u, idx["version"]) else "失败")
        except Exception as e:
            print("   出错：", e)
    U.GITEE, U.GITHUB = g0, h0
    loot.close_bundle()
