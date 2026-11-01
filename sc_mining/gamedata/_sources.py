"""建库读哪些源文件：显式清单，不扫目录。每个文件只读一次字节，同一份字节既算哈希又解析，哈希和入库内容不会对不上"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._types import BuildError


@dataclass(frozen=True)
class Source:
    name: str
    required: bool


# 试点（批 1）所需的源；后面批次按矩阵往这里加，加了就升 _schema.IMPORTER_VERSION
SOURCES: tuple[Source, ...] = (
    Source("shops.json", True),
    Source("loot_index.json", False),
    Source("zh_names.json", False),
    Source("zh_only_names.json", False),
    Source("name_aliases.json", False),
    Source("wiki_items.json", False),
    Source("prices.json", False),
    # schema 2：导航
    Source("starmap.json", False),
    Source("starmap_fixes.json", False),
    Source("city_places.json", False),
    Source("place_amenities.json", False),
    Source("station_lifts.json", False),
    Source("places_zh.json", False),
    Source("places_extra_zh.json", False),
    Source("place_codes_zh.json", False),
    Source("mining_spots.json", False),
)


@dataclass(frozen=True)
class SourceBytes:
    name: str
    present: bool
    sha256: str  # 不存在时 ""
    data: Any  # 解析后的 JSON；不存在时 None


def read_sources(data_dir: Path) -> dict[str, SourceBytes]:
    """按 SOURCES 读 data_dir 下的文件。缺必需文件、JSON 坏掉都抛 BuildError（旧库不受影响）"""
    out: dict[str, SourceBytes] = {}
    for src in SOURCES:
        p = data_dir / src.name
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            if src.required:
                raise BuildError(f"缺少必需的数据文件 {src.name}，先「更新数据」")
            out[src.name] = SourceBytes(src.name, False, "", None)
            continue
        except OSError as e:
            raise BuildError(f"读不了 {src.name}：{e}") from e
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise BuildError(
                f"{src.name} 不是完整的 JSON（{e}），重新「更新数据」"
            ) from e
        out[src.name] = SourceBytes(
            src.name, True, hashlib.sha256(raw).hexdigest(), data
        )
    return out
