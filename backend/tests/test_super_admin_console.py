import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Branch, Transaction, User, UserRoleEnum
from app.core.security import hash_password, verify_password

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_super_admin_data():
    init_db()
    db = SessionLocal()
    try:
        # Create Super Admin if not exists
        sa = db.query(User).filter(User.username == "console_superadmin").first()
        if not sa:
            sa = User(
                username="console_superadmin",
                email="admin@saas-platform.jo",
                full_name="رئيس مجلس إدارة المنصة",
                hashed_password=hash_password("ConsoleMasterKey123!"),
                role=UserRoleEnum.SUPER_ADMIN,
                is_active=True
            )
            db.add(sa)

        # Create a sample organization with subscription
        sample_org = db.query(Organization).filter(Organization.name == "شركة تجريبية للكونسول").first()
        if not sample_org:
            sample_org = Organization(
                name="شركة تجريبية للكونسول",
                industry_type="retail",
                tax_number="998877665",
                is_tax_registered=True,
                subscription_plan="PRO",
                subscription_status="ACTIVE",
                subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                subscription_price_jod=59.0,
                contact_email="manager@testconsole.jo",
                contact_phone="0799998877",
                is_active=True
            )
            db.add(sample_org)
            db.commit()
            db.refresh(sample_org)

            # Add sample manager
            mgr = User(
                organization_id=sample_org.id,
                username="mgr_testconsole",
                email="manager@testconsole.jo",
                full_name="مدير شركة الكونسول",
                hashed_password=hash_password("MgrOldPass123"),
                role=UserRoleEnum.ORG_ADMIN,
                is_active=True
            )
            db.add(mgr)

            # Add sample transaction
            tx = Transaction(
                organization_id=sample_org.id,
                transaction_type="SALE",
                total_amount=150.750
            )
            db.add(tx)

        db.commit()
    finally:
        db.close()


