"""功能包装配/校验（scripts/build_plugin_pack.py）契约测试。

重点在**篡改检测**：下载器只认 SHA256，装到用户机器上的东西必须能被证明
"就是发布时那一份"。所以这里逐个模拟各种动手脚的方式，断言全部被拒。
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_plugin_pack.py"


@pytest.fixture
def bpp(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_plugin_pack_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    monkeypatch.setattr(module, "PLUGINS_ROOT", plugins_root)
    module.ROOT = tmp_path
    module.DIST_ROOT = tmp_path / "dist"
    return module


def _make_pack(bpp, pack_id: str = "demo", version: str = "1.0.0", *, py: bool = True,
               manifest_id: str | None = None) -> Path:
    pack = bpp.PLUGINS_ROOT / pack_id
    (pack / "py").mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": manifest_id if manifest_id is not None else pack_id,
        "version": version,
        "api_level": 1,
        "min_core": "0.0.0",
        "entry": "demo_pack:register",
        "lifecycle": {"start": "demo_pack:start"},
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    if py:
        (pack / "py" / "demo_pack.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
    return pack


def _rewrite_zip(src: Path, dst: Path, mutate) -> Path:
    """按 mutate(name, data) -> bytes 重写 zip，用来模拟各种篡改。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            data = mutate(name, data)
            if data is not None:
                zout.writestr(name, data)
        extra = getattr(mutate, "extra", None)
        if extra:
            zout.writestr(*extra)
    return dst


# ── 正常路径 ────────────────────────────────────────────

def test_build_and_verify_roundtrip(bpp):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")

    info = bpp.verify_pack(archive)

    assert info["id"] == "demo"
    assert info["version"] == "1.0.0"
    assert info["files"] >= 1
    assert archive.name == "demo-1.0.0.aeriepack"


def test_pack_contains_manifest_and_sums(bpp):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert "pack.json" in names
        assert bpp.SUMS_NAME in names
        sums = zf.read(bpp.SUMS_NAME).decode("utf-8")
        assert "py/demo_pack.py" in sums


def test_bytecode_and_pycache_are_excluded(bpp):
    pack = _make_pack(bpp)
    (pack / "py" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (pack / "py" / "__pycache__" / "demo_pack.cpython-314.pyc").write_bytes(b"junk")
    (pack / "py" / "stale.pyc").write_bytes(b"junk")

    archive = bpp.build_pack("demo")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


# ── 篡改检测 ────────────────────────────────────────────

def test_tampered_file_is_detected(bpp, tmp_path):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")
    bad = _rewrite_zip(
        archive, tmp_path / "bad.aeriepack",
        lambda name, data: data + b"\n# injected\n" if name.endswith(".py") else data,
    )

    with pytest.raises(bpp.PackError) as exc:
        bpp.verify_pack(bad)

    assert "篡改" in str(exc.value)


def test_extra_unlisted_file_is_detected(bpp, tmp_path):
    """往包里塞一个没登记的载荷（不更新 SHA256SUMS）必须被发现。"""
    _make_pack(bpp)
    archive = bpp.build_pack("demo")

    def mutate(name, data):
        return data

    mutate.extra = ("py/backdoor.py", b"print('hi')\n")
    bad = _rewrite_zip(archive, tmp_path / "extra.aeriepack", mutate)

    with pytest.raises(bpp.PackError) as exc:
        bpp.verify_pack(bad)

    assert "未登记" in str(exc.value)


def test_missing_file_is_detected(bpp, tmp_path):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")
    bad = _rewrite_zip(
        archive, tmp_path / "missing.aeriepack",
        lambda name, data: None if name.endswith(".py") else data,
    )

    with pytest.raises(bpp.PackError) as exc:
        bpp.verify_pack(bad)

    assert "没有" in str(exc.value)


def test_missing_sums_is_rejected(bpp, tmp_path):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")
    bad = _rewrite_zip(
        archive, tmp_path / "nosums.aeriepack",
        lambda name, data: None if name == bpp.SUMS_NAME else data,
    )

    with pytest.raises(bpp.PackError) as exc:
        bpp.verify_pack(bad)

    assert bpp.SUMS_NAME in str(exc.value)


# ── 装配前的基础校验 ────────────────────────────────────

def test_missing_py_dir_is_rejected(bpp):
    _make_pack(bpp, py=False)
    # _make_pack(py=False) 仍会建 py/ 目录，这里显式删掉
    (bpp.PLUGINS_ROOT / "demo" / "py").rmdir()

    with pytest.raises(bpp.PackError) as exc:
        bpp.build_pack("demo")

    assert "py/" in str(exc.value)


def test_pack_id_must_match_directory(bpp):
    _make_pack(bpp, pack_id="demo", manifest_id="something-else")

    with pytest.raises(bpp.PackError) as exc:
        bpp.build_pack("demo")

    assert "必须与目录名一致" in str(exc.value)


def test_unknown_pack_is_rejected(bpp):
    with pytest.raises(bpp.PackError) as exc:
        bpp.build_pack("no-such-pack")

    assert "不存在" in str(exc.value)


def test_catalog_entry_carries_sha256_and_size(bpp):
    _make_pack(bpp)
    archive = bpp.build_pack("demo")

    entry = bpp.emit_catalog_entry("demo", archive)

    assert entry["id"] == "demo"
    assert entry["available"] is True
    assert len(entry["sha256"]) == 64
    assert entry["sizeMb"] >= 0
