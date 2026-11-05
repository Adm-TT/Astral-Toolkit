"""垃圾代码检查（2026-11-05，老大定：每个 PR 自动查）：只用标准库，不需要游戏数据，CI 和本机全量都跑。

查六样，和 tools/junk_baseline.json 里登记的老问题比，**只许减不许加**：
  没人用      astral_toolkit 里的函数 / 类 / 方法 / 大写常量，全仓库（产品、tests、tools 的 .py，加上
              astral_toolkit 和 tools/shell 里的 js / html / json / cs）除了定义那一处再没出现过
  只有测试用  产品代码和 tools 都不用，只剩 tests 在调（生产里已经死了，被测试吊着）
  重复        两个以上模块里函数体一模一样（去掉文档串后比 AST；太短的一两行不算）
  门面没人用  包的 __init__.py（和 navigation/navigate.py）从子模块再导出的名字，除了门面和定义它的模块，没人用
  noqa F401   每个文件里压掉「导入没用到」提示的行数
  过时说法    注释 / 文档串里还在说已经删掉的东西（services.py、sc_mining、EngineManager、get_instance）

按名字认：别处有同名的东西就当有人用（会漏掉一些，但不会冤枉）。getattr("名字")、_T("x").名字、路由表里的
字符串都算有人用；__all__ 里列着不算。

用法（仓库根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\junk_check.py                  查；有新垃圾退出码 1
  .venv\\Scripts\\python.exe -X utf8 tools\\junk_check.py --list           列出现在全部的（含已登记的）
  .venv\\Scripts\\python.exe -X utf8 tools\\junk_check.py --write-baseline 清掉老问题后把基线写成现在这样
确实要留的（比如专门给测试留的口子）：写进基线的 allow，后面写原因。
不进仓库的私有脚本（PRIVATE）不算：CI 上没有它们，本机算进来结果就和 CI 不一样。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "junk_baseline.json"
PROD = "astral_toolkit"
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STALE = re.compile(r"services\.py|sc_mining|EngineManager|get_instance")
NOQA_F401 = re.compile(r"#\s*noqa:[^#\n]*\bF401\b")
OTHER_SUFFIXES = (".js", ".html", ".json", ".cs")
SKIP_DIRS = {
    "__pycache__",
    "fixtures",
    "samples",
    "bin",
    "obj",
    "node_modules",
    ".venv",
}
# .gitignore 里不进仓库的私有脚本：CI 上没有，本机也不算，两边查出来才一样
PRIVATE = {"tools/publish_hk.py"}
# 框架 / 协议按约定调用的名字：不算没人用
FRAMEWORK = {
    "main",
    "run",
    "handle",
    "setUp",
    "tearDown",
    "do_GET",
    "do_POST",
    "do_HEAD",
    "do_OPTIONS",
    "do_PUT",
    "do_DELETE",
    "log_message",
}
DUP_MIN_NODES = 10  # 函数体 AST 节点太少（一两行转发）不算重复；按节点数算，不按 ast.dump 长度（3.12 / 3.13 输出长短不一样）
FACADES_EXTRA = ("astral_toolkit/navigation/navigate.py",)


@dataclass
class Findings:
    dead: dict[str, str] = field(default_factory=dict)  # id -> 位置
    test_only: dict[str, str] = field(default_factory=dict)
    dup: dict[str, str] = field(default_factory=dict)  # 组 id -> 说明
    facade: dict[str, str] = field(default_factory=dict)
    noqa_f401: dict[str, int] = field(default_factory=dict)
    stale: dict[str, int] = field(default_factory=dict)


def _files(root: Path, sub: str, suffixes: tuple[str, ...]) -> list[Path]:
    base = root / sub
    if not base.exists():
        return []
    out = []
    for p in base.rglob("*"):
        if (
            p.suffix in suffixes
            and p.is_file()
            and not (SKIP_DIRS & set(p.relative_to(root).parts))
            and p.relative_to(root).as_posix() not in PRIVATE
        ):
            out.append(p)
    return sorted(out)


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _area(rel: str) -> str:
    if rel.startswith(PROD + "/"):
        return "prod"
    if rel.startswith("tests/"):
        return "tests"
    return "tools"


def _all_strings(tree: ast.AST) -> set[int]:
    """__all__ = [...] 里的字符串节点：列在导出表里不算有人用"""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                for sub in ast.walk(node.value):
                    skip.add(id(sub))
    return skip


def _body_key(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
    """（去掉文档串后的函数体 + 参数的 AST 文本，函数体节点数）"""
    body = node.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    text = "\n".join(ast.dump(b, annotate_fields=False) for b in body)
    text += "|" + ast.dump(node.args, annotate_fields=False)
    size = sum(1 for b in body for _ in ast.walk(b))
    return text, size


def scan(root: Path = ROOT) -> Findings:
    py = (
        _files(root, PROD, (".py",))
        + _files(root, "tests", (".py",))
        + _files(root, "tools", (".py",))
    )
    trees: dict[str, ast.Module] = {}
    for p in py:
        try:
            trees[_rel(root, p)] = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

    # 引用：名字 -> 出现在哪些文件（按区分开）
    used_in: dict[str, set[str]] = defaultdict(set)
    for rel, tree in trees.items():
        skip = _all_strings(tree)
        for node in ast.walk(tree):
            # 只算读（和 del）：FOO = 1、obj.x = 1 这种赋值本身不算有人用
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                used_in[node.id].add(rel)
            elif isinstance(node, ast.Attribute) and not isinstance(
                node.ctx, ast.Store
            ):
                used_in[node.attr].add(rel)
            elif isinstance(node, ast.keyword) and node.arg:
                used_in[node.arg].add(rel)
            elif isinstance(node, ast.alias):
                used_in[node.name.split(".")[-1]].add(rel)
                if node.asname:
                    used_in[node.asname].add(rel)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                for w in IDENT.findall(node.value):
                    used_in[w].add(rel)
    for p in _files(root, PROD, OTHER_SUFFIXES) + _files(
        root, "tools/shell", OTHER_SUFFIXES
    ):
        rel = _rel(root, p)
        for w in set(IDENT.findall(p.read_text(encoding="utf-8", errors="replace"))):
            used_in[w].add(rel)

    found = Findings()

    # 定义：只看产品代码
    defs: list[tuple[str, str, str, int]] = []  # (名字, id, 文件, 行)
    for rel, tree in trees.items():
        if _area(rel) != "prod":
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.append((node.name, f"{rel}::{node.name}", rel, node.lineno))
                if isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            defs.append(
                                (
                                    sub.name,
                                    f"{rel}::{node.name}.{sub.name}",
                                    rel,
                                    sub.lineno,
                                )
                            )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 1:
                        defs.append((t.id, f"{rel}::{t.id}", rel, node.lineno))

    # 同一个名字在定义它的文件里出现，只有定义本身那次不算；定义行里的 Name 节点不存在（def 名不是 Name），
    # 所以「在定义文件里出现过」= 本模块内部有人用
    def_files: dict[str, set[str]] = defaultdict(set)
    for name, _id, rel, _line in defs:
        def_files[name].add(rel)
    for name, did, rel, line in defs:
        if name in FRAMEWORK or (name.startswith("__") and name.endswith("__")):
            continue
        where = used_in.get(name, set())
        if not where:
            found.dead[did] = f"{rel}:{line}"
            continue
        areas = {_area(w) for w in where}
        if areas == {"tests"}:
            found.test_only[did] = f"{rel}:{line}"

    # 重复：函数体一模一样、分在两个以上模块
    groups: dict[str, list[str]] = defaultdict(list)
    for rel, tree in trees.items():
        if _area(rel) != "prod":
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key, size = _body_key(node)
                if size >= DUP_MIN_NODES:
                    groups[hashlib.sha1(key.encode()).hexdigest()].append(
                        f"{rel}::{node.name}"
                    )
    for members in groups.values():
        if len({m.split("::")[0] for m in members}) > 1:
            gid = " | ".join(sorted(members))
            found.dup[gid] = f"{len(members)} 份"

    # 门面：包 __init__.py 和 navigate.py 从子模块（相对导入）再导出的名字
    facades = [
        rel for rel in trees if _area(rel) == "prod" and rel.endswith("/__init__.py")
    ]
    facades += [f for f in FACADES_EXTRA if f in trees]
    for frel in facades:
        tree = trees[frel]
        pkg_dir = frel.rsplit("/", 1)[0]
        for node in tree.body:
            if not (
                isinstance(node, ast.ImportFrom) and node.level == 1 and node.module
            ):
                continue
            src_rel = f"{pkg_dir}/{node.module.replace('.', '/')}.py"
            if src_rel not in trees:
                src_rel = f"{pkg_dir}/{node.module.replace('.', '/')}/__init__.py"
            for a in node.names:
                name = a.asname or a.name
                if name == "*":  # from .x import *：看不出导出了什么，不查
                    continue
                others = used_in.get(name, set()) - {frel, src_rel}
                if not others:
                    found.facade[f"{frel}::{name}"] = f"从 {node.module} 再导出"

    # noqa F401 / 过时说法：按文件计数
    for p in _files(root, PROD, (".py",)):
        rel = _rel(root, p)
        text = p.read_text(encoding="utf-8")
        n = len(NOQA_F401.findall(text))
        if n:
            found.noqa_f401[rel] = n
        s = len(STALE.findall(text))
        if s:
            found.stale[rel] = s
    return found


def load_baseline(path: Path = BASELINE) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


LABELS = {
    "dead": "没人用",
    "test_only": "只有测试用",
    "dup": "重复",
    "facade": "门面再导出没人用",
    "noqa_f401": "noqa F401",
    "stale": "过时说法",
}
HINTS = {
    "dead": "删掉（连调用方和测试一起）",
    "test_only": "产品代码已经不用：连测试一起删；确实是给测试留的口子就写进基线 allow 并写原因",
    "dup": "合成一份，别的地方改成调它",
    "facade": "从门面里删掉这个再导出",
    "noqa_f401": "别再压「导入没用到」：删掉导入，或改成显式再导出",
    "stale": "注释里别再提已经删掉的东西",
}


def compare(found: Findings, base: dict) -> list[str]:
    """返回新问题（每条一行，中文）"""
    allow = set((base.get("allow") or {}).keys())
    new: list[str] = []
    for kind in ("dead", "test_only", "dup", "facade"):
        known = set(base.get(kind) or [])
        for item, where in sorted(getattr(found, kind).items()):
            if item in known or item in allow:
                continue
            new.append(f"[{LABELS[kind]}] {item}（{where}）—— {HINTS[kind]}")
    for kind in ("noqa_f401", "stale"):
        known_counts = base.get(kind) or {}
        for rel, n in sorted(getattr(found, kind).items()):
            old = int(known_counts.get(rel, 0))
            if n > old:
                new.append(f"[{LABELS[kind]}] {rel}：{old} → {n} 处 —— {HINTS[kind]}")
    return new


def tightenable(found: Findings, base: dict) -> int:
    """基线里登记了、现在已经清掉的条数（计数类按少了几处算）：不收紧不报错，但同一处以后再犯就查不出来"""
    n = 0
    for kind in ("dead", "test_only", "dup", "facade"):
        n += len(set(base.get(kind) or []) - set(getattr(found, kind)))
    for kind in ("noqa_f401", "stale"):
        now = getattr(found, kind)
        for rel, old in (base.get(kind) or {}).items():
            n += max(0, int(old) - now.get(rel, 0))
    return n


def as_baseline(found: Findings, old: dict) -> dict:
    allow = old.get("allow") or {}
    return {
        "说明": "tools/junk_check.py 的老问题登记表：只许减不许加。清掉一条就重写基线（--write-baseline）；allow 里是确实要留的，后面写原因",
        "allow": allow,
        "dead": sorted(k for k in found.dead if k not in allow),
        "test_only": sorted(k for k in found.test_only if k not in allow),
        "dup": sorted(k for k in found.dup if k not in allow),
        "facade": sorted(k for k in found.facade if k not in allow),
        "noqa_f401": dict(sorted(found.noqa_f401.items())),
        "stale": dict(sorted(found.stale.items())),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="垃圾代码检查（只许减不许加）")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--list", action="store_true", help="列出现在全部的（含已登记的）")
    ap.add_argument("--write-baseline", action="store_true", help="把基线写成现在这样")
    args = ap.parse_args(argv)
    baseline_path = args.baseline or (args.root / "tools" / "junk_baseline.json")
    found = scan(args.root)
    base = load_baseline(baseline_path)
    if args.list:
        for kind in ("dead", "test_only", "dup", "facade", "noqa_f401", "stale"):
            items = getattr(found, kind)
            print(f"== {LABELS[kind]}（{len(items)}）")
            for k, v in sorted(items.items()):
                print(f"  {k}  {v}")
        return 0
    if args.write_baseline:
        new = as_baseline(found, base)
        for kind in ("dead", "test_only", "dup", "facade"):
            added = set(new[kind]) - set(base.get(kind) or [])
            gone = set(base.get(kind) or []) - set(new[kind])
            if added:
                print(
                    f"基线新增 {LABELS[kind]} {len(added)} 条（PR 里要写原因）：{sorted(added)[:5]}"
                )
            if gone:
                print(f"基线清掉 {LABELS[kind]} {len(gone)} 条")
        baseline_path.write_text(
            json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"基线写到 {baseline_path}")
        return 0
    new = compare(found, base)
    known = {k: len(base.get(k) or []) for k in ("dead", "test_only", "dup", "facade")}
    print(
        "已登记的老问题（只许减不许加）："
        + "、".join(f"{LABELS[k]} {n}" for k, n in known.items())
        + f"、noqa F401 {sum((base.get('noqa_f401') or {}).values())} 处、过时说法 {sum((base.get('stale') or {}).values())} 处"
    )
    gone = tightenable(found, base)
    if gone:
        print(
            f"基线里有 {gone} 处已经清掉了：跑 --write-baseline 把基线收紧，再一起提交"
        )
    if new:
        print(f"垃圾代码检查：发现 {len(new)} 处新的")
        for line in new:
            print("  " + line)
        return 1
    print("垃圾代码检查：没有新的")
    return 0


if __name__ == "__main__":
    sys.exit(main())
