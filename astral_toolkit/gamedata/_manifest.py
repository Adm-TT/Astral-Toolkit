"""当前版本清单 data/gamedata/current.json：唯一的发布入口，说现在该用哪个库文件

读的时候打开即关；写的时候先写临时文件、刷盘，再原子换名（Windows 被占用时重试几次）。"""

import json
import os
import time
from dataclasses import asdict, dataclass

from ._paths import manifest_path, tmp_dir
from ._types import GamedataUnavailable

_FIELDS = ("generation_id", "data_version", "schema_version", "file")
_RETRY_TIMES = (
    10  # 读清单撞上换名瞬间的重试：10 × 20 ms（批 1 实测边搜边发布会撞到，2026-11-02）
)
_RETRY_SLEEP = 0.02
_last: tuple | None = (
    None  # (路径, mtime_ns, size, ino, Manifest)：文件没变就不重读（收口 2：导航每帧读清单好几次）
)


@dataclass(frozen=True)
class Manifest:
    generation_id: str  # 这次构建的唯一代号，也是库文件名的一部分
    data_version: str  # 内容版本：源文件 + schema + 导入规则的哈希；缓存键用它
    schema_version: int
    file: str  # 库文件名（相对 gamedata 目录）


def read_manifest() -> Manifest | None:
    """没有清单返回 None；清单坏了（不是 JSON、缺字段、类型不对）抛 GamedataUnavailable。
    文件的 (mtime, 大小, inode) 和上次一样就直接给上次解析的结果——发布端是 os.replace 换文件，三样必有一样变"""
    global _last
    p = manifest_path()
    try:
        st = os.stat(p)
        key = (str(p), st.st_mtime_ns, st.st_size, st.st_ino)
    except FileNotFoundError:
        return None
    except OSError:
        key = None  # 读不到属性就老老实实读文件，让下面的错误处理说话
    last = _last
    if key is not None and last is not None and last[:4] == key:
        return last[4]
    raw = None
    for i in range(_RETRY_TIMES):
        try:
            raw = p.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return None
        except PermissionError as e:  # Windows：发布端正在 os.replace 换清单，几十毫秒的共享冲突；和写端一样重试
            if i == _RETRY_TIMES - 1:
                raise GamedataUnavailable(f"读不了游戏数据清单 {p}：{e}") from e
            time.sleep(_RETRY_SLEEP)
        except OSError as e:
            raise GamedataUnavailable(f"读不了游戏数据清单 {p}：{e}") from e
    assert raw is not None
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
    if key is not None:
        _last = key + (m,)
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
