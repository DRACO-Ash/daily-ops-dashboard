from typing import List
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str
    app_allowed_origins: List[str] = Field(default_factory=list)

    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    mattermost_url: str = ""
    mattermost_bot_token: str = ""
    mattermost_team_id: str = ""
    mattermost_poll_interval: int = 60

    udl_base_url: str = "https://unifieddatalibrary.com/udl"
    udl_username: str = ""
    udl_password: str = ""
    udl_request_timeout_seconds: int = 30
    udl_verify_ssl: bool = True

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 2048

    procedure_storage_path: str = "/data/procedures"

    background_refresh_enabled: bool = True
    background_refresh_interval_seconds: int = 600
    background_refresh_window_hours: int = 48
    background_auto_evaluate: bool = True
    background_max_evaluations_per_cycle: int = 20

    @property
    def database_url(self) -> str:
        # Percent-encode user and password so reserved characters
        # (% ! @ : / + and friends) survive the round-trip into a
        # valid Postgres URL.
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()  # type: ignore[call-arg]
