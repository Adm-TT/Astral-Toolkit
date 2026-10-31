"""这台电脑的设备编号（天枢 1.6.54 起，每笔库存变动都记下是哪台电脑录的，给以后接交易平台、多台设备同步用）

编号 = Windows 安装编号（注册表 MachineGuid）加盐后的散列，取 16 位：同一台电脑永远一样，重装天枢、换文件夹也不变；
不会把 MachineGuid 原样存下来或传出去。拿不到时退回电脑名的散列。
设备名就是电脑名（DESKTOP-XXXX），只用来在记录里给你看是哪台录的。
"""

import hashlib
import os
import platform
from functools import lru_cache


def _machine_guid():
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        return ""


@lru_cache(maxsize=1)
def device():
    """(设备编号, 设备名)"""
    name = os.environ.get("COMPUTERNAME") or platform.node() or "本机"
    seed = _machine_guid() or ("node:" + name)
    return hashlib.sha256(("dubhe-device|" + seed).encode("utf-8")).hexdigest()[
        :16
    ], name
