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

    # ---- disk retention / maintenance ----
    # Append-only history tables grow forever; a daily pass ages them out so the
    # volume can't slowly refill. Current verification STATE lives in link_checks
    # (one row/placement), so link_check_results is pure history and safe to trim.
    # Any *_retention_days / keep set to 0 disables that particular rule.
    retention_enabled: bool = True
    retention_run_hours: int = 24                     # how often the pass runs
    retention_startup_delay_sec: int = 300            # wait after boot before first pass
    retention_delete_batch: int = 5000                # rows per delete chunk (bounded locks)
    link_check_results_retention_days: int = 90       # keep this many days of check history
    link_check_results_keep_per_placement: int = 50   # …and at most N most-recent per placement
    notifications_retention_days: int = 120           # old notifications
    import_logs_retention_days: int = 180             # old import logs
    audit_logs_retention_days: int = 365              # audit trail — kept longer

    # Whether the client cabinet exposes problem statuses (link gone/anchor
    # changed) as "проблема", or masks them as "на проверке". Default: mask.
    client_shows_problems: bool = False


settings = Settings()
