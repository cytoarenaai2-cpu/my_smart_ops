import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Branch, Transaction, User, UserRoleEnum
from app.core.security import hash_password

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_test_data():
    init_db()
    db = SessionLocal()
    try:
        # Ensure Super Admin exists
        sa = db.query(User).filter(User.username == "test_superadmin").first()
        if not sa:
            sa = User(
                username="test_superadmin",
                full_name="Super Admin Tester",
                email="super@platform.local",
                hashed_password=hash_password("SuperSecret123!"),
                role=UserRoleEnum.SUPER_ADMIN,
                is_active=True
            )
            db.add(sa)
        else:
            sa.hashed_password = hash_password("SuperSecret123!")

        # Create Tenant Org A
        org_a = db.query(Organization).filter(Organization.name == "مطعم التجربة أ").first()
        if not org_a:
            org_a = Organization(
                name="مطعم التجربة أ",
                industry_type="restaurant",
                tax_number="111222333",
                is_tax_registered=True,
                telegram_bot_token="bot_token_a_123",
                auto_daily_brief_enabled=True,
                daily_brief_time="08:00",
                contact_email="contact@orga.jo"
            )
            db.add(org_a)
            db.commit()
            db.refresh(org_a)

        # User A
        user_a = db.query(User).filter(User.username == "admin_org_a").first()
        if not user_a:
            user_a = User(
                organization_id=org_a.id,
                username="admin_org_a",
                full_name="مدير منشأة أ",
                email="admin_org_a@rawsheh.jo",
                hashed_password=hash_password("PassA@123"),
                role=UserRoleEnum.ORG_ADMIN,
                is_active=True
            )
            db.add(user_a)
        else:
            user_a.hashed_password = hash_password("PassA@123")
            user_a.email = "admin_org_a@rawsheh.jo"

        # Create Tenant Org B
        org_b = db.query(Organization).filter(Organization.name == "سوبرماركت التجربة ب").first()
        if not org_b:
            org_b = Organization(
                name="سوبرماركت التجربة ب",
                industry_type="retail",
                tax_number="444555666",
                is_tax_registered=True,
                telegram_bot_token="bot_token_b_456",
                auto_daily_brief_enabled=True,
                daily_brief_time="09:00",
                contact_email="contact@orgb.jo"
            )
            db.add(org_b)
            db.commit()
            db.refresh(org_b)

        # User B
        user_b = db.query(User).filter(User.username == "admin_org_b").first()
        if not user_b:
            user_b = User(
                organization_id=org_b.id,
                username="admin_org_b",
                full_name="مدير منشأة ب",
                email="admin_org_b@baraka.jo",
                hashed_password=hash_password("PassB@123"),
                role=UserRoleEnum.ORG_ADMIN,
                is_active=True
            )
            db.add(user_b)
        else:
            user_b.hashed_password = hash_password("PassB@123")
            user_b.email = "admin_org_b@baraka.jo"

        db.commit()
    finally:
        db.close()


def test_login_success_and_jwt():
    res = client.post("/api/v1/auth/login", json={"username": "test_superadmin", "password": "SuperSecret123!"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["role"] == UserRoleEnum.SUPER_ADMIN


def test_login_invalid_credentials():
    res = client.post("/api/v1/auth/login", json={"username": "test_superadmin", "password": "WrongPassword"})
    assert res.status_code == 401


def test_super_admin_can_access_admin_endpoints():
    login_res = client.post("/api/v1/auth/login", json={"username": "test_superadmin", "password": "SuperSecret123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/admin/organizations", headers=headers)
    assert res.status_code == 200
    orgs = res.json()
    assert len(orgs) >= 2


def test_org_admin_blocked_from_admin_endpoints():
    login_res = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "PassA@123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/admin/organizations", headers=headers)
    assert res.status_code == 403


def test_org_admin_cannot_modify_locked_business_info():
    """التحقق من شرط المستخدم: المنشأة لا تستطيع تغيير الاسم أو النشاط أو الرقم الضريبي أو الفروع"""
    login_res = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "PassA@123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.put("/api/v1/analytics/organization-profile", headers=headers, json={
        "name": "اسم تجاري غير مصرح به",
        "tax_number": "000000000",
        "industry_type": "services"
    })
    assert res.status_code == 403
    assert "محصور بمالك المنصة" in res.json()["detail"]


def test_org_admin_can_modify_briefing_schedule():
    """التحقق من شرط المستخدم: تمكين المنشأة من تخصيص الجدولة الصباحية متى شاءت"""
    login_res = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "PassA@123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.put("/api/v1/analytics/briefing-schedule", headers=headers, json={
        "auto_daily_brief_enabled": True,
        "daily_brief_time": "08:45"
    })
    assert res.status_code == 200
    assert res.json()["daily_brief_time"] == "08:45"


def test_tenant_data_isolation():
    """التحقق من عزل بيانات كل منشأة عن الأخرى بنسبة 100%"""
    login_a = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "PassA@123"})
    token_a = login_a.json()["access_token"]

    login_b = client.post("/api/v1/auth/login", json={"username": "admin_org_b", "password": "PassB@123"})
    org_b_id = login_b.json()["organization"]["id"]

    res = client.get(f"/api/v1/analytics/recent-transactions?organization_id={org_b_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert res.status_code == 403
    assert "منشأة تجارية أخرى" in res.json()["detail"]


def test_login_with_email_success():
    """التحقق من دعم تسجيل الدخول باستخدام البريد الإلكتروني للمستخدم أو المنشأة"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin_org_a").first()
        user.email = "owner_a@testcompany.com"
        db.commit()
    finally:
        db.close()

    res = client.post("/api/v1/auth/login", json={"username": "owner_a@testcompany.com", "password": "PassA@123"})
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["username"] == "admin_org_a"
    assert data["user"]["email"] == "owner_a@testcompany.com"


def test_forgot_password_flow():
    """التحقق من مسار استعادة الحساب ونسيان كلمة المرور عبر الإيميل أو اسم المستخدم"""
    db = SessionLocal()
    try:
        tester = db.query(User).filter(User.username == "forgot_tester_user").first()
        if not tester:
            tester = User(
                username="forgot_tester_user",
                email="forgot_tester@platform.local",
                full_name="Forgot Tester",
                hashed_password=hash_password("OldPass@123"),
                role=UserRoleEnum.CASHIER,
                is_active=True
            )
            db.add(tester)
        else:
            tester.hashed_password = hash_password("OldPass@123")
            tester.email = "forgot_tester@platform.local"
        db.commit()
    finally:
        db.close()

    # 1. طلب الاستعادة بمعرف غير موجود
    res_fail = client.post("/api/v1/auth/forgot-password", json={"identifier": "nonexistent_user_999@test.com"})
    assert res_fail.status_code == 200
    assert res_fail.json()["success"] is False

    # 2. طلب الاستعادة ببريد مستخدم مسجل
    res_ok = client.post("/api/v1/auth/forgot-password", json={"identifier": "forgot_tester@platform.local"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["success"] is True
    assert data["username"] == "forgot_tester_user"
    assert "reset_token" in data
    token = data["reset_token"]

    # 3. استخدام الرمز لتعيين كلمة مرور جديدة
    res_reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewSecretPass@2026"})
    assert res_reset.status_code == 200
    assert "بنجاح" in res_reset.json()["message"]

    # 4. تسجيل الدخول بكلمة المرور الجديدة عبر الإيميل
    res_login = client.post("/api/v1/auth/login", json={"username": "forgot_tester@platform.local", "password": "NewSecretPass@2026"})
    assert res_login.status_code == 200
    assert "access_token" in res_login.json()


