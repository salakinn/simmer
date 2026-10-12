from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/simmer.db"
    max_html_bytes: int = 2 * 1024 * 1024
    max_image_bytes: int = 5 * 1024 * 1024
    request_timeout: float = 10.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
