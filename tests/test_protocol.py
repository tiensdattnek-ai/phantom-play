import struct

import pytest

from phantom.protocol import (
    HEADER, H264Parser, InputError, pack_media, unpack_media, validate_input, VIDEO_KEY,
)


def nal(t, payload=b"\x00"):
    return bytes([t]) + payload


def au(*nals):
    return b"".join(b"\x00\x00\x00\x01" + n for n in nals)


def test_media_header_roundtrip():
    payload = b"abc"
    data = pack_media(VIDEO_KEY, 7, 123456, payload)
    kind, seq, pts, out = unpack_media(data)
    assert kind == VIDEO_KEY and seq == 7 and pts == 123456 and out == payload
    assert len(data) == HEADER.size + len(payload)


def test_h264_parser_avcc_and_keyframe():
    p = H264Parser()
    sps = nal(7, b"\x42\xe0\x1e")
    pps = nal(8, b"\x00")
    idr = nal(5, b"\x88\x01")
    delta = nal(1, b"\x88\x01")
    stream = au(nal(9, b"\xf0"), sps, pps, idr) + au(nal(9, b"\xf0"), delta) + au(nal(9, b"\xf0"))
    units = p.feed(stream)
    assert len(units) >= 1
    assert units[0].key
    assert p.avcc is not None
    assert p.codec.startswith("avc1.")
    # AVCC sample contains VCL NALs; SPS/PPS are in avcC description.
    ln = struct.unpack(">I", units[0].data[:4])[0]
    assert ln == len(idr)


def test_validate_mouse_and_key():
    m = validate_input({"type": "mouse", "mode": "relative", "dx": 5, "dy": -3, "buttons": 1})
    assert m["dx"] == 5
    k = validate_input({"type": "key", "code": "KeyW", "down": True})
    assert k["code"] == "KeyW"
    with pytest.raises(InputError):
        validate_input({"type": "key", "code": "Bad", "down": True})
    with pytest.raises(InputError):
        validate_input({"type": "mouse", "mode": "relative", "dx": 9999})


def test_gamepad_validation():
    m = validate_input({"type": "gamepad", "axes": [0, 0.5, -1, 1], "buttons": [1, 0]})
    assert len(m["buttons"]) == 2
    with pytest.raises(InputError):
        validate_input({"type": "gamepad", "axes": [0, 0], "buttons": []})
