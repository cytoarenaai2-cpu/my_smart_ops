import uuid
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schema import User, Organization, Branch, Transaction, UserRoleEnum
from app.core.security import (
    hash_password,
    require_super_admin
)

router = APIRouter(prefix="/admin", tags=["Platform Super Admin Management"])


class CreateOrgRequest(BaseModel):
    name: str
    industry_type: str = "retail"
    tax_number: Optional[str] = None
    currency: str = "JOD"
    branches: List[str] = []
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    auto_daily_brief_enabled: bool = True
    daily_brief_time: str = "08:30"
    admin_username: str
    admin_password: str
    admin_full_name: str


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    industry_type: Optional[str] = None
    tax_number: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    auto_daily_brief_enabled: Optional[bool] = None
    daily_brief_time: Optional[str] = None
    is_active: Optional[bool] = None
    branches: Optional[List[str]] = None


class CreateUserRequest(BaseModel):
    organization_id: Optional[str] = None
    username: str
    password: str
    full_name: str
    email: Optional[str] = None
    role: str = UserRoleEnum.CASHIER


@router.get("/organizations")
def list_organizations(
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استعراض كافة المنشآت والأنشطة التجارية المشتركة في المنصة (خاص بمالك المنصة فقط).
    """
    orgs = db.query(Organization).order_by(Organization.created_at.desc()).all()
    results = []

    for org in orgs:
        branches = [{"id": b.id, "name": b.name} for b in org.branches]
        user_count = db.query(User).filter(User.organization_id == org.id).count()
        tx_count = db.query(Transaction).filter(Transaction.organization_id == org.id).count()

        results.append({
            "id": org.id,
            "name": org.name,
            "industry_type": org.industry_type,
            "tax_number": org.tax_number or "",
            "currency": org.currency,
            "is_active": org.is_active,
            "telegram_bot_token": org.telegram_bot_token or "",
            "telegram_chat_id": org.telegram_chat_id or "",
            "has_dedicated_bot": bool(org.telegram_bot_token),
            "auto_daily_brief_enabled": org.auto_daily_brief_enabled,
            "daily_brief_time": org.daily_brief_time,
            "branches": branches,
            "users_count": user_count,
            "transactions_count": tx_count,
            "created_at": org.created_at.strftime("%Y-%m-%d %H:%M") if org.created_at else ""
        })

    return results


@router.post("/organizations")
def create_organization(
    req: CreateOrgRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    إنشاء منشأة تجارية جديدة بالكامل وتعيين بياناتها الضريبية وفروعها وتوكن البوت الخاص بها.
    """
    clean_username = req.admin_username.strip()
    existing_user = db.query(User).filter(User.username.ilike(clean_username)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"اسم المستخدم '{clean_username}' مسجل مسبقاً، يرجى اختيار اسم مستخدم آخر."
        )

    org = Organization(
        id=str(uuid.uuid4()),
        name=req.name.strip(),
        industry_type=req.industry_type.strip(),
        tax_number=req.tax_number.strip() if req.tax_number else None,
        is_tax_registered=bool(req.tax_number and req.tax_number.strip()),
        currency=req.currency,
        telegram_bot_token=req.telegram_bot_token.strip() if req.telegram_bot_token else None,
        telegram_chat_id=req.telegram_chat_id.strip() if req.telegram_chat_id else None,
        auto_daily_brief_enabled=req.auto_daily_brief_enabled,
        daily_brief_time=req.daily_brief_time.strip() if req.daily_brief_time else "08:30",
        is_active=True
    )
    db.add(org)

    # إنشاء الفروع
    branches_to_create = req.branches if req.branches else ["الفرع الرئيسي"]
    for b_name in branches_to_create:
        if b_name.strip():
            branch = Branch(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                name=b_name.strip()
            )
            db.add(branch)

    # إنشاء حساب الأدمن للمنشأة
    admin_user = User(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        username=clean_username,
        full_name=req.admin_full_name.strip(),
        hashed_password=hash_password(req.admin_password),
        role=UserRoleEnum.ORG_ADMIN,
        is_active=True
    )
    db.add(admin_user)

    db.commit()
    db.refresh(org)

    # إذا تم تزويد توكن بوت، تشغيله فوراً في مدير البوتات
    try:
        from app.services.telegram_bot import multi_bot_manager
        if org.telegram_bot_token:
            multi_bot_manager.start_or_reload_bot(org.id, org.telegram_bot_token)
    except Exception as e:
        print(f"[Admin] Could not start bot for new org: {e}")

    return {
        "message": f"تم إنشاء المنشأة '{org.name}' وحساب المدير بنجاح!",
        "organization_id": org.id,
        "admin_username": admin_user.username
    }


@router.put("/organizations/{org_id}")
def update_organization(
    org_id: str,
    req: UpdateOrgRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تعديل البيانات الحساسة للنشاط التجاري (الاسم، نوع النشاط، الرقم الضريبي JoFotara، الفروع، وتوكن البوت).
    هذه العملية مقفلة حصرياً لمالك المنصة (Super Admin).
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="لم يتم العثور على المنشأة المحددة.")

    if req.name is not None:
        org.name = req.name.strip()

    if req.industry_type is not None:
        org.industry_type = req.industry_type.strip()

    if req.tax_number is not None:
        org.tax_number = req.tax_number.strip() if req.tax_number.strip() else None
        org.is_tax_registered = bool(org.tax_number)

    if req.telegram_chat_id is not None:
        org.telegram_chat_id = req.telegram_chat_id.strip() if req.telegram_chat_id.strip() else None

    if req.auto_daily_brief_enabled is not None:
        org.auto_daily_brief_enabled = req.auto_daily_brief_enabled

    if req.daily_brief_time is not None:
        org.daily_brief_time = req.daily_brief_time.strip()

    if req.is_active is not None:
        org.is_active = req.is_active

    old_token = org.telegram_bot_token
    token_changed = False
    if req.telegram_bot_token is not None:
        new_token = req.telegram_bot_token.strip() if req.telegram_bot_token.strip() else None
        if new_token != old_token:
            org.telegram_bot_token = new_token
            token_changed = True

    # تحديث أو إضافة الفروع
    if req.branches is not None:
        existing_branch_names = {b.name.strip() for b in org.branches}
        for b_name in req.branches:
            if b_name.strip() and b_name.strip() not in existing_branch_names:
                new_branch = Branch(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    name=b_name.strip()
                )
                db.add(new_branch)

    db.commit()
    db.refresh(org)

    # إعادة ضبط البوت إن تغير التوكن أو حالة التفعيل
    try:
        from app.services.telegram_bot import multi_bot_manager
        if token_changed or req.is_active is False:
            if org.is_active and org.telegram_bot_token:
                multi_bot_manager.start_or_reload_bot(org.id, org.telegram_bot_token)
            else:
                multi_bot_manager.stop_bot(org.id)
    except Exception as e:
        print(f"[Admin] Bot manager sync error: {e}")

    return {
        "message": f"تم تحديث بيانات المنشأة '{org.name}' بنجاح!",
        "organization_id": org.id
    }


@router.get("/users")
def list_users(
    organization_id: Optional[str] = None,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استعراض مستخدمي النظام وتوزيعهم على المنشآت.
    """
    query = db.query(User)
    if organization_id:
        query = query.filter(User.organization_id == organization_id)
    users = query.order_by(User.created_at.desc()).all()

    return [
        {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email or "",
            "role": u.role,
            "is_active": u.is_active,
            "organization_id": u.organization_id,
            "organization_name": u.organization.name if u.organization else "مالك المنصة (النظام العام)",
            "created_at": u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else ""
        }
        for u in users
    ]


@router.post("/users")
def create_user(
    req: CreateUserRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    إنشاء مستخدم جديد لأي منشأة وتعيين دوره (ORG_ADMIN, ACCOUNTANT, CASHIER).
    """
    clean_username = req.username.strip()
    if db.query(User).filter(User.username.ilike(clean_username)).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"اسم المستخدم '{clean_username}' موجود مسبقاً."
        )

    if req.role != UserRoleEnum.SUPER_ADMIN and not req.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يجب تحديد المنشأة التجارية التابع لها هذا المستخدم."
        )

    user = User(
        id=str(uuid.uuid4()),
        organization_id=req.organization_id,
        username=clean_username,
        full_name=req.full_name.strip(),
        email=req.email.strip() if req.email else None,
        hashed_password=hash_password(req.password),
        role=req.role,
        is_active=True
    )
    db.add(user)
    db.commit()

    return {"message": f"تم إنشاء المستخدم '{user.username}' برتبة {user.role} بنجاح!"}


@router.delete("/users/{user_id}")
def delete_or_toggle_user(
    user_id: str,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تعطيل أو حذف مستخدم من النظام.
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لا يمكنك حذف أو تعطيل حسابك الشخصي كمالك للمنصة."
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    db.delete(user)
    db.commit()
    return {"message": "تم حذف المستخدم بنجاح."}
