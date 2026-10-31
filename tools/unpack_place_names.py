"""星图地名补中文（2026-10-27）：data/places_zh.json 只收了汉化包里「中文 (English)」这种双语写法的地名，
「采矿基地 #IGB-FXW」「小行星群 CAJ-445」「HDMS-安德森」这种中文里不带英文的没收进来。
用解包出来的英文包对上：同一个键英文是 X、中文是 Y → X 的中文就是 Y（汉化组的翻译）。只收星图里用得到的名字。
→ data/places_extra_zh.json：{英文名去符号小写: 中文名}
用法：python tools/unpack_place_names.py"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sc_mining.update.localization import read_ini  # noqa: E402

EN_INI = Path(r"E:\Game3\unpack\p4k_out\Data\Localization\english\global.ini")
ZH_INI = ROOT / "data" / "loc" / "global_zh.ini"
OUT = ROOT / "data" / "places_extra_zh.json"
CJK = re.compile(r"[\u4e00-\u9fff]")


# 汉化包里也没有的：自己翻（用到的专有名词按汉化组：克莱舍尔、标枪、布拉什伍德、哈特莫尔、索兰奇、行政中心、莉瑞雅），
# 都写进 翻译对照\自译对照_全部地名.csv 给老大改。纯内部编号（RastarLocationEntity-001、ObjectContainer-003）保持英文
SELF = {
    "Velakar Spawn Area #001": "瓦拉卡出没区 #001",
    "Velakar Spawn Area #002": "瓦拉卡出没区 #002",
    "Attritus Borehole": "Attritus 钻孔",
    "Lamina Borehole": "Lamina 钻孔",
    "Lamina GAP": "Lamina 地面激活平台",
    "Klescher Borehole A": "克莱舍尔钻孔 A",
    "Klescher Borehole B": "克莱舍尔钻孔 B",
    "Klescher, Container #009": "克莱舍尔 集装箱 #009",
    "Finn's Foley Hidden Tent under a rock": "芬恩·福利藏在石头下的帐篷",
    "Abandoned Hab Entry (GrimHex)": "废弃居住舱入口（六角湾）",
    "Bennyhenge": "本尼巨石阵",
    "Lakesite Chairs": "湖边的椅子",
    "Mountainsite Chairs": "山边的椅子",
    "Painted Rooftop (missing) - Tears of Fire": "彩绘屋顶 - 火之泪",
    "Sketto Rock": "Sketto 岩石",
    "The Great Wall": "长城",
    "XMAS Campfire": "圣诞篝火",
    "Citizencon 2953 Location of cows and homestead": "公民大会 2953 奶牛和农庄",
    "Adair's Retreal": "阿代尔隐居处",
    "Rupture OLP": "Rupture 轨道激光平台",
    "Rupture PAF I": "Rupture 行星校准设施 I",
    "Rupture PAF II": "Rupture 行星校准设施 II",
    "Rupture PAF III": "Rupture 行星校准设施 III",
    "Orison - Admin Center Platform": "奥里森 - 行政中心平台",
    "Orison - Brushwood Platform": "奥里森 - 布拉什伍德平台",
    "Orison - Hartmoore Platform": "奥里森 - 哈特莫尔平台",
    "Orison - Solanki Platform": "奥里森 - 索兰奇平台",
    "Operations Depot Lyria": "运营仓库 莉瑞雅",
    "Samson & Son's Salvage Yard (old)": "萨姆森父子打捞场（旧）",
    "Caterpillar Wreck N11b": "毛虫残骸 N11b",
    "Derelict Cutlass (CS Hacking)": "弯刀残骸（CS 骇入）",
    "Javelin - UEES Flyssa": "标枪 - UEES Flyssa",
    "XGR - Snake Pit": "XGR - 蛇坑",
    "CP Betty DR2026": "检查点 Betty DR2026",
    "HHL 2020 - Crater (old)": "HHL 2020 - 陨石坑（旧）",
    "HHL 2021 - Civilian Crater": "HHL 2021 - 平民陨石坑",
    "New Vega - Hill Climb Mountain": "New Vega - 爬坡山",
    "Stanton7 - Race1, CP1": "Stanton7 - 第 1 赛 检查点 1",
    "Stanton7 - Race1, CP2": "Stanton7 - 第 1 赛 检查点 2",
    "Stanton7 - Race2, CP1, Calhoun Pass": "Stanton7 - 第 2 赛 检查点 1 卡尔霍恩山口",
    "Stanton7 - Race3, CP1": "Stanton7 - 第 3 赛 检查点 1",
    "Stanton7 - Race3, CP2": "Stanton7 - 第 3 赛 检查点 2",
    "Stanton7 - Race3, Finish": "Stanton7 - 第 3 赛 终点",
    "Stanton7 - Race3, Start": "Stanton7 - 第 3 赛 起点",
    "Tour de Verse - Stage 3 CP1": "Tour de Verse - 第 3 赛段 检查点 1",
    "Tour de Verse - Stage 3 Start": "Tour de Verse - 第 3 赛段 起点",
    "MT SecurityCenter GWS-NM3-E": "微科安保中心 GWS-NM3-E",
    "MT SecurityCenter UDB-24W-2": "微科安保中心 UDB-24W-2",
    "Test Facility Octagon (missing)": "八角测试设施",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    from sc_mining.navigation import navigate as n

    data = n.load()
    names = {norm(p["n"]): p["n"] for p in data["pois"] + data.get("points", [])}
    en = read_ini(EN_INI)
    zh = read_ini(ZH_INI)
    out, seen = {}, {}
    for k, v in en.items():
        e = v.split("\\n")[0].strip()
        key = norm(e)
        if key not in names or k.lower().endswith("desc"):
            continue
        z = (zh.get(k) or "").split("\\n")[0].strip()
        # 「罗威尔 (Lorville)」去掉英文尾巴；纯中文的括号「（旧）」留着（二审 2026-10-27）
        z = (
            re.sub(
                r"\s*[(（][^()（）\u4e00-\u9fff]*[A-Za-z][^()（）\u4e00-\u9fff]*[)）]\s*$",
                "",
                z,
            ).strip()
            if CJK.search(z)
            else ""
        )
        if not z or not CJK.search(z):
            continue
        seen.setdefault(key, set()).add(z)
        out.setdefault(key, z)
    amb = {k: v for k, v in seen.items() if len(v) > 1}
    self_rows = []
    for e, z in SELF.items():
        k = norm(e)
        if k in names and k not in out:
            out[k] = z
            self_rows.append((e, z))
    _to_csv(data, self_rows)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    still = [
        names[k]
        for k in names
        if k not in out and n.label({"n": names[k], "t": ""}) == names[k]
    ]
    print(
        f"✅ 星图地名补中文 {len(out)} 个 → {OUT}（同一个英文名有几种译法的 {len(amb)} 个，取第一个）"
    )
    print(f"   汉化包里也没有的 {len(still)} 个（按规则翻或显示英文）")


def _to_csv(data, rows):
    """自译的地名追加到 翻译对照\自译对照_全部地名.csv（已有的不重复写；追加不能再写 BOM）"""
    import csv

    f = ROOT / "翻译对照" / "自译对照_全部地名.csv"
    if not f.exists() or not rows:
        return
    have = {r[1] for r in csv.reader(f.open(encoding="utf-8-sig")) if len(r) > 1}
    from sc_mining.navigation.navigate import BODY_ZH

    body = {p["n"]: p.get("b", "") for p in data["pois"]}
    new = [(e, z) for e, z in rows if e not in have]
    with f.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        for e, z in new:
            b = body.get(e, "")
            w.writerow([f"{BODY_ZH.get(b, b)}（{b}）" if b else "", e, z, ""])
    print(f"   自译对照_全部地名.csv 加了 {len(new)} 个")


if __name__ == "__main__":
    main()
