import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-xxxxxxx")
os.environ.setdefault("FERNET_KEY", "0123456789abcdef0123456789abcdef0123456789AB=")
