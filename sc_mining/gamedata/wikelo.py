"""维科洛 topic：wikelo_contracts / wikelo_rewards / wikelo_requirements / wikelo_contract_systems（wikelo.json 的兑换），
print_spots / print_spot_places（print_spots.json：打印机打印的物品在哪打）

兑换在消费方（目标清单、悬停、控制台）是当 dict 传的，所以还原成与 wikelo.json 同形的 dict 列表，按内容版本缓存一份
（同一版本内是同一个列表、同一批对象）。传 snap 时用调用方的快照，不传就自己开一个。"""

from dataclasses import dataclass

from ._cache import VersionCache
from ._ready import use


@dataclass(frozen=True)
class Contracts:
    """一个内容版本的全部兑换：rows 与 wikelo.json 的 contracts 同形（按源顺序）；by_req：(兑换 id, 材料下标) → (兑换, 材料)"""

    rows: list
    by_req: dict


_all: VersionCache[Contracts] = VersionCache()


def _load(s) -> Contracts:
    rows, by_id, by_req = [], {}, {}
    for cid, typ, t, te, rz in s.execute(
        "select id, type, t, te, rz from wikelo_contracts order by source_order"
    ):
        c = {
            "id": cid,
            "type": typ,
            "t": t,
            "te": te,
            "rz": rz,
            "rewards": [],
            "req": [],
            "systems": [],
        }
        rows.append(c)
        by_id[cid] = c
    for cid, item in s.execute(
        "select contract_id, item from wikelo_rewards order by contract_id, idx"
    ):
        by_id[cid]["rewards"].append(item)
    for cid, idx, n, z, q, u in s.execute(
        "select contract_id, idx, n, z, q, u from wikelo_requirements order by contract_id, idx"
    ):
        # 汉化包里个别名字末尾带了个反斜杠（「约曼迪之眼\」）：原 crafting.wikelo.load() 读完就地去掉，这里还原时去
        r = {"n": n, "z": z.rstrip("\\ ").strip(), "q": q, "u": u}
        by_id[cid]["req"].append(r)
        by_req[(cid, idx)] = (by_id[cid], r)
    for cid, system in s.execute(
        "select contract_id, system from wikelo_contract_systems order by contract_id, idx"
    ):
        by_id[cid]["systems"].append(system)
    return Contracts(rows, by_req)


def contracts(snap=None) -> list[dict]:
    """全部兑换（按源顺序）；按内容版本缓存一份"""
    with use(snap) as s:
        return _all.get(s, _load).rows


def requiring(
    norm_en: str | None, norm_zh: str | None, snap=None
) -> list[tuple[dict, dict]]:
    """材料英文名比较键（crafting.wikelo._fold）= norm_en、或中文名比较键 = norm_zh 的 (兑换, 材料)，按兑换源顺序、材料顺序；
    传 None 的那一边不比（空串照样比：和原来「名字非空就比折叠结果」一致）。只是相等，放宽成包含的那一步在调用方"""
    if norm_en is None and norm_zh is None:
        return []
    with use(snap) as s:
        c = _all.get(s, _load)
        return [
            c.by_req[(cid, idx)]
            for cid, idx in s.execute(
                "select r.contract_id, r.idx from wikelo_requirements r "
                "join wikelo_contracts c on c.id = r.contract_id "
                "where (? and r.norm_n = ?) or (? and r.norm_z = ?) order by c.source_order, r.idx",
                (
                    norm_en is not None,
                    norm_en or "",
                    norm_zh is not None,
                    norm_zh or "",
                ),
            )
        ]


_spots: VersionCache[dict] = VersionCache()


def _load_spots(s) -> dict:
    """物品名小写 → 打印地点列表；小写撞名后出现的那条赢（同原来的 dict 推导式）"""
    places: dict[str, list[str]] = {}
    for name, place in s.execute(
        "select item_name, place from print_spot_places order by item_name, idx"
    ):
        places.setdefault(name, []).append(place)
    return {
        name.lower(): places.get(name, [])
        for (name,) in s.execute(
            "select item_name from print_spots order by source_order"
        )
    }


def print_places(key: str, snap=None) -> list[str]:
    """打印地点：key 是已经去空格、转小写的物品名；没有 → []"""
    with use(snap) as s:
        return _spots.get(s, _load_spots).get(key, [])
