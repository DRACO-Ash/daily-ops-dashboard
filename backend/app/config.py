from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str
    allowed_origins: List[str] = []

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

    udl_base_url: str = "https://unifieddatalibrary.com/udl"
    udl_username: str = ""
    udl_password: str = ""
    udl_request_timeout_seconds: int = 30
    udl_verify_ssl: bool = True

    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()  # type: ignore[call-arg]
