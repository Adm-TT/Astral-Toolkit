"""一键升级：找安装包、检查安装包、覆盖程序文件但不动个人数据"""
import zipfile


def _pkg(path, version, files, top=None):
    top = top or f"Dubhe_{version}"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{top}/sc_mining/__init__.py", "")
        z.writestr(f"{top}/sc_mining/app/server.py", "# server")
        z.writestr(f"{top}/sc_mining/app/services.py", "# services")      # 必需文件清单（老大审查 2026-10-28 第 3 条）
        z.writestr(f"{top}/sc_mining/run.py", "# run")
        z.writestr(f"{top}/sc_mining/version.py", f'VERSION = "{version}"\n')
        for name, text in files.items():
            z.writestr(f"{top}/{name}", text)
    return path


def _install(tmp_path):
    root = tmp_path / "天枢"
    (root / "sc_mining" / "app").mkdir(parents=True)
    (root / "sc_mining" / "__init__.py").write_text("")
    (root / "sc_mining" / "app" / "server.py").write_text("# old server")
    (root / "sc_mining" / "app" / "services.py").write_text("# old services")
    (root / "sc_mining" / "run.py").write_text("# old run")
    (root / "sc_mining" / "version.py").write_text('VERSION = "1.5.0"\n')
    (root / "sc_mining" / "old_module.py").write_text("# 新版本里已经删掉了")
    (root / "userdata").mkdir()
    (root / "userdata" / "settings.json").write_text('{"mine": true}')
    (root / ".venv").mkdir()
    (root / ".venv" / "python.txt").write_text("env")
    (root / "requirements.txt").write_text("mss\n")
    return root


def _setup(monkeypatch, tmp_path):
    from sc_mining.update import upgrade as U
    root = _install(tmp_path)
    monkeypatch.setattr(U, "ROOT", root)
    monkeypatch.setattr(U, "STAMP", root / "userdata" / "upgraded.json")
    monkeypatch.setattr(U, "VERSION", "1.5.0")
    monkeypatch.setattr(U, "BACKUPS", root / "userdata" / "backups")      # 备份别写到真实的 userdata
    monkeypatch.setattr(U, "STABLE", root / "userdata" / "stable")
    monkeypatch.setattr(U, "_search_dirs", lambda: [])
    return U, root


def test_find_newer_packages(monkeypatch, tmp_path):
    U, root = _setup(monkeypatch, tmp_path)
    dl = tmp_path / "Downloads"
    (dl / "群文件").mkdir(parents=True)
    _pkg(dl / "Dubhe_1.4.9.zip", "1.4.9", {})           # 旧的不要
    _pkg(dl / "Dubhe_1.6.0.zip", "1.6.0", {})
    _pkg(dl / "群文件" / "Dubhe_1.10.0.zip", "1.10.0", {})   # 1.10 比 1.6 新（不是按字母比）
    (dl / "别的.zip").write_bytes(b"x")
    monkeypatch.setattr(U, "_search_dirs", lambda: [(dl, "下载", 1)])
    found = U.find_packages()
    assert [f["version"] for f in found] == ["1.10.0", "1.6.0"] and found[0]["where"] == "下载"


def test_check_rejects_bad_packages(tmp_path):
    import pytest
    from sc_mining.update import upgrade as U
    (tmp_path / "Dubhe_9.0.0.zip").write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        U.check(tmp_path / "Dubhe_9.0.0.zip")                       # 没下载完
    with zipfile.ZipFile(tmp_path / "Dubhe_9.0.1.zip", "w") as z:
        z.writestr("Dubhe_9.0.1/readme.txt", "hi")
    with pytest.raises(ValueError):
        U.check(tmp_path / "Dubhe_9.0.1.zip")                       # 不是天枢
    p = _pkg(tmp_path / "Dubhe_9.0.2.zip", "9.0.2", {"../evil.py": "x"})
    with pytest.raises(ValueError):
        U.check(p)                                                  # 可疑路径
    assert U.check(_pkg(tmp_path / "Dubhe_9.0.3.zip", "9.0.3", {}))[1] == (9, 0, 3)


