from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./crowd.db"
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    admin_email: str = "admin@crowd.local"
    admin_password: str = "admin123"
    admin_name: str = "Admin"

    score_tr_weight: float = 40
    score_traffic_weight: float = 20
    score_refdomains_weight: float = 20
    score_backlinks_weight: float = 20


settings = Settings()
