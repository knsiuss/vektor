from modules.widgets.repository import is_origin_allowed


def test_origin_allowed_empty_list_permits_any() -> None:
    assert is_origin_allowed("https://shop.example.com", []) is True
    assert is_origin_allowed(None, []) is True


def test_origin_allowed_exact_wildcard_and_port() -> None:
    allowed = ["tokoku.com", "*.tokoku.com", "localhost"]
    assert is_origin_allowed("https://tokoku.com/checkout", allowed) is True
    assert is_origin_allowed("https://shop.tokoku.com", allowed) is True
    assert is_origin_allowed("localhost:3000", allowed) is True
    assert is_origin_allowed("http://localhost:3000", allowed) is True
    assert is_origin_allowed("https://evil.com", allowed) is False
    assert is_origin_allowed(None, allowed) is False
