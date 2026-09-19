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


def test_primary_super_admin_super_powers_and_protection():
    db = SessionLocal()
    # 1. Prepare Primary Super Admin (Root)
    root_admin = db.query(User).filter(User.username == "root_super_owner").first()
    if not root_admin:
        root_admin = User(
            username="root_super_owner",
            full_name="Root Super Admin",
            email="root@platform.jo",
            hashed_password=hash_password("RootPass@123"),
            role=UserRoleEnum.SUPER_ADMIN,
            is_active=True,
            is_primary_owner=True
        )
        db.add(root_admin)
    else:
        root_admin.is_primary_owner = True
        root_admin.role = UserRoleEnum.SUPER_ADMIN

    # 2. Prepare Secondary Super Admin
    secondary_admin = db.query(User).filter(User.username == "secondary_super_admin").first()
    if not secondary_admin:
        secondary_admin = User(
            username="secondary_super_admin",
            full_name="Secondary Super Admin",
            email="secondary@platform.jo",
            hashed_password=hash_password("SecPass@123"),
            role=UserRoleEnum.SUPER_ADMIN,
            is_active=True,
            is_primary_owner=False
        )
        db.add(secondary_admin)
    else:
        secondary_admin.is_primary_owner = False
        secondary_admin.role = UserRoleEnum.SUPER_ADMIN

    # 3. Prepare Another Secondary Super Admin to be deleted
    other_super = db.query(User).filter(User.username == "disposable_super_admin").first()
    if not other_super:
        other_super = User(
            username="disposable_super_admin",
            full_name="Disposable Super Admin",
            email="disposable@platform.jo",
            hashed_password=hash_password("DispPass@123"),
            role=UserRoleEnum.SUPER_ADMIN,
            is_active=True,
            is_primary_owner=False
        )
        db.add(other_super)

    db.commit()
    db.refresh(root_admin)
    db.refresh(secondary_admin)
    db.refresh(other_super)

    root_id = root_admin.id
    secondary_id = secondary_admin.id
    other_id = other_super.id
    db.close()

    root_token = create_access_token({"sub": root_id, "username": "root_super_owner", "role": UserRoleEnum.SUPER_ADMIN})
    root_headers = {"Authorization": f"Bearer {root_token}"}

    sec_token = create_access_token({"sub": secondary_id, "username": "secondary_super_admin", "role": UserRoleEnum.SUPER_ADMIN})
    sec_headers = {"Authorization": f"Bearer {sec_token}"}

    # Test A: Secondary admin cannot delete the Root primary owner (403 Forbidden)
    res_del_root_by_sec = client.delete(f"/api/v1/admin/users/{root_id}", headers=sec_headers)
    assert res_del_root_by_sec.status_code == 403
    assert "المالك الأساسي" in res_del_root_by_sec.json()["detail"]

    # Test B: Secondary admin cannot delete another Super Admin (403 Forbidden)
    res_del_other_by_sec = client.delete(f"/api/v1/admin/users/{other_id}", headers=sec_headers)
    assert res_del_other_by_sec.status_code == 403
    assert "فقط المالك الأساسي" in res_del_other_by_sec.json()["detail"]

    # Test C: Secondary admin cannot reset root admin password or generate reset link
    res_reset_pass = client.post(
        f"/api/v1/admin/users/{root_id}/reset-password",
        headers=sec_headers,
        json={"new_password": "NewSecret@123"}
    )
    assert res_reset_pass.status_code == 403

    res_reset_link = client.post(
        f"/api/v1/admin/users/{root_id}/generate-reset-link",
        headers=sec_headers
    )
    assert res_reset_link.status_code == 403

    # Test D: Root admin CANNOT delete themselves (400 Bad Request)
    res_self_del = client.delete(f"/api/v1/admin/users/{root_id}", headers=root_headers)
    assert res_self_del.status_code == 400

    # Test E: Root admin CAN delete the other Super Admin (Super Power!)
    res_del_by_root = client.delete(f"/api/v1/admin/users/{other_id}", headers=root_headers)
    assert res_del_by_root.status_code == 200
    assert "تم حذف المستخدم" in res_del_by_root.json()["message"]

    # Verify other_super is indeed removed from db
    db2 = SessionLocal()
    deleted_check = db2.query(User).filter(User.id == other_id).first()
    assert deleted_check is None
    db2.close()

