"""测试用：把一张暗背景的采矿助手截图里扫描面板上半截的背景换成亮灰色浓雾（2026-10-23 Calliope 实测的雾色），HUD 字照原样叠上去。
用来测「面板一半在雾里、一半在地面上」这种情况（整块搜索区里雾不到三成，以前的办法会把雾当成字）"""
import numpy as np

FOG = (210, 222, 232)


def fog_panel(img, box, edge=12):
    """img：PIL 整屏图；box：要换成雾的区域 (左, 上, 右, 下)，整屏像素坐标。返回新的 PIL 图"""
    import cv2
    from PIL import Image
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    bg = cv2.medianBlur(a.astype(np.uint8), 61).astype(np.float32)        # 去掉字和难度条后的背景（窗口要比难度条高得多）
    light = np.clip(a - bg, 0, 255)                                        # HUD 字的亮度（叠加在背景上）
    fog = np.clip(np.array(FOG, np.float32) + light * 1.1, 0, 255)
    m = np.zeros(a.shape[:2], np.float32)
    l, t, r, b = box
    m[t:b, l:r] = 1
    m = cv2.blur(m, (edge * 2 + 1, edge * 2 + 1))[..., None]               # 雾的边缘柔和一点
    out = a * (1 - m) + fog * m
    return Image.fromarray(out.astype(np.uint8))
