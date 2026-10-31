"""解包核对：矿物品质档位（DataCore crafting/qualityquantization）和 AT 的 quality.py / quality_tiers.py 比，打印不一样的。
用法：python tools/unpack_quality.py <records/crafting/qualityquantization 目录>"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sc_mining.mining.quality import TIERS as T7          # noqa: E402
from sc_mining.mining.quality_tiers import TIERS as T8    # noqa: E402


def main(d):
    game = {}
    for f in Path(d).glob("quantization_*.json"):
        bands = json.loads(f.read_text(encoding="utf-8"))["_RecordValue_"]["qualityQuantization"]["bands"]
        game[f.stem[len("quantization_"):]] = [b["mappedValue"] for b in bands]
    key = lambda n: {"pressurizedice": "rawice"}.get(n.lower().replace(" ", ""), n.lower().replace(" ", ""))
    bad = 0
    for n, v in T8.items():
        g = game.get(key(n))
        if g and list(v) != g:
            print(f"quality_tiers {n}: AT {list(v)} / 游戏 {g}"); bad += 1
    for n, v in T7.items():
        g = game.get(key(n))
        if g and list(v) != g[:7]:
            print(f"quality {n}: AT {list(v)} / 游戏 {g[:7]}"); bad += 1
    print("✅ 品质档位全部一致" if not bad else f"❌ {bad} 处不一致")
    return bad


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
