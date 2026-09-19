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

        try:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE users ADD COLUMN is_primary_owner BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass

    # Seed default subscription plans if table is empty
    with SessionLocal() as db_session:
        from app.models.schema import SubscriptionPlan
        try:
            if db_session.query(SubscriptionPlan).count() == 0:
                default_plans = [
                    SubscriptionPlan(
                        code="TRIAL",
                        name="الخطة التجريبية (Free Trial)",
                        description="فترة تجريبية مجانية لمدة 14 يوماً مع كافة ميزات الفوترة والامتثال الضريبي",
                        price_monthly_jod=0.0,
                        price_annual_jod=0.0,
                        max_branches=1,
                        max_users=2,
                        max_transactions_monthly=100,
                        has_telegram_bot=False,
                        has_jofotara_qr=True,
                        has_ai_daily_brief=True,
                        has_tax_reports=True,
                        badge_color="amber",
                        is_active=True
                    ),
                    SubscriptionPlan(
                        code="BASIC",
                        name="الخطة الأساسية (Basic)",
                        description="مناسبة للمتاجر الصغيرة ونقاط البيع الفردية مع فواتير JoFotara المعتمدة",
                        price_monthly_jod=29.0,
                        price_annual_jod=290.0,
                        max_branches=1,
                        max_users=3,
                        max_transactions_monthly=1000,
                        has_telegram_bot=False,
                        has_jofotara_qr=True,
                        has_ai_daily_brief=True,
                        has_tax_reports=True,
                        badge_color="sky",
                        is_active=True
                    ),
                    SubscriptionPlan(
                        code="PRO",
                        name="الخطة الاحترافية (Pro)",
                        description="الخيار الأمثل للمطاعم والأنشطة التجارية المتوسطة مع بوت تلغرام مخصص",
                        price_monthly_jod=49.0,
                        price_annual_jod=490.0,
                        max_branches=3,
                        max_users=10,
                        max_transactions_monthly=5000,
                        has_telegram_bot=True,
                        has_jofotara_qr=True,
                        has_ai_daily_brief=True,
                        has_tax_reports=True,
                        badge_color="emerald",
                        is_active=True
                    ),
                    SubscriptionPlan(
                        code="ENTERPRISE",
                        name="خطة الشركات والمجموعات (Enterprise)",
                        description="حل متكامل للشركات ذات الفروع المتعددة وحجم العمليات غير المحدود مع دعم فني مخصص",
                        price_monthly_jod=99.0,
                        price_annual_jod=990.0,
                        max_branches=-1,
                        max_users=-1,
                        max_transactions_monthly=-1,
                        has_telegram_bot=True,
                        has_jofotara_qr=True,
                        has_ai_daily_brief=True,
                        has_tax_reports=True,
                        badge_color="purple",
                        is_active=True
                    )
                ]
                db_session.add_all(default_plans)
                db_session.commit()
        except Exception:
            db_session.rollback()

        from app.models.schema import PlatformSupportContact
        try:
            contact = db_session.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
            if not contact:
                contact = PlatformSupportContact(
                    id="default",
                    support_phone="+962 7 9000 0000",
                    support_whatsapp="962790000000",
                    support_email="support@smartops.jo",
                    working_hours="يومياً من 9:00 صباحاً حتى 10:00 مساءً",
                    support_notes="فريق الدعم الفني جاهز لمساعدتكم في استعادة الحساب وتأكيد بيانات المنشأة عبر واتساب أو الهاتف.",
                    is_active=True
                )
                db_session.add(contact)
                db_session.commit()
        except Exception:
            db_session.rollback()

        from app.models.schema import User, UserRoleEnum
        try:
            primary = db_session.query(User).filter(User.is_primary_owner == True).first()
            if not primary:
                super_user = db_session.query(User).filter(
                    (User.username == "superadmin") | (User.email == "yazeedbaniissa@gmail.com")
                ).first()
                if not super_user:
                    super_user = db_session.query(User).filter(User.role == UserRoleEnum.SUPER_ADMIN).order_by(User.created_at.asc()).first()
                if super_user:
                    super_user.is_primary_owner = True
                    db_session.commit()
        except Exception:
            db_session.rollback()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
