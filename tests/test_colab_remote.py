import argparse
import base64
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("colab_remote", ROOT / "scripts" / "colab_remote.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def test_chrome_cmd_is_colab_safe():
    cmd = cr.chrome_cmd("/usr/bin/google-chrome-stable", "https://example.com", 1280, 720)
    assert "--no-sandbox" in cmd
    assert "--disable-dev-shm-usage" in cmd
    assert any(x.startswith("--user-data-dir=") for x in cmd)
    assert cmd[-1] == "https://example.com"
    kiosk = cr.chrome_cmd("chrome", "https://example.com", 800, 600, kiosk=True)
    assert "--kiosk" in kiosk
    app = cr.chrome_cmd("chrome", "https://example.com", 800, 600, app=True)
    assert "--app=https://example.com" in app


def test_obtain_password_policy(monkeypatch):
    monkeypatch.delenv("PHANTOM_REMOTE_PASSWORD", raising=False)
    monkeypatch.delenv("PHANTOM_PASSWORD", raising=False)
    pw, generated = cr.obtain_password(argparse.Namespace(password=""))
    assert generated and len(pw) >= 12
    pw, generated = cr.obtain_password(argparse.Namespace(password="ManhKhau123"))
    assert not generated and pw == "ManhKhau123"
    with pytest.raises(SystemExit):
        cr.obtain_password(argparse.Namespace(password="short"))


def test_notebook_is_self_contained():
    p = ROOT / "colab" / "PhantomPlay_Colab.ipynb"
    nb = json.loads(p.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    src = "".join(nb["cells"][3]["source"])
    assert "BUNDLE_B64" in src
    b64 = src.split('BUNDLE_B64 = """')[1].split('"""')[0]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as z:
        names = set(z.namelist())
    assert "scripts/colab_remote.py" in names
    assert "scripts/actions_remote.py" in names
    assert "phantom/server.py" in names
    assert "web/player.js" in names


def test_build_script_bundle_paths_exist():
    build_spec = importlib.util.spec_from_file_location("build_colab_notebook", ROOT / "scripts" / "build_colab_notebook.py")
    build = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build)
    for item in build.BUNDLE_PATHS:
        assert (ROOT / item).exists(), item
