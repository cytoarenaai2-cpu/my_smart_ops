import os
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "smart_ops.db").replace(os.sep, "/")

class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Ops and Compliance Assistant"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    DEFAULT_CURRENCY: str = "JOD"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    LEGAL_DISCLAIMER: str = (
        "هذا التقرير تم توليده آلياً لدعم القرار الإداري والتشغيلي والتحضير للمحاسب القانوني، "
        "ولا يُعتبر إقراراً ضريبياً رسمياً بديلاً عن الإقرار المعتمد لدى دائرة ضريبة الدخل والمبيعات الأردنية."
    )

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

settings = Settings()
