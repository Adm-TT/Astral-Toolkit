"""生成「第三方许可.txt」：从 .venv 里实际装的组件收集许可证原文（不手抄，免得漏抄错抄），再加上 Python 和 D-DIN、DejaVu Sans Mono 字体。
打包时（tools/pack.py）自动调用；也可以单独跑：
  .venv\\Scripts\\python.exe -X utf8 tools\\collect_licenses.py
MIT / BSD / Apache-2.0 / OFL 等许可都要求分发时附上许可证原文和版权声明（2026-10-26）
"""

import importlib.metadata as md
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "第三方许可.txt"
SKIP = {"pip", "setuptools", "wheel"}  # 只在安装时用，不随 AT 运行
NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


def _license_files(dist):
    out = []
    for f in dist.files or []:
        name = Path(str(f)).name.upper()
        if any(name.startswith(n) for n in NAMES) and "/tests/" not in str(f).replace(
            "\\", "/"
        ):
            p = Path(dist.locate_file(f))
            if p.is_file() and p not in out:
                out.append(p)
    return out


def build():
    parts = [
        "AT 星际公民助手　第三方许可",
        "AT 使用了下列开源组件、Python 运行环境和字体，它们按各自的许可证提供，许可证原文附在下面。",
        "AT 本身按 AGPL-3.0 开源（见「LICENSE」和「免责声明.txt」第 2 条）。",
        "",
    ]
    rows = []
    for d in sorted(
        md.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()
    ):
        name = d.metadata["Name"] or ""
        if not name or name.lower() in SKIP:
            continue
        lic = (
            d.metadata.get("License-Expression")
            or (d.metadata.get("License") or "").splitlines()[0:1]
            or [""]
        )
        lic = lic if isinstance(lic, str) else (lic[0] if lic else "")
        classifiers = [
            c.split("::")[-1].strip()
            for c in (d.metadata.get_all("Classifier") or [])
            if c.startswith("License ::")
        ]
        home = d.metadata.get("Home-page") or next(
            (
                u.split(",", 1)[-1].strip()
                for u in (d.metadata.get_all("Project-URL") or [])
                if u.lower().startswith(("homepage", "source", "repository"))
            ),
            "",
        )
        rows.append(
            (
                name,
                d.version,
                lic or "、".join(classifiers) or "见下方原文",
                _license_files(d),
                d.metadata.get("Author") or d.metadata.get("Author-email") or "",
                home,
            )
        )
    py = Path(sys.base_prefix) / "LICENSE.txt"
    font = ROOT / "sc_mining" / "app" / "web" / "fonts" / "OFL.txt"
    parts.append("一、组件列表")
    parts.append(
        f"- Python {sys.version.split()[0]}：Python Software Foundation License"
    )
    parts += [f"- {n} {v}：{l}" for n, v, l, *_ in rows]  # noqa: E741
    parts.append("- D-DIN 字体：SIL Open Font License 1.1")
    parts.append(
        "- DejaVu Sans Mono 字体：Bitstream Vera Fonts License（DejaVu 的改动属于公有领域）"
    )
    parts.append("")
    parts.append("二、许可证原文")
    missing = []

    def add(title, files, fallback=""):
        if not files:
            missing.append(title)
            if (
                fallback
            ):  # 安装包里没附许可证文件：写明许可证、作者、项目主页（原文见主页）
                parts.append("=" * 72)
                parts.append(title)
                parts.append("=" * 72)
                parts.append(fallback)
                parts.append("")
            return
        for f in files:
            parts.append("=" * 72)
            parts.append(f"{title}　（{f.name}）")
            parts.append("=" * 72)
            parts.append(f.read_text(encoding="utf-8", errors="replace").strip())
            parts.append("")

    add(f"Python {sys.version.split()[0]}", [py] if py.is_file() else [])
    for n, v, lic, files, author, home in rows:
        add(
            f"{n} {v}",
            files,
            f"许可证：{lic}"
            + (f"\n版权人 / 作者：{author}" if author else "")
            + (
                f"\n许可证原文见项目主页：{home}"
                if home
                else "\n此组件的安装包未附许可证原文"
            ),
        )
    add("D-DIN 字体", [font] if font.is_file() else [])
    dejavu = ROOT / "sc_mining" / "fonts" / "LICENSE-DejaVu.txt"
    add("DejaVu Sans Mono 字体", [dejavu] if dejavu.is_file() else [])
    # 安装包没附原文、许可证是 Apache-2.0 的（flatbuffers、rapidocr-onnxruntime；RapidOCR 的模型来自 PaddleOCR，也是 Apache-2.0）：
    # Apache-2.0 要求附全文，从环境里别的组件附带的 Apache 原文取一份
    apache = [
        f"{n} {v}"
        for n, v, lic, files, *_ in rows
        if not files and "apache" in lic.lower()
    ]
    if apache:
        text = next(
            (
                f.read_text(encoding="utf-8", errors="replace")
                for *_, files, _a, _h in rows
                for f in files
                if "Apache License"
                in f.read_text(encoding="utf-8", errors="replace")[:400]
                and "Version 2.0"
                in f.read_text(encoding="utf-8", errors="replace")[:400]
            ),
            "",
        )
        if text:
            parts.append("=" * 72)
            parts.append(
                "Apache License 2.0 原文（适用于："
                + "、".join(apache)
                + "；RapidOCR 的识别模型来自 PaddleOCR，同为 Apache-2.0）"
            )
            parts.append("=" * 72)
            parts.append(text.strip())
            parts.append("")
            missing = [m for m in missing if m not in apache]
    OUT.write_text(
        "\r\n".join(parts).replace("\r\n", "\n").replace("\n", "\r\n"),
        encoding="utf-8-sig",
    )
    return len(rows), missing


if __name__ == "__main__":
    n, missing = build()
    print(f"✅ 已生成 {OUT}：{n} 个组件 + Python + 字体")
    if missing:
        print("⚠️ 这些没找到许可证原文文件，要手动补：" + "、".join(missing))
