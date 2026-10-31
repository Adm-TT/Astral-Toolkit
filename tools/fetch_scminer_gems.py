"""重新抓 SCMiner 的地面小矿数据（ROC 车矿、车矿·手采、矿洞手采），重写 sc_mining/gems.py

用法（在 sc_mining 文件夹里）：.venv\\Scripts\\python.exe -X utf8 tools\\fetch_scminer_gems.py
每种矿读 scminer.rocks/data/mineral-directory/<矿名> 详情页：类型、单块信号、终端价、不稳定性、抗性、全部地点和概率。
联网失败、页面认不出来的矿保留 gems.py 里原来的数据，不会把文件写坏。
"""

import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "sc_mining" / "mining" / "gems.py"
URL = "https://scminer.rocks/data/mineral-directory/{}"
NAMES = [
    "Janalite",
    "Hadanite",
    "Feynmaline",
    "Aphorite",
    "Glacosite",
    "Dolivine",
    "Beradom",
    "Jaclium",
    "Sadaryx",
    "Saldynium",
]
KIND = {
    "ROC Vehicle Mining": "车矿",
    "Dual: ROC Vehicle & Hand Tool": "车矿·手采",
    "FPS Hand Mining": "矿洞手采",
}
LEVEL = {
    "very low": "很低",
    "low": "低",
    "medium": "中",
    "high": "高",
    "very high": "很高",
}


class _Text(HTMLParser):
    """网页里所有文字块，用 | 连起来（脚本、样式里的不要）"""

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        t = data.strip()
        if t and not self.skip:
            self.parts.append(t)


def page_text(html):
    p = _Text()
    p.feed(html)
    return "|".join(p.parts)


def parse(s):
    """详情页文字 → dict(kind, rs, price, inst, res, locs)；认不出来返回 None"""
    head = s[s.find("PATCH|") :].split("|")[2:10]
    kind = next(
        (v for k, v in KIND.items() if any(h.startswith(k) for h in head)), None
    )
    rs = re.search(r"Radar Sig \(⊙\)\|([\d,]+)", s, re.I)
    price = re.search(r"Terminal Value\|Live NPC\|([\d,]+|TBD)", s, re.I)
    level = lambda lab: (
        (m := re.search(lab + r"\|([A-Za-z ]+)\|", s, re.I))
        and LEVEL.get(m.group(1).strip().lower())
    )  # noqa: E731
    locs = [
        (n, sys_.title(), float(p))
        for n, sys_, p in re.findall(
            r"\|([^|]+)\|System:\|([a-z]+)\|([\d.]+)\|%\|Abundance", s, re.I
        )
        if float(p) > 0
    ]
    if not (kind and rs and locs):
        return None
    pv = price.group(1).replace(",", "") if price else ""
    return dict(
        kind=kind,
        rs=int(rs.group(1).replace(",", "")),
        price=int(pv) if pv.isdigit() else None,
        inst=level("Instability Level"),
        res=level("Fracture Resistance"),
        locs=locs,
    )


def write(gems, day):
    lines = []
    for en, g in gems.items():
        locs = ", ".join(f'("{n}", "{s}", {p})' for n, s, p in g["locs"])
        lines.append(
            f'    "{en}": dict(kind="{g["kind"]}", rs={g["rs"]}, price={g["price"]}, '
            f'inst="{g["inst"]}", res="{g["res"]}",\n{" " * 17}locs=[{locs}]),'
        )
    head = OUT.read_text(encoding="utf-8").split("GEMS = {")[0]
    head = re.sub(r"\d{4}-\d{2}-\d{2} 抓取", f"{day} 抓取", head)
    OUT.write_text(
        head + "GEMS = {\n" + "\n".join(lines) + "\n}\n", encoding="utf-8", newline="\n"
    )


def main():
    import time
    from sc_mining.mining.gems import GEMS

    out, bad = dict(GEMS), []
    for en in NAMES:
        try:
            req = urllib.request.Request(
                URL.format(en.lower()), headers={"User-Agent": "Mozilla/5.0 Dubhe"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                g = parse(page_text(r.read().decode("utf-8", "replace")))
        except Exception as e:
            g, why = None, f"{type(e).__name__}: {e}"
        else:
            why = "页面认不出来"
        if g:
            out[en] = g
            print(
                f"{en}：{g['kind']} 信号 {g['rs']:,} 价格 {g['price']} 地点 {len(g['locs'])} 个"
            )
        else:
            bad.append(en)
            print(f"{en}：没抓到（{why}），保留原来的数据")
    write(out, time.strftime("%Y-%m-%d"))
    print(f"写好 {OUT}" + (f"；{len(bad)} 种没抓到：{'、'.join(bad)}" if bad else ""))


if __name__ == "__main__":
    main()
