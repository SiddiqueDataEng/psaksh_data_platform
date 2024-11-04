"""
Centralised settings using pydantic-settings.
Reads from environment variables and .env file.

Environments:
  local       — SQLite (no Docker needed)
  staging     — MySQL on remote server
  production  — MySQL on remote server (same host, same DB for this project)
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    db_host:     str = "localhost"
    db_port:     int = 3306
    db_name:     str = "psaksh_warehouse"
    db_user:     str = "psaksh_user"
    db_password: str = "changeme"

    # AWS (optional — only needed for cloud S3 features)
    aws_region:            str = "us-east-1"
    aws_access_key_id:     Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    s3_bucket:             str = "psaksh-data-lake"
    s3_raw_prefix:         str = "raw/"
    s3_processed_prefix:   str = "processed/"
    s3_output_prefix:      str = "output/"

    # SurveyCTO (optional)
    surveycto_server:   Optional[str] = None
    surveycto_user:     Optional[str] = None
    surveycto_password: Optional[str] = None
    surveycto_form_ids: str = "household_enrollment,followup_visit,facility_assessment"

    # App
    env:       str = "local"
    log_level: str = "INFO"

    @property
    def db_url(self) -> str:
        """MySQL connection URL for staging/production."""
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    @property
    def db_url_local_sqlite(self) -> str:
        """SQLite fallback for local dev without MySQL."""
        return "sqlite:///psaksh_local.db"

    @property
    def surveycto_form_id_list(self) -> list[str]:
        return [f.strip() for f in self.surveycto_form_ids.split(",")]

    @property
    def is_local(self) -> bool:
        return self.env == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
