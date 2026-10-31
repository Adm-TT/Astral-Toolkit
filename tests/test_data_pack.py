"""数据包（2026-10-26）：从 Gitee 下载 AT 整理好的数据；连不上时改从各数据网站更新（不联网：换掉 _open）"""
import hashlib
import io
import json
import threading  # noqa: F401
import zipfile


class _Resp(io.BytesIO):
    headers = {}


def _setup(monkeypatch, tmp_path, pages):
    from sc_mining.update import data_pack as P, update_check as U
    monkeypatch.setattr(U, "GITEE", "at/at")
    monkeypatch.setattr(U, "GITHUB", "at/at")
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "STAMP", tmp_path / "data" / "data_pack.json")
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
    m = {"version": version, "file": zp.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
         "urls": [f"https://gitee.com/at/at/releases/download/data-{version}/{zp.name}",
                  f"https://github.com/at/at/releases/download/data-{version}/{zp.name}"]}
    return data, m


def test_update_from_gitee_installs_listed_files_only(monkeypatch, tmp_path):
    data, m = _pack(tmp_path, {"shops.json": '{"items": {}}', "starmap.json": "[]", "../evil.json": "{}", "notes.txt": "x"})
    P = _setup(monkeypatch, tmp_path, {"https://gitee.com/at/at/raw/master/data.json": json.dumps(m).encode(), m["urls"][0]: data})
    assert P.update(progress=lambda *_: None) is True
    d = tmp_path / "data"
    assert json.loads((d / "shops.json").read_text()) == {"items": {}} and (d / "starmap.json").exists()
    assert not (d / "evil.json").exists() and not (d / "notes.txt").exists() and not (tmp_path / "evil.json").exists()
    assert P.local_version() == "2026.10.26-1200"
    assert P.update(progress=lambda *_: None) is True                    # 再点一次：已是最新，不再下载


def test_bad_checksum_falls_back_to_github_mirror(monkeypatch, tmp_path):
    data, m = _pack(tmp_path, {"prices.json": '{"prices": {}}'})
    P = _setup(monkeypatch, tmp_path, {"https://gitee.com/at/at/raw/master/data.json": json.dumps(m).encode(),
                                       m["urls"][0]: data[:-3] + b"xyz", m["urls"][1]: data})
    assert P.update(progress=lambda *_: None) is True and (tmp_path / "data" / "prices.json").exists()


def test_unreachable_returns_none_and_run_falls_back(monkeypatch, tmp_path):
    P = _setup(monkeypatch, tmp_path, {})
    assert P.update(progress=lambda *_: None) is None
    from sc_mining import run
    from sc_mining.update import uex, localization
    from sc_mining.crafting import build_crafting, shops, loot
    from sc_mining.navigation import navigate
    called = []
    for mod, fn in ((localization, "update"), (uex, "refresh"), (build_crafting, "update"), (navigate, "update"),
                    (shops, "update"), (loot, "update")):
        monkeypatch.setattr(mod, fn, (lambda n: (lambda *a, **k: called.append(n)))(mod.__name__))
    r = run.update()
    assert len(called) == 6 and r["total"] == 6 and r["ok"] == 6          # 汉化包 + 5 个数据网站


def test_pack_up_to_date_skips_sources(monkeypatch, tmp_path):
    data, m = _pack(tmp_path, {"shops.json": "{}"})
    P = _setup(monkeypatch, tmp_path, {"https://gitee.com/at/at/raw/master/data.json": json.dumps(m).encode(), m["urls"][0]: data})  # noqa: F841
    from sc_mining import run
    from sc_mining.update import uex, localization
    called = []
    monkeypatch.setattr(localization, "update", lambda *a, **k: called.append("loc"))
    monkeypatch.setattr(uex, "refresh", lambda *a, **k: called.append("uex"))
    r = run.update()
    assert called == ["loc"] and r["ok"] == r["total"] == 2                 # 汉化包 + 数据包，不再去各网站


