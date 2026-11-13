"""数据包（2026-10-26）：从 AT 服务器 / 国内镜像 / GitHub 下载 AT 整理好的数据；连不上时只更新行情（不联网：换掉 _open）"""

import hashlib
import io
import json
import threading  # noqa: F401
import zipfile


class _Resp(io.BytesIO):
    headers = {}


def _setup(monkeypatch, tmp_path, pages):
    from astral_toolkit.update import data_pack as P, update_check as U

    monkeypatch.setattr(U, "GITHUB", "at/at")
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "STAMP", tmp_path / "data" / "data_pack.json")
    from astral_toolkit.core import paths

    monkeypatch.setattr(
        paths, "DATA", tmp_path / "data"
    )  # 装完会重建游戏数据库：也指向临时目录，别碰真实 data/
    (tmp_path / "data").mkdir(exist_ok=True)

    def fake_open(url, timeout):
        v = pages.get(url)
        if v is None:
            raise OSError("连不上")
        return _Resp(v)

    monkeypatch.setattr(U, "_open", fake_open)
    return P


def _pack(tmp_path, files, version="2026.10.26-1200"):
    zp = tmp_path / f"AT_data_{version}.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for n, text in files.items():
            z.writestr(n, text)
    data = zp.read_bytes()
    m = {
        "version": version,
        "file": zp.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "urls": [
            f"https://dl.astral-trade.com/releases/data-{version}/{zp.name}",
            f"https://github.com/at/at/releases/download/data-{version}/{zp.name}",
        ],
    }
    return data, m


def test_update_from_mirror_installs_listed_files_only(monkeypatch, tmp_path):
    data, m = _pack(
        tmp_path,
        {
            "shops.json": '{"items": {}}',
            "starmap.json": "[]",
            "../evil.json": "{}",
            "notes.txt": "x",
        },
    )
    P = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/data.json": json.dumps(
                m
            ).encode(),
            m["urls"][0]: data,
        },
    )
    assert P.update(progress=lambda *_: None) is True
    d = tmp_path / "data"
    assert (
        json.loads((d / "shops.json").read_text()) == {"items": {}}
        and (d / "starmap.json").exists()
    )
    assert (
        not (d / "evil.json").exists()
        and not (d / "notes.txt").exists()
        and not (tmp_path / "evil.json").exists()
    )
    assert P.local_version() == "2026.10.26-1200"
    assert P.update(progress=lambda *_: None) is True  # 再点一次：已是最新，不再下载


def test_bad_checksum_falls_back_to_github_mirror(monkeypatch, tmp_path):
    data, m = _pack(tmp_path, {"prices.json": '{"prices": {}}'})
    P = _setup(
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/data.json": json.dumps(
                m
            ).encode(),
            m["urls"][0]: data[:-3] + b"xyz",
            m["urls"][1]: data,
        },
    )
    assert (
        P.update(progress=lambda *_: None) is True
        and (tmp_path / "data" / "prices.json").exists()
    )


def test_unreachable_returns_none_and_run_falls_back(monkeypatch, tmp_path):
    P = _setup(monkeypatch, tmp_path, {})
    assert P.update(progress=lambda *_: None) is None
    from astral_toolkit import run
    from astral_toolkit.update import uex, localization
    from astral_toolkit.crafting import build_crafting
    from astral_toolkit.update import loot as loot_index
    from astral_toolkit.update import shops

    called = []
    for mod, fn in (
        (localization, "update"),
        (uex, "refresh"),
        (build_crafting, "update"),
        (shops, "update"),
        (loot_index, "update"),
    ):
        monkeypatch.setattr(
            mod, fn, (lambda n: lambda *a, **k: called.append(n))(mod.__name__)
        )
    r = run.update()
    # 数据包连不上：只更新汉化包和行情（矿价、商店）；制造、掉落不去别的网站下（2026-11-13）；数据包那项不算失败、不出现在结果里（老大定）
    assert sorted(called) == sorted(
        [localization.__name__, uex.__name__, shops.__name__]
    )
    assert r["total"] == 3 and r["ok"] == 3
    assert "数据包" not in [x["title"] for x in r["results"]]
    called.clear()
    r = run.update(
        direct=True
    )  # 作者发数据包前：行情 + 重编制造 + 掉落索引，不下数据包
    assert len(called) == 5 and r["total"] == r["ok"] == 5


def test_pack_up_to_date_skips_sources(monkeypatch, tmp_path):
    data, m = _pack(tmp_path, {"shops.json": "{}"})
    P = _setup(  # noqa: F841
        monkeypatch,
        tmp_path,
        {
            "https://raw.githubusercontent.com/at/at/main/data.json": json.dumps(
                m
            ).encode(),
            m["urls"][0]: data,
        },
    )  # noqa: F841
    from astral_toolkit import run
    from astral_toolkit.update import uex, localization

    called = []
    monkeypatch.setattr(localization, "update", lambda *a, **k: called.append("loc"))
    monkeypatch.setattr(uex, "refresh", lambda *a, **k: called.append("uex"))
    r = run.update()
    assert (
        called == ["loc"] and r["ok"] == r["total"] == 2
    )  # 汉化包 + 数据包，不再去各网站


