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


def test_support_contact_and_recovery_flow():
    """التحقق من منظومة قنوات الدعم الفني وتحديثها واستعادة الحساب عبر مالك المنصة"""
    # 1. فحص النقطة العامة لجلب قنوات الدعم المتاحة لشاشة تسجيل الدخول
    res_public = client.get("/api/v1/auth/support-contact")
    assert res_public.status_code == 200
    pub_data = res_public.json()
    assert "support_phone" in pub_data
    assert "support_whatsapp" in pub_data
    assert "support_email" in pub_data

    # 2. مالك المنصة يحدث قنوات الدعم الفني
    login_sa = client.post("/api/v1/auth/login", json={"username": "test_superadmin", "password": "SuperSecret123!"})
    sa_token = login_sa.json()["access_token"]
    sa_headers = {"Authorization": f"Bearer {sa_token}"}

    update_res = client.put("/api/v1/admin/support-contact", headers=sa_headers, json={
        "support_phone": "+962 7 9999 1111",
        "support_whatsapp": "962799991111",
        "support_email": "custom_support@platform.jo",
        "working_hours": "على مدار الساعة 24/7",
        "support_notes": "دعم فني واستعادة فورية لكلمات المرور"
    })
    assert update_res.status_code == 200
    assert update_res.json()["contact"]["support_whatsapp"] == "962799991111"

    # 3. التحقق من انعكاس التحديث على النقطة العامة لشاشة الدخول
    res_public_after = client.get("/api/v1/auth/support-contact")
    assert res_public_after.status_code == 200
    assert res_public_after.json()["support_whatsapp"] == "962799991111"
    assert res_public_after.json()["support_phone"] == "+962 7 9999 1111"

    # 4. منع المستخدم العادي من تعديل قنوات الدعم
    login_user = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "PassA@123"})
    user_token = login_user.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    res_blocked = client.put("/api/v1/admin/support-contact", headers=user_headers, json={
        "support_phone": "+962 7 0000 0000"
    })
    assert res_blocked.status_code == 403

    # 5. استعادة الحساب الآمنة: مالك المنصة يولد رابط إعادة تعيين 24 ساعة للمستخدم بعد التواصل
    db = SessionLocal()
    try:
        user_to_reset = db.query(User).filter(User.username == "admin_org_a").first()
        user_id = user_to_reset.id
    finally:
        db.close()

    res_link = client.post(f"/api/v1/admin/users/{user_id}/generate-reset-link", headers=sa_headers)
    assert res_link.status_code == 200
    link_data = res_link.json()
    assert "reset_token" in link_data
    token = link_data["reset_token"]

    # 6. استخدام الرمز المشفر لإعادة تعيين كلمة المرور
    res_reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewVerifiedPass@2026"})
    assert res_reset.status_code == 200

    # 7. تسجيل الدخول بكلمة المرور الجديدة
    res_new_login = client.post("/api/v1/auth/login", json={"username": "admin_org_a", "password": "NewVerifiedPass@2026"})
    assert res_new_login.status_code == 200
    assert "access_token" in res_new_login.json()



