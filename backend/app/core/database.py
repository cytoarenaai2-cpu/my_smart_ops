from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.schema import Base

engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Safe migration for new columns on SQLite
    with engine.connect() as conn:
        for col, col_type in [
            ("telegram_chat_id", "VARCHAR(50)"),
            ("auto_daily_brief_enabled", "BOOLEAN DEFAULT 1"),
            ("daily_brief_time", "VARCHAR(10) DEFAULT '08:30'")
        ]:
            try:
                from sqlalchemy import text
                conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
