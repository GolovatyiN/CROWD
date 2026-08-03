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

    # ---- ready-link verification worker ----
    link_check_enabled: bool = True
    link_check_interval_hours: int = 24        # periodic re-check cadence
    link_check_concurrency: int = 4            # max simultaneous checks
    link_check_domain_delay_sec: float = 3.0   # politeness gap per donor domain
    link_check_poll_sec: int = 30              # worker wake interval
    link_check_batch: int = 20                 # checks claimed per pass
    link_check_max_attempts: int = 5           # transient retries before manual


settings = Settings()
