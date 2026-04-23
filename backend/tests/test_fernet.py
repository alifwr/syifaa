import pytest
from cryptography.fernet import Fernet
from app.security import encrypt_secret, decrypt_secret


@pytest.fixture(autouse=True)
def real_fernet_key(monkeypatch):
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    # Reload cached Settings so the new key is observed.
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_encrypt_then_decrypt_roundtrip():
    tok = encrypt_secret("sk-live-1234567890")
    assert tok != "sk-live-1234567890"
    assert decrypt_secret(tok) == "sk-live-1234567890"


def test_encrypt_is_nondeterministic():
    a = encrypt_secret("same")
    b = encrypt_secret("same")
    assert a != b


def test_decrypt_rejects_bogus():
    with pytest.raises(Exception):
        decrypt_secret("not-a-real-fernet-token")