def test_parse_rejects_bad_manifest():
    from astral_toolkit.update import data_pack as P

    good = {
        "version": "2026.10.26-1200",
        "file": "AT_data_2026.10.26-1200.zip",
        "sha256": "a" * 64,
        "urls": ["https://github.com/x/y/z.zip"],
    }
    assert P.parse(json.dumps(good))["version"] == "2026.10.26-1200"
    for bad in (
        {**good, "file": "x.exe"},
        {**good, "urls": ["https://evil.com/a.zip"]},
        {**good, "version": "latest"},
    ):
        try:
            P.parse(json.dumps(bad))
            assert False, bad
        except ValueError:
            pass


def _loot_zip(path, version, items):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("version.txt", version)
        for u, d in items.items():
            z.writestr(f"{u}.json", json.dumps(d))
    return path


def test_loot_detail_reads_bundle_first(monkeypatch, tmp_path):
    """掉落明细只查整包（版本对得上才用）和老版本留下的单件缓存；都没有就说没有，不联网（2026-11-13）"""
    from astral_toolkit.core import net
    from astral_toolkit.infrastructure.persistence import loot_details
    from astral_toolkit.tasks.catalog_queries import loot
    from tests.minipytest import raises

    monkeypatch.setattr(
        loot_details,
        "DETAILS",
        _loot_zip(tmp_path / "loot_details.zip", "4.10.2LIVE", {"u1": {"a": 1}}),
    )
    monkeypatch.setattr(loot_details, "CACHE_DIR", tmp_path / "loot")
    monkeypatch.setattr(
        loot_details, "_zip", {"z": None, "mtime": None, "version": None}
    )
    monkeypatch.setattr(loot, "_index_meta", lambda: {"version": "4.10.2LIVE"})
    sent = []
    monkeypatch.setattr(net, "read", lambda *a, **k: sent.append(a) or b"{}")
    assert (
        loot.detail("u1") == {"a": 1} and loot_details.details_version() == "4.10.2LIVE"
    )
    with raises(loot.NoDetail):  # 整包里没有：不现查
        loot.detail("u2")
    (tmp_path / "loot").mkdir()
    (tmp_path / "loot" / "4.10.2LIVE_u2.json").write_text(
        '{"old": 1}', encoding="utf-8"
    )
    assert loot.detail("u2") == {"old": 1}  # 老版本联网存下的单件缓存照样读
    monkeypatch.setattr(loot, "_index_meta", lambda: {"version": "4.11.0LIVE"})
    with raises(loot.NoDetail):  # 游戏版本变了：旧整包、旧缓存都不用
        loot.detail("u1")
    assert sent == []


def test_data_pack_downloads_loot_bundle_only_when_version_changes(
    monkeypatch, tmp_path
):
    from astral_toolkit.infrastructure.persistence import loot_details

    data, m = _pack(tmp_path, {"shops.json": "{}"})
    lz = _loot_zip(
        tmp_path / "AT_loot_4.10.2LIVE.zip", "4.10.2LIVE", {"u1": {"a": 1}}
    ).read_bytes()
    m["loot"] = {
        "version": "4.10.2LIVE",
        "file": "AT_loot_4.10.2LIVE.zip",
        "size": len(lz),
        "sha256": hashlib.sha256(lz).hexdigest(),
        "urls": ["https://dl.astral-trade.com/releases/data-x/AT_loot_4.10.2LIVE.zip"],
    }
    hits = []
    pages = {
        "https://raw.githubusercontent.com/at/at/main/data.json": json.dumps(
            m
        ).encode(),
        m["urls"][0]: data,
        m["loot"]["urls"][0]: lz,
    }
    P = _setup(monkeypatch, tmp_path, pages)
    from astral_toolkit.update import update_check as U

    real = U._open
    monkeypatch.setattr(U, "_open", lambda url, t: (hits.append(url), real(url, t))[1])
    monkeypatch.setattr(loot_details, "DETAILS", tmp_path / "data" / "loot_details.zip")
    assert P.update(progress=lambda *_: None) is True
    assert (
        loot_details.details_version() == "4.10.2LIVE"
        and sum("AT_loot" in h for h in hits) == 1
    )
    assert (
        P.update(progress=lambda *_: None) is True
        and sum("AT_loot" in h for h in hits) == 1
    )  # 版本没变不再下


def test_crawl_stops_on_rate_limit(monkeypatch, tmp_path):
    """全速抓掉落明细：对方限流（429）就停，不生成整包"""
    import urllib.error
    from astral_toolkit.infrastructure.persistence import loot_details
    from astral_toolkit.update import loot as loot_index
    from astral_toolkit.core import net

    monkeypatch.setattr(
        loot_index,
        "update",
        lambda version=None, progress=print: {
            "version": "4.10.2LIVE",
            "rows": [[f"u{i}"] for i in range(40)],
        },
    )

    def fake_read(req, timeout=60):
        if req.full_url.endswith("u5.json"):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return b'{"ok": 1}'

    monkeypatch.setattr(net, "read", fake_read)
    try:
        loot_index.crawl_details(out=tmp_path / "x.zip", workers=2, progress=None)
        assert False
    except RuntimeError as e:
        assert "429" in str(e)
    assert not (tmp_path / "x.zip").exists() and not (tmp_path / "x.part").exists()
    monkeypatch.setattr(net, "read", lambda req, timeout=60: b'{"ok": 1}')
    ok, bad, v = loot_index.crawl_details(
        out=tmp_path / "x.zip", workers=4, progress=None
    )
    assert (
        ok == 40
        and bad == 0
        and loot_details.details_version(tmp_path / "x.zip") == "4.10.2LIVE"
    )
