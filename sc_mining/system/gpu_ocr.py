"""文字识别状态兼容层（DirectML 现已直接在主进程中根据用户设置运行，不再通过后台子进程通信）"""
import os
import sys


def is_worker():
    return False


def wanted():
    from ..core.perf import gpu_available, is_gpu_preferred
    return gpu_available() and is_gpu_preferred()


def active():
    from ..core.perf import ocr_device
    return ocr_device() == "显卡"


def device():
    from ..core.perf import ocr_device
    return ocr_device()


def acquire():
    return active()


def release():
    pass


def revive():
    pass


def ensure_active(blocking=True):
    return active()


def release_permanent():
    pass


def shutdown():
    pass


def run(arr, kw, urgent=False):
    return None


def info():
    from ..core.perf import ocr_device, gpu_available, last_ocr_error
    return {
        "active": active(),
        "device": device(),
        "wanted": wanted(),
        "permanent": True,
        "last_error": last_ocr_error()
    }


def worker_main():
    pass


if __name__ == "__main__":
    pass
