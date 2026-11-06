from phantom.security import RateLimiter, SessionManager, generate_password, hash_password, verify_password


def test_password_roundtrip():
    pw = "correct horse battery staple"
    h = hash_password(pw)
    assert verify_password(pw, h)
    assert not verify_password("wrong", h)
    assert h.startswith("scrypt$")


def test_generated_password_length():
    assert len(generate_password()) >= 10


def test_session_expiry_and_revoke():
    m = SessionManager(ttl_hours=1)
    s = m.issue("127.0.0.1")
    assert m.get(s.sid) is s
    m.revoke(s.sid)
    assert m.get(s.sid) is None


def test_rate_limiter():
    rl = RateLimiter(limit=2, window=60, global_limit=10)
    assert rl.check("a")[0]
    assert rl.check("a")[0]
    ok, retry = rl.check("a")
    assert not ok and retry > 0
    assert rl.check("b")[0]
