"""地面小矿：ROC 车矿、车矿和手采都行的、矿洞手采（飞船挖不了，扫描面板上没有，只看雷达信号）

数据：SCMiner 矿物目录各矿详情页（scminer.rocks/data/mineral-directory/<矿名>，4.10.2），2026-10-25 抓取。
重新抓：tools/fetch_scminer_gems.py（会重写这个文件）。
kind：车矿 = 只能 ROC 车挖；车矿·手采 = ROC 车或手持采矿工具都行；矿洞手采 = 只在矿洞里用手持工具挖
rs：单块雷达信号（一处 N 块 = rs × N）；price：交易终端每个（1 SCU = 1000 个）的 aUEC，SCMiner 没有价格的是 None
locs：(地点, 星系, 出现概率 %)，按概率从高到低，SCMiner 原值
"""

GEMS = {
    "Janalite": dict(kind="矿洞手采", rs=3000, price=17640, inst="中", res="中",
                 locs=[("Calliope", "Stanton", 2.0), ("Clio", "Stanton", 2.0), ("Euterpe", "Stanton", 2.0), ("Lyria", "Stanton", 2.0), ("Wala", "Stanton", 2.0), ("microTech", "Stanton", 2.0), ("Pyro III (Bloom)", "Pyro", 2.0), ("Pyro V-e (Fuego)", "Pyro", 2.0), ("Pyro VI (Terminus)", "Pyro", 2.0), ("Hathor Caves", "Stanton", 1.1)]),
    "Hadanite": dict(kind="车矿·手采", rs=3000, price=275, inst="中", res="低",
                 locs=[("Aberdeen", "Stanton", 6.0), ("Arial", "Stanton", 6.0), ("Cellin", "Stanton", 6.0), ("Daymar", "Stanton", 6.0), ("Hurston", "Stanton", 6.0), ("Ita", "Stanton", 6.0), ("Magda", "Stanton", 6.0), ("Yela", "Stanton", 6.0), ("Pyro I", "Pyro", 6.0), ("Pyro II (Monox)", "Pyro", 6.0), ("Pyro IV", "Pyro", 6.0), ("Pyro V-a (Ignis)", "Pyro", 6.0), ("Pyro V-b (Vatra)", "Pyro", 6.0), ("Pyro V-c (Adir)", "Pyro", 6.0), ("Pyro V-d (Fairo)", "Pyro", 6.0), ("Pyro V-f (Vuur)", "Pyro", 6.0), ("Hathor Caves", "Stanton", 3.2)]),
    "Feynmaline": dict(kind="车矿", rs=4000, price=220, inst="中", res="低",
                 locs=[("Pyro IV", "Pyro", 100.0), ("Pyro V-a (Ignis)", "Pyro", 100.0), ("Pyro V-e (Fuego)", "Pyro", 100.0), ("Pyro VI (Terminus)", "Pyro", 100.0), ("Aberdeen", "Stanton", 64.0), ("Arial", "Stanton", 52.0), ("Daymar", "Stanton", 40.0), ("Magda", "Stanton", 37.0), ("Ita", "Stanton", 26.9), ("Cellin", "Stanton", 12.0), ("Clio", "Stanton", 12.0), ("Yela", "Stanton", 8.0), ("Calliope", "Stanton", 4.0), ("Hurston", "Stanton", 4.0), ("Lyria", "Stanton", 4.0), ("Wala", "Stanton", 4.0), ("microTech", "Stanton", 4.0)]),
    "Aphorite": dict(kind="车矿·手采", rs=3000, price=152, inst="很低", res="低",
                 locs=[("Breaker Stations Interior", "Nyx", 75.0), ("Calliope", "Stanton", 61.1), ("Clio", "Stanton", 61.1), ("Euterpe", "Stanton", 61.1), ("Lyria", "Stanton", 61.1), ("Wala", "Stanton", 61.1), ("microTech", "Stanton", 61.1), ("Pyro III (Bloom)", "Pyro", 61.1), ("Pyro V-e (Fuego)", "Pyro", 61.1), ("Pyro VI (Terminus)", "Pyro", 61.1), ("Aberdeen", "Stanton", 58.6), ("Arial", "Stanton", 58.6), ("Cellin", "Stanton", 58.6), ("Daymar", "Stanton", 58.6), ("Hurston", "Stanton", 58.6), ("Ita", "Stanton", 58.6), ("Magda", "Stanton", 58.6), ("Yela", "Stanton", 58.6), ("Pyro I", "Pyro", 58.6), ("Pyro II (Monox)", "Pyro", 58.6), ("Pyro IV", "Pyro", 58.6), ("Pyro V-a (Ignis)", "Pyro", 58.6), ("Pyro V-b (Vatra)", "Pyro", 58.6), ("Pyro V-c (Adir)", "Pyro", 58.6), ("Pyro V-d (Fairo)", "Pyro", 58.6), ("Pyro V-f (Vuur)", "Pyro", 58.6), ("Hathor Caves", "Stanton", 30.2)]),
    "Glacosite": dict(kind="车矿", rs=4000, price=145, inst="很低", res="中",
                 locs=[("Pyro II (Monox)", "Pyro", 100.0), ("Pyro V-c (Adir)", "Pyro", 100.0), ("Pyro V-f (Vuur)", "Pyro", 100.0), ("Euterpe", "Stanton", 88.0), ("Calliope", "Stanton", 84.0), ("Ita", "Stanton", 69.2), ("Clio", "Stanton", 68.0), ("Yela", "Stanton", 68.0), ("microTech", "Stanton", 68.0), ("Magda", "Stanton", 59.3), ("Pyro V-b (Vatra)", "Pyro", 50.0), ("Lyria", "Stanton", 48.0), ("Wala", "Stanton", 40.0), ("Aberdeen", "Stanton", 32.0), ("Arial", "Stanton", 32.0), ("Cellin", "Stanton", 32.0), ("Hurston", "Stanton", 32.0), ("Daymar", "Stanton", 12.0)]),
    "Dolivine": dict(kind="车矿·手采", rs=3000, price=130, inst="很低", res="中",
                 locs=[("Calliope", "Stanton", 36.9), ("Clio", "Stanton", 36.9), ("Euterpe", "Stanton", 36.9), ("Lyria", "Stanton", 36.9), ("Wala", "Stanton", 36.9), ("microTech", "Stanton", 36.9), ("Pyro III (Bloom)", "Pyro", 36.9), ("Pyro V-e (Fuego)", "Pyro", 36.9), ("Pyro VI (Terminus)", "Pyro", 36.9), ("Aberdeen", "Stanton", 35.4), ("Arial", "Stanton", 35.4), ("Cellin", "Stanton", 35.4), ("Daymar", "Stanton", 35.4), ("Hurston", "Stanton", 35.4), ("Ita", "Stanton", 35.4), ("Magda", "Stanton", 35.4), ("Yela", "Stanton", 35.4), ("Pyro I", "Pyro", 35.4), ("Pyro II (Monox)", "Pyro", 35.4), ("Pyro IV", "Pyro", 35.4), ("Pyro V-a (Ignis)", "Pyro", 35.4), ("Pyro V-b (Vatra)", "Pyro", 35.4), ("Pyro V-c (Adir)", "Pyro", 35.4), ("Pyro V-d (Fairo)", "Pyro", 35.4), ("Pyro V-f (Vuur)", "Pyro", 35.4), ("Hathor Caves", "Stanton", 18.3)]),
    "Beradom": dict(kind="车矿", rs=4000, price=120, inst="很低", res="低",
                 locs=[("Pyro I", "Pyro", 100.0), ("Pyro III (Bloom)", "Pyro", 100.0), ("Pyro V-d (Fairo)", "Pyro", 100.0), ("Hurston", "Stanton", 64.0), ("Cellin", "Stanton", 56.0), ("Wala", "Stanton", 56.0), ("Pyro V-b (Vatra)", "Pyro", 50.0), ("Daymar", "Stanton", 48.0), ("Lyria", "Stanton", 48.0), ("microTech", "Stanton", 28.0), ("Yela", "Stanton", 24.0), ("Clio", "Stanton", 20.0), ("Arial", "Stanton", 16.0), ("Calliope", "Stanton", 12.0), ("Euterpe", "Stanton", 12.0), ("Aberdeen", "Stanton", 4.0), ("Ita", "Stanton", 3.9), ("Magda", "Stanton", 3.7)]),
    "Jaclium": dict(kind="矿洞手采", rs=3000, price=None, inst="低", res="高",
                 locs=[("Hathor Caves", "Stanton", 19.5)]),
    "Sadaryx": dict(kind="矿洞手采", rs=3000, price=None, inst="中", res="低",
                 locs=[("Breaker Stations Interior", "Nyx", 25.0)]),
    "Saldynium": dict(kind="矿洞手采", rs=3000, price=None, inst="低", res="低",
                 locs=[("Hathor Caves", "Stanton", 15.8)]),
}
