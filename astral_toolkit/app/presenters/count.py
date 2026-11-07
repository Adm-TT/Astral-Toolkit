"""盘点的悬浮窗文字（目录迁移 R5 从盘点线程搬来）：只排版，不取数据"""


def hud_text(place, items, qty_text) -> str:
    """悬浮窗里的盘点文字：最近 8 项，品质为空时不带 Q；qty_text 把数量写成玩家看得懂的（tasks/hover.qty_text）"""
    lines = [f"盘点｜{place}"]
    for v in list(items.values())[-8:]:
        q = "" if v["quality"] is None else f" Q{v['quality']}"
        lines.append(
            f"{v['zh'] or v['en']}{q} ×{v['cells']}  {qty_text(v['qty'], v['unit'])}"
        )
    return "\n".join(lines)
