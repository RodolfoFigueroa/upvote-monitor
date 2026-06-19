from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upvote_monitor_secret_key: str | None = None
    cors_dev: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