def get_super_admin_headers():
    login_res = client.post("/api/v1/auth/login", json={
        "username": "console_superadmin",
        "password": "ConsoleMasterKey123!"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_platform_summary_metrics():
    headers = get_super_admin_headers()
    res = client.get("/api/v1/admin/platform-summary", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_organizations" in data
    assert "active_subscriptions" in data
    assert "total_sales_volume" in data
    assert data["total_organizations"] >= 1
    assert data["total_sales_volume"] >= 150.0


def test_list_organizations_with_subscription_details():
    headers = get_super_admin_headers()
    res = client.get("/api/v1/admin/organizations", headers=headers)
    assert res.status_code == 200
    orgs = res.json()
    target_org = next((o for o in orgs if o["name"] == "شركة تجريبية للكونسول"), None)
    assert target_org is not None
    assert target_org["subscription_plan"] == "PRO"
    assert target_org["subscription_status"] == "ACTIVE"
    assert target_org["days_remaining"] > 0
    assert target_org["subscription_price_jod"] == 59.0
    assert target_org["total_sales"] >= 150.0
    assert target_org["admin_user"] is not None
    assert target_org["admin_user"]["username"] == "mgr_testconsole"


def test_create_and_update_tenant_organization():
    headers = get_super_admin_headers()
    create_payload = {
        "name": "مخبز القدس الآلي",
        "industry_type": "bakery",
        "tax_number": "123123123",
        "currency": "JOD",
        "branches": ["فرع الشميساني", "فرع عبدون"],
        "admin_username": "jerusalem_bakery_admin",
        "admin_password": "BakerySecret123!",
        "admin_full_name": "سامر الحلبي",
        "subscription_plan": "BASIC",
        "subscription_duration_months": 6,
        "subscription_price_jod": 29.0,
        "contact_email": "samer@bakery.jo",
        "contact_phone": "0788887766"
    }
    create_res = client.post("/api/v1/admin/organizations", headers=headers, json=create_payload)
    assert create_res.status_code == 200
    org_id = create_res.json()["organization_id"]

    # Verify update
    update_res = client.put(f"/api/v1/admin/organizations/{org_id}", headers=headers, json={
        "subscription_plan": "ENTERPRISE",
        "subscription_price_jod": 99.0
    })
    assert update_res.status_code == 200

    # Verify toggle status (suspend)
    toggle_res = client.post(f"/api/v1/admin/organizations/{org_id}/toggle-status", headers=headers)
    assert toggle_res.status_code == 200
    assert toggle_res.json()["is_active"] is False
    assert toggle_res.json()["subscription_status"] == "SUSPENDED"

    # Verify toggle back to active
    toggle_res2 = client.post(f"/api/v1/admin/organizations/{org_id}/toggle-status", headers=headers)
    assert toggle_res2.status_code == 200
    assert toggle_res2.json()["is_active"] is True

    # Delete organization
    del_res = client.delete(f"/api/v1/admin/organizations/{org_id}", headers=headers)
    assert del_res.status_code == 200


def test_super_admin_update_own_profile_and_password():
    headers = get_super_admin_headers()
    update_res = client.put("/api/v1/admin/profile", headers=headers, json={
        "full_name": "المهندس المالك المحدث",
        "email": "owner.updated@platform.jo",
        "current_password": "ConsoleMasterKey123!",
        "new_password": "ConsoleMasterKeyNew456!"
    })
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["user"]["full_name"] == "المهندس المالك المحدث"
    assert data["user"]["email"] == "owner.updated@platform.jo"

    # Verify login with new password
    new_login = client.post("/api/v1/auth/login", json={
        "username": "console_superadmin",
        "password": "ConsoleMasterKeyNew456!"
    })
    assert new_login.status_code == 200

    # Restore original password for stability
    new_token = new_login.json()["access_token"]
    restore_res = client.put("/api/v1/admin/profile", headers={"Authorization": f"Bearer {new_token}"}, json={
        "current_password": "ConsoleMasterKeyNew456!",
        "new_password": "ConsoleMasterKey123!"
    })
    assert restore_res.status_code == 200


def test_tenant_direct_password_reset():
    headers = get_super_admin_headers()
    db = SessionLocal()
    mgr = db.query(User).filter(User.username == "mgr_testconsole").first()
    mgr_id = mgr.id
    db.close()

    res = client.post(f"/api/v1/admin/users/{mgr_id}/reset-password", headers=headers, json={
        "new_password": "DirectNewPass789!"
    })
    assert res.status_code == 200

    # Verify manager can login with new password
    mgr_login = client.post("/api/v1/auth/login", json={
        "username": "mgr_testconsole",
        "password": "DirectNewPass789!"
    })
    assert mgr_login.status_code == 200


def test_tenant_password_reset_link_and_public_endpoint():
    headers = get_super_admin_headers()
    db = SessionLocal()
    mgr = db.query(User).filter(User.username == "mgr_testconsole").first()
    mgr_id = mgr.id
    db.close()

    # Super Admin generates reset link
    gen_res = client.post(f"/api/v1/admin/users/{mgr_id}/generate-reset-link", headers=headers)
    assert gen_res.status_code == 200
    link_data = gen_res.json()
    reset_token = link_data["reset_token"]
    assert reset_token != ""
    assert "reset_url" in link_data

    # User opens link and resets password via public endpoint
    reset_res = client.post("/api/v1/auth/reset-password", json={
        "token": reset_token,
        "new_password": "LinkResetPass999!"
    })
    assert reset_res.status_code == 200

    # Verify manager can now login with the new password
    login_after_link = client.post("/api/v1/auth/login", json={
        "username": "mgr_testconsole",
        "password": "LinkResetPass999!"
    })
    assert login_after_link.status_code == 200

    # Verify token cannot be reused
    reuse_res = client.post("/api/v1/auth/reset-password", json={
        "token": reset_token,
        "new_password": "ShouldFailPass123!"
    })
    assert reuse_res.status_code == 400
