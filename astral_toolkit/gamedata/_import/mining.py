"""schema 6：采矿（矿石、船信号、精炼产出）"""

import sqlite3

from .._sources import SourceBytes
from ._common import _d


# ---------------------------------------------------------------- schema 6：采矿（批 5 公共层，2026-11-02）
# 三份都存原样 JSON：消费方（mining_area.rocks_table / area_for_spot、shipsig.match、uex.apply_live 的 yields）吃的就是整段 dict，
# 拆表没有查询收益还会改数值类型。「源文件在不在」看 meta 的 src:<文件名> 是否为空串


def import_mining_rocks(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "mining_rocks.json", None)
    if not isinstance(raw, dict):
        return  # 缺失 / 坏 / 不是 dict：没有表行、没有 meta 键（批 5 据此判「没有石头表」）
    sections, extra, rows = [], {}, []
    for name, sec in raw.items():
        if isinstance(sec, dict):
            sections.append(name)
            for i, (k, v) in enumerate(sec.items()):
                rows.append(
                    (
                        str(name),
                        str(k),
                        json.dumps(v, ensure_ascii=False, separators=(",", ":")),
                        i,
                    )
                )
        else:
            extra[str(name)] = sec
    conn.executemany("insert or ignore into mining_rock_entries values (?,?,?,?)", rows)
    conn.execute(
        "insert or replace into meta values ('mining_rocks_meta', ?)",
        (
            json.dumps(
                {"sections": sections, "extra": extra},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
    )


def import_ship_signatures(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "ship_signatures.json", None)
    ships = raw.get("ships") if isinstance(raw, dict) else None
    conn.executemany(
        "insert into ship_signatures values (?,?)",
        [
            (i, json.dumps(s, ensure_ascii=False, separators=(",", ":")))
            for i, s in enumerate(ships if isinstance(ships, list) else [])
            if isinstance(s, dict)
        ],
    )


def import_refinery_yields(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "prices.json", None)
    yields = raw.get("yields") if isinstance(raw, dict) else None
    conn.executemany(
        "insert or ignore into refinery_yields values (?,?,?)",
        [
            (
                str(station),
                json.dumps(bonus, ensure_ascii=False, separators=(",", ":")),
                i,
            )
            for i, (station, bonus) in enumerate(
                yields.items() if isinstance(yields, dict) else ()
            )
            if isinstance(bonus, dict)
        ],
    )
