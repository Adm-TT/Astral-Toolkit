"""当前版本清单 data/gamedata/current.json：唯一的发布入口，说现在该用哪个库文件

读的时候打开即关；写的时候先写临时文件、刷盘，再原子换名（Windows 被占用时重试几次）。"""

import json
import os
import time
from dataclasses import asdict, dataclass

from ._paths import manifest_path, tmp_dir
from ._types import GamedataUnavailable

_FIELDS = ("generation_id", "data_version", "schema_version", "file")


@dataclass(frozen=True)
class Manifest:
    generation_id: str  # 这次构建的唯一代号，也是库文件名的一部分
    data_version: str  # 内容版本：源文件 + schema + 导入规则的哈希；缓存键用它
    schema_version: int
    file: str  # 库文件名（相对 gamedata 目录）


def read_manifest() -> Manifest | None:
    """没有清单返回 None；清单坏了（不是 JSON、缺字段、类型不对）抛 GamedataUnavailable"""
    p = manifest_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise GamedataUnavailable(f"读不了游戏数据清单 {p}：{e}") from e
    try:
        d = json.loads(raw)
        if not isinstance(d, dict) or any(k not in d for k in _FIELDS):
            raise ValueError("缺字段")
        m = Manifest(
            str(d["generation_id"]),
            str(d["data_version"]),
            int(d["schema_version"]),
            str(d["file"]),
        )
    except (ValueError, TypeError) as e:
        raise GamedataUnavailable(f"游戏数据清单 {p} 坏了：{e}") from e
    return m


def write_manifest(m: Manifest) -> None:
    """原子写清单：临时文件 → fsync → os.replace；PermissionError（Windows 正被读）重试 6 次"""
    dst = manifest_path()
    tmp_dir().mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir() / f"current.json.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(m), f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    try:
        for i in range(6):
            try:
                os.replace(tmp, dst)
                break
            except PermissionError:
                if i == 5:
                    raise
                time.sleep(0.05)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
