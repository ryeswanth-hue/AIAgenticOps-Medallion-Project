from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = f"sqlite:///{BASE_DIR}/data/aiops.db"
    bronze_data_path: str = str(BASE_DIR / "data" / "bronze")
    silver_data_path: str = str(BASE_DIR / "data" / "silver")
    gold_data_path: str = str(BASE_DIR / "data" / "gold")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    claude_model: str = "claude-opus-5"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
