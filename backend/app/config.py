from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    jwt_secret: str
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 30
    fernet_key: str
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/auth/google/callback"
    frontend_origin: str = "http://localhost:3000"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "syifa-papers"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    paper_chunk_max_tokens: int = 800
    paper_chunk_overlap: int = 100
    concept_edge_top_k: int = 5
    concept_edge_min_cosine: float = 0.75
    paper_max_bytes: int = 50_000_000
    cookie_secure: bool = False
    feynman_max_turns: int = 60

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
