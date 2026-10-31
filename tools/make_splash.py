"""Velopack 安装时的启动图（安装进度条画在它上面，2026-10-27）：DESIGN.md 的颜色——深海军蓝底、琥珀金细线、暖银白字
  .venv\\Scripts\\python.exe -X utf8 tools\\make_splash.py → tools\\velopack_splash.png"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
NAVY, GOLD, WHITE, STEEL = "#152851", "#c6ab6c", "#e9edf5", "#6f84a8"     # 2026-10-27 蓝金


def main():
    W, H = 640, 320
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    icon = Image.open(ROOT / "sc_mining" / "app" / "web" / "icon.png").convert("RGBA").resize((96, 96), Image.LANCZOS)
    im.paste(icon, ((W - 96) // 2, 58), icon)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 30)
    small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 16)
    title = "AT 星际公民助手"
    tw = d.textlength(title, font=font)
    d.text(((W - tw) / 2, 172), title, fill=WHITE, font=font)
    d.line([(W / 2 - 40, 222), (W / 2 + 40, 222)], fill=GOLD, width=2)
    sub = "正在安装"
    sw = d.textlength(sub, font=small)
    d.text(((W - sw) / 2, 236), sub, fill=STEEL, font=small)
    out = ROOT / "tools" / "velopack_splash.png"
    im.save(out)
    print(out)


if __name__ == "__main__":
    main()
