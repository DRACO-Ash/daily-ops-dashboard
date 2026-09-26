import os
from typing import List
from urllib.parse import quote

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str
    app_allowed_origins: List[str] = Field(default_factory=list)

    # POSTGRES_* is the local compose convention; PG* is what the
    # Bluestaq App Store PostgreSQL add-on injects. Either works.
    postgres_host: str = Field(validation_alias=AliasChoices("POSTGRES_HOST", "PGHOST"))
    postgres_port: int = Field(
        default=5432, validation_alias=AliasChoices("POSTGRES_PORT", "PGPORT")
    )
    postgres_db: str = Field(validation_alias=AliasChoices("POSTGRES_DB", "PGDATABASE"))
    postgres_user: str = Field(validation_alias=AliasChoices("POSTGRES_USER", "PGUSER"))
    postgres_password: str = Field(validation_alias=AliasChoices("POSTGRES_PASSWORD", "PGPASSWORD"))

    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    mattermost_url: str = ""
    mattermost_bot_token: str = ""
    mattermost_team_id: str = ""
    mattermost_poll_interval: int = 60
    # Comma-separated list of Mattermost channel IDs to poll. Channels
    # the bot account isn't a member of are silently skipped (Mattermost
    # rejects the GET with a 403).
    mattermost_channel_ids: str = ""
    mattermost_interval_seconds: int = 60
    mattermost_prompt_window_hours: int = 6
    mattermost_max_messages_in_prompt: int = 30

    udl_base_url: str = "https://unifieddatalibrary.com/udl"
    udl_username: str = ""
    udl_password: str = ""
    udl_request_timeout_seconds: int = 30
    udl_verify_ssl: bool = True

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 4096

    # Defaults under the App Store file-storage mount (STORAGE_MOUNT_PATH,
    # normally /data) so uploads survive pod restarts.
    procedure_storage_path: str = Field(
        default_factory=lambda: os.path.join(
            os.environ.get("STORAGE_MOUNT_PATH", "/data"), "procedures"
        )
    )

    # Built frontend bundle served by the backend in the single-container
    # deployment. Absent in local dev, where Vite serves the frontend.
    static_dir: str = "/app/static"

    background_refresh_enabled: bool = True
    background_auto_evaluate: bool = True
    background_max_evaluations_per_cycle: int = 20
    background_max_event_summaries_per_cycle: int = 20

    # Per-surface cadences. Notifications change slowly and we want a
    # wide picture (5 days), so they refresh hourly. Maneuvers and
    # elsets are time-critical at the satellite level and stay on a
    # 10-minute cycle.
    background_notification_interval_seconds: int = 3600
    background_notification_window_hours: int = 120
    background_maneuver_interval_seconds: int = 600
    background_maneuver_window_hours: int = 48

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
