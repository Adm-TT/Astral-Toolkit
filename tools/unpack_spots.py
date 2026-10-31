"""解包：星系里能量子过去的挖矿点（2026-10-27）。读解开的星系物件容器（<系>system.xml，StarBreaker 取出、解压）
和 DataCore 的星图记录，算出每个点的星系坐标（按父容器的位置和旋转一层层累加）和汉化名，输出 data/mining_spots.json。
用法：python tools/unpack_spots.py <星图记录目录 records/starmap/pu> <pyrosystem.xml> <nyxsystem.xml> <输出 json>
只读游戏导出的文件"""

import json
import math  # noqa: F401
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def qrot(q, v):
    w, x, y, z = q
    p = qmul(qmul(q, (0.0, *v)), (w, -x, -y, -z))
    return p[1:]


def placements(xml_path):
    """[(entityName, 星系坐标(米), starMapRecord, 物件容器文件名)]"""
    root = ET.parse(xml_path).getroot()
    out = []

    def walk(el, base, rot):
        for ch in el.findall("./ChildObjectContainers/Child"):
            pos = tuple(float(v) for v in (ch.get("pos") or "0,0,0").split(","))
            r = tuple(float(v) for v in (ch.get("rot") or "1,0,0,0").split(","))
            off = qrot(rot, pos)
            g = tuple(base[i] + off[i] for i in range(3))
            out.append(
                (
                    ch.get("entityName") or "",
                    g,
                    (ch.get("starMapRecord") or "").lower(),
                    (ch.get("name") or "").split("/")[-1],
                )
            )
            walk(ch, g, qmul(rot, r))

    walk(root, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
    return out


def starmap_records(starmap_dir):
    """记录 GUID → {name 本地化键, qt 能不能量子, hide 星图里藏不藏, rec 记录名}"""
    out = {}
    for f in Path(starmap_dir).rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        v = d.get("_RecordValue_") or {}
        if v.get("_Type_") != "StarMapObject":
            continue
        out[d["_RecordId_"].lower()] = {
            "key": (v.get("name") or "").lstrip("@").lower(),
            "qt": bool(v.get("quantumTravelData")),
            "hide": bool(v.get("hideInStarmap")),
            "rec": d["_RecordName_"].split(".", 1)[-1],
        }
    return out


# 物件容器 → 刷矿表（2026-10-27 解 socpak 时按刷矿表 GUID 找到的引用）
DEEP = "Deep Space Asteroids"  # 刷矿表 hpp_pyro_deepspaceasteroids：派罗的「小行星群」、远矿站，尼克斯的 tsg 气云
PRESET_OF = [
    (r"^cluster_modular_warm_\d+|^ab_mine_pyro_cloud|^tsg_gascloud", DEEP),
    (r"^akirocluster", "Akiro Cluster"),
]


def build(starmap_dir, systems):
    from sc_mining.update.localization import read_ini

    raw = {k.lower(): v for k, v in read_ini().items()}
    ini = {k: v.split("\\n")[0].strip() for k, v in raw.items()}
    recs = starmap_records(starmap_dir)
    spots = []
    for system, xml_path in systems:
        for ent, g, rec, oc in placements(xml_path):
            r = recs.get(rec)
            if not r or not r["qt"] or r["hide"]:
                continue  # 星图里看不到、不能量子的不要
            area = next((a for pat, a in PRESET_OF if re.search(pat, oc, re.I)), None)
            kind = (
                "cluster"
                if "cluster_modular" in oc
                else "mining_base"
                if "ab_mine" in oc
                else "cloud"
                if "gascloud" in oc
                else "transit"
                if "transitpoint" in ent.lower()
                else "station"
                if re.search(r"social|rockcracker|rckcrk|breaker", ent + oc, re.I)
                else ""
            )
            if not area and not kind:
                continue
            zh = re.sub(
                r"\s*[（(][^（）()]*[A-Za-z][^（）()]*[）)]\s*$",
                "",
                ini.get(r["key"], ""),
            ).strip()
            lines = raw.get(r["key"], "").split("\\n")
            m = re.search(r"([A-Z]{3}-\d{3})$", ent)
            en = (
                (lines[1].strip() if len(lines) > 1 else "")
                or (f"Cluster {m.group(1)}" if m and kind == "cluster" else "")
                or re.sub(r"[_]+", " ", r["rec"])
            )  # 英文名：汉化包第二行的英文 → 星团代号 → 星图记录名
            spots.append(
                {
                    "id": ent,
                    "sys": system,
                    "zh": zh,
                    "en": en,
                    "kind": kind,
                    "area": area,
                    "x": round(g[0], 1),
                    "y": round(g[1], 1),
                    "z": round(g[2], 1),
                }
            )
    return spots


if __name__ == "__main__":
    starmap_dir, pyro_xml, nyx_xml, out = sys.argv[1:5]
    spots = build(starmap_dir, [("Pyro", pyro_xml), ("Nyx", nyx_xml)])
    kinds = {}
    for s in spots:
        kinds[(s["sys"], s["kind"])] = kinds.get((s["sys"], s["kind"]), 0) + 1
    if not any(k == ("Pyro", "cluster") for k in kinds):
        print("❌ 没找到派罗小行星群，不写文件", kinds)
        sys.exit(1)
    Path(out).write_text(
        json.dumps(spots, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"✅ 挖矿点 {len(spots)} 个：", kinds)