def test_parse_rejects_bad_manifest():
    from sc_mining.update import data_pack as P
    good = {"version": "2026.10.26-1200", "file": "AT_data_2026.10.26-1200.zip", "sha256": "a" * 64, "urls": ["https://gitee.com/x/y/z.zip"]}
    assert P.parse(json.dumps(good))["version"] == "2026.10.26-1200"
    for bad in ({**good, "file": "x.exe"}, {**good, "urls": ["https://evil.com/a.zip"]}, {**good, "version": "latest"}):
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
    """掉落明细先查整包，版本对得上才用；整包里没有的才联网"""
    from sc_mining.crafting import loot
    monkeypatch.setattr(loot, "DETAILS", _loot_zip(tmp_path / "loot_details.zip", "4.10.2LIVE", {"u1": {"a": 1}}))
    monkeypatch.setattr(loot, "CACHE_DIR", tmp_path / "loot")
    monkeypatch.setattr(loot, "_zip", {"z": None, "mtime": None, "version": None})
    monkeypatch.setattr(loot, "load_index", lambda auto=True: {"version": "4.10.2LIVE", "rows": []})
    monkeypatch.setattr(loot, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("不该联网")))
    assert loot.detail("u1") == {"a": 1} and loot.details_version() == "4.10.2LIVE"
    monkeypatch.setattr(loot, "_get", lambda url, timeout=60: {"net": url.endswith("u2.json")})
    assert loot.detail("u2") == {"net": True}                              # 整包里没有：现查
    monkeypatch.setattr(loot, "load_index", lambda auto=True: {"version": "4.11.0LIVE", "rows": []})
    monkeypatch.setattr(loot, "_get", lambda url, timeout=60: {"new": True})
    assert loot.detail("u1") == {"new": True}                             # 游戏版本变了：旧整包不用


def test_data_pack_downloads_loot_bundle_only_when_version_changes(monkeypatch, tmp_path):
    from sc_mining.crafting import loot
    data, m = _pack(tmp_path, {"shops.json": "{}"})
    lz = _loot_zip(tmp_path / "AT_loot_4.10.2LIVE.zip", "4.10.2LIVE", {"u1": {"a": 1}}).read_bytes()
    m["loot"] = {"version": "4.10.2LIVE", "file": "AT_loot_4.10.2LIVE.zip", "size": len(lz), "sha256": hashlib.sha256(lz).hexdigest(),
                 "urls": ["https://gitee.com/at/at/releases/download/data-x/AT_loot_4.10.2LIVE.zip"]}
    hits = []
    pages = {"https://gitee.com/at/at/raw/master/data.json": json.dumps(m).encode(), m["urls"][0]: data, m["loot"]["urls"][0]: lz}
    P = _setup(monkeypatch, tmp_path, pages)
    from sc_mining.update import update_check as U
    real = U._open
    monkeypatch.setattr(U, "_open", lambda url, t: (hits.append(url), real(url, t))[1])
    monkeypatch.setattr(loot, "DETAILS", tmp_path / "data" / "loot_details.zip")
    assert P.update(progress=lambda *_: None) is True
    assert loot.details_version() == "4.10.2LIVE" and sum("AT_loot" in h for h in hits) == 1
    assert P.update(progress=lambda *_: None) is True and sum("AT_loot" in h for h in hits) == 1   # 版本没变不再下


def test_crawl_stops_on_rate_limit(monkeypatch, tmp_path):
    """全速抓掉落明细：对方限流（429）就停，不生成整包"""
    import urllib.error
    from sc_mining.crafting import loot
    from sc_mining.core import net
    monkeypatch.setattr(loot, "update", lambda version=None, progress=print: {"version": "4.10.2LIVE", "rows": [[f"u{i}"] for i in range(40)]})

    def fake_read(req, timeout=60):
        if req.full_url.endswith("u5.json"):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return b'{"ok": 1}'
    monkeypatch.setattr(net, "read", fake_read)
    try:
        loot.crawl_details(out=tmp_path / "x.zip", workers=2, progress=None)
        assert False
    except RuntimeError as e:
        assert "429" in str(e)
    assert not (tmp_path / "x.zip").exists() and not (tmp_path / "x.part").exists()
    monkeypatch.setattr(net, "read", lambda req, timeout=60: b'{"ok": 1}')
    ok, bad, v = loot.crawl_details(out=tmp_path / "x.zip", workers=4, progress=None)
    assert ok == 40 and bad == 0 and loot.details_version(tmp_path / "x.zip") == "4.10.2LIVE"
