from app.services.storage import Storage


async def test_put_get_delete_roundtrip(s3_bucket):
    s = Storage()
    key = "papers/roundtrip.bin"
    await s.put_object(key, b"hello world", content_type="application/octet-stream")
    got = await s.get_object(key)
    assert got == b"hello world"
    await s.delete_object(key)


async def test_get_missing_raises_keyerror(s3_bucket):
    s = Storage()
    import pytest
    with pytest.raises(KeyError):
        await s.get_object("papers/does-not-exist")


async def test_presigned_get_returns_string(s3_bucket):
    s = Storage()
    key = "papers/presigned.bin"
    await s.put_object(key, b"x")
    url = await s.presigned_get(key, expires=60)
    assert isinstance(url, str) and url.startswith("http")
