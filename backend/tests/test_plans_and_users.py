import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal, init_db
from app.models.schema import User, Organization, SubscriptionPlan, UserRoleEnum
from app.core.security import create_access_token, hash_password

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    init_db()
    yield

def get_auth_header(username: str, role: str = UserRoleEnum.SUPER_ADMIN, org_id: str = None):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            hashed_password=hash_password("Pass@123"),
            full_name=f"Test {username}",
            role=role,
            organization_id=org_id,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role})
    db.close()
    return {"Authorization": f"Bearer {token}"}

def test_list_plans_contains_default_seeded_plans():
    headers = get_auth_header("superadmin_test", UserRoleEnum.SUPER_ADMIN)
    res = client.get("/api/v1/admin/plans", headers=headers)
    assert res.status_code == 200
    plans = res.json()
    codes = [p["code"] for p in plans]
    assert "TRIAL" in codes
    assert "BASIC" in codes
    assert "PRO" in codes
    assert "ENTERPRISE" in codes

def test_create_and_update_subscription_plan():
    headers = get_auth_header("superadmin_test", UserRoleEnum.SUPER_ADMIN)
    
    # 1. Create
    payload = {
        "code": "TEST_VIP",
        "name": "باقة كبار الشخصيات التجريبية",
        "description": "خطة خاصة باختبارات النظام",
        "price_monthly_jod": 79.5,
        "price_annual_jod": 795.0,
        "max_branches": 5,
        "max_users": 15,
        "max_transactions_monthly": 10000,
        "has_telegram_bot": True,
        "has_jofotara_qr": True,
        "has_ai_daily_brief": True,
        "has_tax_reports": True,
        "badge_color": "purple",
        "is_active": True
    }
    create_res = client.post("/api/v1/admin/plans", json=payload, headers=headers)
    assert create_res.status_code == 200
    plan_id = create_res.json()["plan_id"]
    assert plan_id is not None

    # 2. Update
    update_res = client.put(f"/api/v1/admin/plans/{plan_id}", json={
        "name": "باقة كبار الشخصيات المحدثة",
        "price_monthly_jod": 85.0
    }, headers=headers)
    assert update_res.status_code == 200

    # 3. Verify
    get_res = client.get("/api/v1/admin/plans", headers=headers)
    updated_plan = next(p for p in get_res.json() if p["id"] == plan_id)
    assert updated_plan["name"] == "باقة كبار الشخصيات المحدثة"
    assert updated_plan["price_monthly_jod"] == 85.0

    # 4. Delete
    del_res = client.delete(f"/api/v1/admin/plans/{plan_id}", headers=headers)
    assert del_res.status_code == 200

def test_super_admin_create_tenant_user():
    headers = get_auth_header("superadmin_test", UserRoleEnum.SUPER_ADMIN)
    
    # Find or create an organization to attach to
    db = SessionLocal()
    org = db.query(Organization).first()
    assert org is not None
    org_id = org.id
    db.close()

    user_payload = {
        "organization_id": org_id,
        "username": "cashier_unit_test",
        "full_name": "كاشير فحص البرمجية",
        "email": "cashier@unittest.jo",
        "password": "Password@2026",
        "role": UserRoleEnum.CASHIER
    }

    # Clean up if existed
    db = SessionLocal()
    existing = db.query(User).filter(User.username == "cashier_unit_test").first()
    if existing:
        db.delete(existing)
        db.commit()
    db.close()

    res = client.post("/api/v1/admin/users", json=user_payload, headers=headers)
    assert res.status_code == 200
    assert "cashier_unit_test" in res.json()["message"]

def test_regular_tenant_cannot_access_plans():
    headers = get_auth_header("rawsheh_admin_test", UserRoleEnum.ORG_ADMIN)
    res = client.get("/api/v1/admin/plans", headers=headers)
    assert res.status_code == 403
