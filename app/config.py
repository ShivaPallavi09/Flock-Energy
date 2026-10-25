from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration settings loaded from environment or defaults."""
    
    # Portal Credentials & Configuration
    portal_base_url: str = Field(
        default="https://urja-ops.flockenergy.tech",
        description="Base URL of the legacy Urja Meter Ops portal",
        validation_alias="PORTAL_BASE_URL"
    )
    portal_email: str = Field(
        default="operator@urja.local",
        description="Operator email used for authenticating with Urja portal",
        validation_alias="PORTAL_EMAIL"
    )
    portal_password: str = Field(
        default="urja-ops-2026",
        description="Operator password used for authenticating with Urja portal",
        validation_alias="PORTAL_PASSWORD"
    )
    
    # Service Network & Cache Configuration
    request_timeout: float = Field(
        default=15.0,
        description="HTTP request timeout in seconds for portal communications",
        validation_alias="REQUEST_TIMEOUT"
    )
    cache_ttl_seconds: int = Field(
        default=300,
        description="Time-to-live for the in-memory meter and DT cache in seconds (5 minutes default)",
        validation_alias="CACHE_TTL_SECONDS"
    )
    
    # Server Configuration
    api_title: str = "Flock Energy — Urja Meter Ops Modern REST API"
    api_version: str = "1.0.0"
    api_description: str = (
        "High-performance, clean REST API wrapper over the legacy Urja Meter Ops web portal. "
        "Automates SvelteKit session authentication, normalizes inconsistent legacy and v2 meter schemas, "
        "provides rich consumption analytics, fast spatial filtering, and full network hierarchy reconstruction."
    )
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of configuration settings."""
    return Settings()
