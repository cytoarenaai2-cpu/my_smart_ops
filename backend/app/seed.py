import uuid
from datetime import date, timedelta
from app.core.database import SessionLocal, init_db
from app.core.config import settings
from app.models.schema import Organization, Branch, Transaction, AuditFlag, User, UserRoleEnum
from app.core.security import hash_password


def seed_demo_data():
    init_db()
    db = SessionLocal()

    try:
        # 1. إنشاء حساب مالك المنصة (SUPER_ADMIN) إن لم يكن موجوداً
        super_admin = db.query(User).filter(User.role == UserRoleEnum.SUPER_ADMIN).first()
        if not super_admin:
            super_admin = User(
                id=str(uuid.uuid4()),
                organization_id=None,
                username="superadmin",
                full_name="مالك المنصة الرئيسي (Super Admin)",
                email="admin@smartops.jo",
                hashed_password=hash_password("SuperAdmin@2026"),
                role=UserRoleEnum.SUPER_ADMIN,
                is_active=True
            )
            db.add(super_admin)
            print("[Seed] Created Super Admin account: superadmin / SuperAdmin@2026")

        # 2. فحص أو تهيئة المنشأة الأولى: مطعم وكافيه الروشة
        org1 = db.query(Organization).filter(Organization.name.ilike("%الروشة%")).first()
        if not org1:
            org1 = db.query(Organization).first()

        if not org1:
            org1 = Organization(
                id=str(uuid.uuid4()),
                name="مطعم وكافيه الروشة",
                industry_type="restaurant",
                currency="JOD",
                tax_number="123456789",
                is_tax_registered=True,
                tax_filing_period="MONTHLY",
                telegram_bot_token=settings.TELEGRAM_BOT_TOKEN or None,
                auto_daily_brief_enabled=True,
                daily_brief_time="08:30",
                is_active=True
            )
            db.add(org1)
            db.commit()
            db.refresh(org1)
            print("[Seed] Created Organization 1: مطعم وكافيه الروشة")
        else:
            # تحديث التوكن والنشاط
            if not org1.telegram_bot_token and settings.TELEGRAM_BOT_TOKEN:
                org1.telegram_bot_token = settings.TELEGRAM_BOT_TOKEN
            org1.tax_number = org1.tax_number or "123456789"
            org1.is_tax_registered = True
            org1.is_active = True
            db.commit()

        # فروع المنشأة 1
        b1_list = db.query(Branch).filter(Branch.organization_id == org1.id).all()
        if not b1_list:
            b1 = Branch(id=str(uuid.uuid4()), organization_id=org1.id, name="الفرع الرئيسي - الصويفية", manager_name="أحمد ناصر")
            b2 = Branch(id=str(uuid.uuid4()), organization_id=org1.id, name="فرع خلدا", manager_name="سامر حداد")
            db.add_all([b1, b2])
            db.commit()

        # مستخدمو المنشأة 1
        if not db.query(User).filter(User.username == "rawsheh_admin").first():
            db.add(User(
                id=str(uuid.uuid4()),
                organization_id=org1.id,
                username="rawsheh_admin",
                full_name="عمر المصري (مدير مطعم الروشة)",
                email="admin@rawsheh.jo",
                hashed_password=hash_password("Admin@123"),
                role=UserRoleEnum.ORG_ADMIN,
                is_active=True
            ))
            print("[Seed] Created User: rawsheh_admin / Admin@123")

        if not db.query(User).filter(User.username == "rawsheh_accountant").first():
            db.add(User(
                id=str(uuid.uuid4()),
                organization_id=org1.id,
                username="rawsheh_accountant",
                full_name="سامي القاسم (محاسب قانوني الروشة)",
                email="acc@rawsheh.jo",
                hashed_password=hash_password("Accountant@123"),
                role=UserRoleEnum.ACCOUNTANT,
                is_active=True
            ))
            print("[Seed] Created User: rawsheh_accountant / Accountant@123")

        if not db.query(User).filter(User.username == "rawsheh_cashier").first():
            db.add(User(
                id=str(uuid.uuid4()),
                organization_id=org1.id,
                username="rawsheh_cashier",
                full_name="خالد التميمي (كاشير الفرع)",
                email="cashier@rawsheh.jo",
                hashed_password=hash_password("Cashier@123"),
                role=UserRoleEnum.CASHIER,
                is_active=True
            ))
            print("[Seed] Created User: rawsheh_cashier / Cashier@123")

        # 3. إنشاء منشأة ثانية لإثبات العزل التام للمنصة السحابية: سوبرماركت البركة للتجزئة
        org2 = db.query(Organization).filter(Organization.name.ilike("%البركة%")).first()
        if not org2:
            org2 = Organization(
                id=str(uuid.uuid4()),
                name="سوبرماركت وأسواق البركة للتجزئة",
                industry_type="retail",
                currency="JOD",
                tax_number="987654321",
                is_tax_registered=True,
                tax_filing_period="MONTHLY",
                auto_daily_brief_enabled=True,
                daily_brief_time="09:00",
                is_active=True
            )
            db.add(org2)
            db.commit()
            db.refresh(org2)

            b2_1 = Branch(id=str(uuid.uuid4()), organization_id=org2.id, name="الفرع الرئيسي - الجبيهة", manager_name="محمود بركات")
            b2_2 = Branch(id=str(uuid.uuid4()), organization_id=org2.id, name="فرع تلاع العلي", manager_name="يوسف الشيخ")
            db.add_all([b2_1, b2_2])

            # مستخدمو المنشأة 2
            db.add(User(
                id=str(uuid.uuid4()),
                organization_id=org2.id,
                username="baraka_admin",
                full_name="فهد البركة (مدير أسواق البركة)",
                email="admin@baraka.jo",
                hashed_password=hash_password("Baraka@123"),
                role=UserRoleEnum.ORG_ADMIN,
                is_active=True
            ))

            db.add(User(
                id=str(uuid.uuid4()),
                organization_id=org2.id,
                username="baraka_cashier",
                full_name="علي صبحي (كاشير البركة)",
                email="cashier@baraka.jo",
                hashed_password=hash_password("Cashier@123"),
                role=UserRoleEnum.CASHIER,
                is_active=True
            ))

            # عمليات تجريبية للمنشأة 2 لإثبات عزل الأرقام
            today = date.today()
            t1 = Transaction(
                id=str(uuid.uuid4()),
                organization_id=org2.id,
                branch_id=b2_1.id,
                transaction_type="SALE",
                transaction_date=today,
                invoice_number="BARAKA-Z-101",
                merchant_or_supplier_name="الفرع الرئيسي - الجبيهة",
                subtotal=850.0,
                tax_amount=136.0,
                total_amount=986.0,
                payment_breakdown={"cash": 486.0, "card": 400.0, "cliq": 100.0, "delivery_apps": 0.0},
                tax_status="STANDARD_16",
                notes="إغلاق كاشير سوبرماركت البركة"
            )
            t2 = Transaction(
                id=str(uuid.uuid4()),
                organization_id=org2.id,
                branch_id=b2_1.id,
                transaction_type="PURCHASE",
                transaction_date=today,
                invoice_number="SUP-INV-882",
                merchant_or_supplier_name="شركة الألبان الوطنية",
                subtotal=320.0,
                tax_amount=51.2,
                total_amount=371.2,
                supplier_tax_id="300455123",
                is_deductible_expense=True,
                payment_breakdown={"card": 371.2},
                tax_status="STANDARD_16",
                notes="فاتورة توريد ألبان وأجبان أسبوعية"
            )
            db.add_all([t1, t2])
            print("[Seed] Created Organization 2: سوبرماركت وأسواق البركة للتجزئة with demo data")

        db.commit()
        print("[Seed] Multi-Tenant SaaS Seeding Completed Successfully!")

    except Exception as e:
        db.rollback()
        print(f"[Seed] Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