def test_apply_keeps_personal_data(monkeypatch, tmp_path):
    U, root = _setup(monkeypatch, tmp_path)
    p = _pkg(tmp_path / "Dubhe_1.6.0.zip", "1.6.0", {
        "sc_mining/goals.py": "# new feature", "requirements.txt": "mss\n",
        "userdata/settings.json": '{"mine": false}',          # 包里就算带了 userdata 也不能覆盖
        "Dubhe.exe": "exe", "使用说明.txt": "新说明"})
    r = U.apply(p, progress=lambda *a: None)
    assert r == {"from": "1.5.0", "to": "1.6.0", "deps": False}
    assert (root / "sc_mining" / "app" / "server.py").read_text() == "# server"
    assert (root / "sc_mining" / "goals.py").exists() and (root / "使用说明.txt").read_text(encoding="utf-8") == "新说明"
    assert not (root / "sc_mining" / "old_module.py").exists()           # 新版本删掉的旧代码清掉
    assert (root / "userdata" / "settings.json").read_text() == '{"mine": true}'
    assert (root / ".venv" / "python.txt").exists()
    assert U.just_upgraded()["to"] == "1.6.0" and U.just_upgraded() is None   # 只提示一次


def test_apply_installs_new_dependencies(monkeypatch, tmp_path):
    U, root = _setup(monkeypatch, tmp_path)
    calls = []
    import sc_mining.run as run
    monkeypatch.setattr(run, "_pip", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(run, "_has_directml", lambda: False)          # 别按本机装没装显卡版走不同的路
    monkeypatch.setattr(run, "_pip_uninstall", lambda *a: calls.append(("uninstall",) + a) or True)
    p = _pkg(tmp_path / "Dubhe_1.6.0.zip", "1.6.0", {"requirements.txt": "mss\nnewlib\n"})
    assert U.apply(p, progress=lambda *a: None)["deps"] and calls and calls[0][0] == "-r"
    assert len(calls) == 1                                            # 原来没装显卡版：不动识别组件


def _fake_pip(monkeypatch, ok=True):
    """假 pip：记下装 / 卸的顺序，不真去装"""
    import sc_mining.run as run
    calls = []
    monkeypatch.setattr(run, "_pip", lambda *a: calls.append(("install",) + a) or (ok if "onnxruntime-directml" in a else True))
    monkeypatch.setattr(run, "_pip_uninstall", lambda *a: calls.append(("uninstall",) + a) or True)
    return run, calls


def test_use_directml_installs_before_uninstalling_cpu(monkeypatch):
    run, calls = _fake_pip(monkeypatch)
    assert run.use_directml()
    assert calls == [("install", "onnxruntime-directml"), ("uninstall", "onnxruntime"),
                     ("install", "--force-reinstall", "--no-deps", "onnxruntime-directml")]


def test_use_directml_keeps_cpu_when_install_fails(monkeypatch):
    run, calls = _fake_pip(monkeypatch, ok=False)
    assert run.use_directml() is False
    assert calls == [("install", "onnxruntime-directml")]             # 显卡版没装上：CPU 版不卸


def test_use_directml_restores_cpu_when_reinstall_fails(monkeypatch):
    """CPU 版已经卸了、显卡版强制重装又失败：把 CPU 版装回来，返回 False"""
    import sc_mining.run as run
    calls = []
    monkeypatch.setattr(run, "_pip", lambda *a: calls.append(("install",) + a) or "--force-reinstall" not in a)
    monkeypatch.setattr(run, "_pip_uninstall", lambda *a: calls.append(("uninstall",) + a) or True)
    assert run.use_directml() is False
    assert calls[-1] == ("install", "onnxruntime")
    assert calls == [("install", "onnxruntime-directml"), ("uninstall", "onnxruntime"),
                     ("install", "--force-reinstall", "--no-deps", "onnxruntime-directml"), ("install", "onnxruntime")]


def test_apply_reinstalls_directml_after_requirements(monkeypatch, tmp_path):
    U, root = _setup(monkeypatch, tmp_path)
    run, calls = _fake_pip(monkeypatch)
    monkeypatch.setattr(run, "_has_directml", lambda: True)
    p = _pkg(tmp_path / "Dubhe_1.6.0.zip", "1.6.0", {"requirements.txt": "mss\nnewlib\n"})
    assert U.apply(p, progress=lambda *a: None)["deps"]
    assert calls[0] == ("install", "-r", str(root / "requirements.txt"))
    assert calls[1:] == [("install", "onnxruntime-directml"), ("uninstall", "onnxruntime"),
                         ("install", "--force-reinstall", "--no-deps", "onnxruntime-directml")]



def test_upgrade_backs_up_and_rollback_restores(monkeypatch, tmp_path):
    """升级前自动备份当前版本；新版本出问题回滚到备份：程序文件恢复成旧的，个人数据不动（稳定性要求 2026-10-23）"""
    U, root = _setup(monkeypatch, tmp_path)
    new = _pkg(tmp_path / "Dubhe_1.6.0.zip", "1.6.0", {"sc_mining/app/server.py": "# new server", "requirements.txt": "mss\n"})
    U.apply(new, progress=lambda m: None)
    assert (root / "sc_mining" / "app" / "server.py").read_text() == "# new server"
    backup = root / "userdata" / "backups" / "Dubhe_1.5.0.zip"
    assert backup.exists() and U.check(backup)[1] == (1, 5, 0)
    with zipfile.ZipFile(backup) as z:                                    # 备份里没有个人数据
        assert not [n for n in z.namelist() if "/userdata/" in n or "/.venv/" in n]
    monkeypatch.setattr(U, "VERSION", "1.6.0")                      # 相当于升级后重启
    opts = U.rollback_options()
    assert [o["version"] for o in opts] == ["1.5.0"] and opts[0]["where"] == "升级前自动备份"
    (root / "userdata" / "settings.json").write_text('{"mine": "after"}')
    U.apply(backup, progress=lambda m: None)
    assert (root / "sc_mining" / "app" / "server.py").read_text() == "# old server"
    assert 'VERSION = "1.5.0"' in (root / "sc_mining" / "version.py").read_text()            # 磁盘上的版本号也回去了
    assert (root / "sc_mining" / "old_module.py").exists()                                    # 新版删掉的旧模块也回来了
    left = [p.name for p in (root / "userdata" / "backups").glob("Dubhe_*.zip")]
    assert left == ["Dubhe_1.6.0.zip"]                                    # 回滚时也备份了刚才的新版，只留这一个
    assert (root / "userdata" / "settings.json").read_text() == '{"mine": "after"}'   # 个人数据不动
    assert (root / ".venv" / "python.txt").exists()
    # 存稳定版：永远保留，排在最前面
    stable = U.mark_stable()
    assert stable.parent.name == "stable" and U.rollback_options()[0]["stable"]
    # 自动备份只留上一个版本
    import time as _t
    for i in range(7):
        monkeypatch.setattr(U, "VERSION", f"1.4.{i}")
        U.backup_current()
        _t.sleep(0.05)
    left = sorted(p.name for p in (root / "userdata" / "backups").glob("Dubhe_*.zip"))
    assert left == ["Dubhe_1.4.6.zip"]                                   # 自动备份只留上一个版本



def test_rollback_to_oldest_backup_survives_cleanup(monkeypatch, tmp_path):
    """回滚到备份里的版本：装之前的备份清理会删掉它，也要能装上（Codex 复审 2026-10-23）"""
    import os, time as _t  # noqa: E401
    U, root = _setup(monkeypatch, tmp_path)
    bdir = root / "userdata" / "backups"
    bdir.mkdir(parents=True)
    for i in range(5):
        _pkg(bdir / f"Dubhe_1.4.{i}.zip", f"1.4.{i}", {"sc_mining/app/server.py": f"# v1.4.{i}"})
        os.utime(bdir / f"Dubhe_1.4.{i}.zip", (_t.time() - 100 + i, _t.time() - 100 + i))
    oldest = bdir / "Dubhe_1.4.0.zip"
    U.apply(oldest, progress=lambda m: None)
    assert (root / "sc_mining" / "app" / "server.py").read_text() == "# v1.4.0"


def test_backup_failure_aborts_without_touching_files(monkeypatch, tmp_path):
    """备份不成功就不装（不然新版出问题时没有退路），程序文件一点不动"""
    import pytest
    U, root = _setup(monkeypatch, tmp_path)
    new = _pkg(tmp_path / "Dubhe_1.6.0.zip", "1.6.0", {"sc_mining/extra.py": "# new"})
    def boom(*a, **k):
        raise OSError("磁盘满了")
    monkeypatch.setattr(U, "backup_current", boom)
    with pytest.raises(ValueError) as e:
        U.apply(new, progress=lambda m: None)
    assert "没有改动" in str(e.value)
    assert (root / "sc_mining" / "app" / "server.py").read_text() == "# old server"
    assert not (root / "sc_mining" / "extra.py").exists()


def test_adopt_previous_package_after_first_upgrade(monkeypatch, tmp_path):
    """从没有备份功能的旧版本（1.6.18 及以前）升上来：重启后在下载里找到旧版安装包，收进备份，回滚列表里就有它"""
    U, root = _setup(monkeypatch, tmp_path)
    dl = tmp_path / "Downloads"
    dl.mkdir()
    _pkg(dl / "Dubhe_1.4.9.zip", "1.4.9", {})
    monkeypatch.setattr(U, "_search_dirs", lambda: [(dl, "下载", 1)])
    got = U.adopt_previous("1.4.9")
    assert got and got.parent.name == "backups" and U.adopt_previous("1.4.9") is None     # 第二次不重复复制
    assert any(o["version"] == "1.4.9" and o["where"] == "升级前自动备份" and o["action"] == "回滚到"
               for o in U.rollback_options())


def test_beta_backup_shows_in_rollback(monkeypatch, tmp_path):
    """beta 版的备份、稳定版文件名带完整版本号，回滚列表看得到；同号的 beta 和正式版是两个包，不能互相顶掉
    （S5 审查 2026-10-31：以前 beta 的备份打好了列表里看不到；第 2 轮复审：只用三位数命名会让 beta 和正式版撞名，
    从 beta.2 升到同号正式版时拿更旧的 beta.1 备份当退路，稳定版也会被同号的另一版覆盖）"""
    U, root = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(U, "VERSION", "1.5.0-beta.1")
    assert U.backup_current().name == "Dubhe_1.5.0-beta.1.zip"
    assert [(o["version"], o["action"]) for o in U.rollback_options()] == [("1.5.0-beta.1", "重新安装")]
    monkeypatch.setattr(U, "VERSION", "1.5.0-beta.2")                  # 升到 beta.2 之后
    assert [(o["version"], o["action"]) for o in U.rollback_options()] == [("1.5.0-beta.1", "回滚到")]
    assert U.mark_stable().name == "Dubhe_1.5.0-beta.2.zip"
    live = _pkg(tmp_path / "Dubhe_1.5.0.zip", "1.5.0", {"sc_mining/app/server.py": "# live"})
    U.apply(live, progress=lambda m: None)                           # beta.2 → 同号正式版：要另打 beta.2 的备份
    assert [p.name for p in (root / "userdata" / "backups").glob("Dubhe_*.zip")] == ["Dubhe_1.5.0-beta.2.zip"]
    monkeypatch.setattr(U, "VERSION", "1.5.0")
    U.mark_stable()
    assert sorted(p.name for p in (root / "userdata" / "stable").glob("*.zip")) == ["Dubhe_1.5.0-beta.2.zip", "Dubhe_1.5.0.zip"]
    rows = [(o["version"], o["action"], o["stable"]) for o in U.rollback_options()]
    assert rows[0] == ("1.5.0", "重新安装", True) and ("1.5.0-beta.2", "回滚到", False) in rows
    dl = tmp_path / "Downloads"                                       # 升级记录里存的是完整版本号：按完整版本号找包
    dl.mkdir()
    _pkg(dl / "Dubhe_1.4.9.zip", "1.4.9", {})
    _pkg(dl / "Dubhe_1.4.9-beta.3.zip", "1.4.9-beta.3", {})
    monkeypatch.setattr(U, "_search_dirs", lambda: [(dl, "下载", 1)])
    got = U.adopt_previous("1.4.9-beta.3")
    assert got and got.name == "Dubhe_1.4.9-beta.3.zip" and U.adopt_previous("1.4.9-beta.3") is None
    assert [r["version"] for r in U.find_packages()] == []                # 都比 1.5.0 旧
