import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("actions_remote", ROOT / "scripts" / "actions_remote.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


def test_parse_resolution():
    assert ar.parse_resolution("1280x720") == (1280, 720)
    assert ar.parse_resolution("1920x1080") == (1920, 1080)
    with pytest.raises(SystemExit):
        ar.parse_resolution("bad")
    with pytest.raises(SystemExit):
        ar.parse_resolution("100x100")


def test_bitrate_scales():
    assert ar.bitrate_for(1280, 720, 24) == 2500
    assert ar.bitrate_for(1920, 1080, 24) == 6000
    assert ar.bitrate_for(1280, 720, 15) < ar.bitrate_for(1280, 720, 30)


def test_quick_tunnel_url_regex():
    assert ar.URL_RE.fullmatch("https://abc-def.trycloudflare.com")
    assert not ar.URL_RE.fullmatch("http://abc.trycloudflare.com")
    assert not ar.URL_RE.fullmatch("https://example.com")


def test_workflow_is_manual_and_bounded():
    d = yaml.safe_load((ROOT / ".github" / "workflows" / "remote-desktop.yml").read_text())
    # PyYAML 1.1 may parse bare `on` as True; accept both.
    triggers = d.get("on", d.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    job = d["jobs"]["remote"]
    assert job["timeout-minutes"] <= 360
    assert job["runs-on"] == "${{ matrix.os }}"
    assert "inputs.target" in job["strategy"]["matrix"]["os"]
    assert d["permissions"]["contents"] == "read"
    steps = job["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("Wait for public URL" in n for n in names)
    assert any("Cleanup" in n for n in names)
    cred = next(s for s in steps if s.get("name", "").startswith("Upload connection info"))
    assert cred["with"]["retention-days"] == 1


def test_http_json_retryable_on_network_error():
    status, data, text = ar.http_json("http://127.0.0.1:1/nope", timeout=0.2)
    assert status == 599
    assert data == {}
