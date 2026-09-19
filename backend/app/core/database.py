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
            ("daily_brief_time", "VARCHAR(10) DEFAULT '08:30'"),
            ("telegram_bot_token", "VARCHAR(100)"),
            ("is_active", "BOOLEAN DEFAULT 1"),
            ("subscription_plan", "VARCHAR(50) DEFAULT 'PRO'"),
            ("subscription_status", "VARCHAR(30) DEFAULT 'ACTIVE'"),
            ("subscription_expires_at", "DATETIME"),
            ("subscription_price_jod", "FLOAT DEFAULT 0.0"),
            ("contact_email", "VARCHAR(255)"),
            ("contact_phone", "VARCHAR(50)")
        ]:
            try:
                from sqlalchemy import text
                conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass

        for col, col_type in [
            ("reset_token", "VARCHAR(255)"),
            ("reset_token_expires_at", "DATETIME")
        ]:
            try:
                from sqlalchemy import text
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass

        try:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE transactions ADD COLUMN service_charge FLOAT DEFAULT 0.0"))
            conn.commit()
        except Exception:
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
