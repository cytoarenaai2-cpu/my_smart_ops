import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.schema import (
    User, Organization, Branch, Transaction, SubscriptionPlan, 
    UserRoleEnum, PlatformSupportContact
)
from app.core.security import (
    hash_password,
    verify_password,
    require_super_admin
)

router = APIRouter(prefix="/admin", tags=["Platform Super Admin Management"])


class CreatePlanRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    price_monthly_jod: float = 0.0
    price_annual_jod: float = 0.0
    max_branches: int = 1
    max_users: int = 3
    max_transactions_monthly: int = 1000
    has_telegram_bot: bool = True
    has_jofotara_qr: bool = True
    has_ai_daily_brief: bool = True
    has_tax_reports: bool = True
    badge_color: str = "emerald"
    is_active: bool = True


class UpdatePlanRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_monthly_jod: Optional[float] = None
    price_annual_jod: Optional[float] = None
    max_branches: Optional[int] = None
    max_users: Optional[int] = None
    max_transactions_monthly: Optional[int] = None
    has_telegram_bot: Optional[bool] = None
    has_jofotara_qr: Optional[bool] = None
    has_ai_daily_brief: Optional[bool] = None
    has_tax_reports: Optional[bool] = None
    badge_color: Optional[str] = None
    is_active: Optional[bool] = None


class CreateOrgRequest(BaseModel):
    name: str
    industry_type: str = "retail"
    tax_number: Optional[str] = None
    currency: str = "JOD"
    admin_username: str
    admin_password: str
    admin_full_name: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    auto_daily_brief_enabled: bool = True
    daily_brief_time: str = "08:30"
    branches: Optional[List[str]] = None
    # Phase 4 SaaS Subscription fields
    subscription_plan: str = "PRO"
    subscription_duration_months: int = 12
    subscription_price_jod: float = 0.0
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    industry_type: Optional[str] = None
    tax_number: Optional[str] = None
    currency: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    auto_daily_brief_enabled: Optional[bool] = None
    daily_brief_time: Optional[str] = None
    is_active: Optional[bool] = None
    branches: Optional[List[str]] = None
    # Phase 4 SaaS Subscription fields
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None  # ACTIVE, TRIAL, SUSPENDED, EXPIRED
    subscription_expires_at: Optional[str] = None  # YYYY-MM-DD
    subscription_price_jod: Optional[float] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class CreateUserRequest(BaseModel):
    organization_id: Optional[str] = None
    username: str
    password: str
    full_name: str
    email: Optional[str] = None
    role: str = UserRoleEnum.CASHIER


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    organization_id: Optional[str] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


class AdminProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None
    # Support contact settings
    support_phone: Optional[str] = None
    support_whatsapp: Optional[str] = None
    support_email: Optional[str] = None
    working_hours: Optional[str] = None
    support_notes: Optional[str] = None


class SupportContactUpdateRequest(BaseModel):
    support_phone: Optional[str] = None
    support_whatsapp: Optional[str] = None
    support_email: Optional[str] = None
    working_hours: Optional[str] = None
    support_notes: Optional[str] = None
    is_active: Optional[bool] = True


class DirectResetPasswordRequest(BaseModel):
    new_password: str


@router.get("/platform-summary")
def get_platform_summary(
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استرجاع مؤشرات الأداء والقيادة التنفيذية للمنصة بالكامل (Executive Platform Metrics).
    """
    total_orgs = db.query(Organization).count()
    active_subs = db.query(Organization).filter(
        Organization.subscription_status == "ACTIVE",
        Organization.is_active == True
    ).count()
    trial_subs = db.query(Organization).filter(
        Organization.subscription_status == "TRIAL"
    ).count()
    suspended_or_expired = db.query(Organization).filter(
        (Organization.subscription_status.in_(["EXPIRED", "SUSPENDED"])) | (Organization.is_active == False)
    ).count()

    total_sales = db.query(func.coalesce(func.sum(Transaction.total_amount), 0.0)).filter(
        Transaction.transaction_type == "SALE"
    ).scalar() or 0.0

    total_tx_count = db.query(Transaction).count()

    connected_bots = db.query(Organization).filter(
        Organization.telegram_bot_token.isnot(None),
        Organization.telegram_bot_token != ""
    ).count()

    monthly_revenue = db.query(func.coalesce(func.sum(Organization.subscription_price_jod), 0.0)).filter(
        Organization.subscription_status.in_(["ACTIVE", "TRIAL"]),
        Organization.is_active == True
    ).scalar() or 0.0

    return {
        "total_organizations": total_orgs,
        "active_subscriptions": active_subs,
        "trial_subscriptions": trial_subs,
        "expired_subscriptions": suspended_or_expired,
        "total_sales_volume": round(float(total_sales), 3),
        "total_transactions": total_tx_count,
        "connected_bots": connected_bots,
        "monthly_revenue_jod": round(float(monthly_revenue), 2)
    }


# ==========================================
# Subscription Plans Management (خطط وباقات الاشتراك)
# ==========================================

@router.get("/plans")
def list_plans(
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استعراض كافة خطط وباقات الاشتراك المتاحة في المنصة مع عدد المشتركين في كل باقة.
    """
    plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.created_at).all()
    results = []
    for p in plans:
        subscriber_count = db.query(Organization).filter(
            Organization.subscription_plan == p.code
        ).count()
        results.append({
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "description": p.description or "",
            "price_monthly_jod": p.price_monthly_jod,
            "price_annual_jod": p.price_annual_jod,
            "max_branches": p.max_branches,
            "max_users": p.max_users,
            "max_transactions_monthly": p.max_transactions_monthly,
            "has_telegram_bot": p.has_telegram_bot,
            "has_jofotara_qr": p.has_jofotara_qr,
            "has_ai_daily_brief": p.has_ai_daily_brief,
            "has_tax_reports": p.has_tax_reports,
            "badge_color": p.badge_color or "emerald",
            "is_active": p.is_active,
            "subscriber_count": subscriber_count,
            "created_at": p.created_at.strftime("%Y-%m-%d") if p.created_at else ""
        })
    return results


@router.post("/plans")
def create_plan(
    req: CreatePlanRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    إنشاء خطة اشتراك سحابية جديدة وتحديد أسعارها وميزاتها.
    """
    clean_code = req.code.strip().upper()
    if db.query(SubscriptionPlan).filter(SubscriptionPlan.code == clean_code).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"رمز الخطة '{clean_code}' موجود مسبقاً. الرجاء استخدام كود فريد."
        )
    
    plan = SubscriptionPlan(
        id=str(uuid.uuid4()),
        code=clean_code,
        name=req.name.strip(),
        description=req.description.strip() if req.description else None,
        price_monthly_jod=req.price_monthly_jod,
        price_annual_jod=req.price_annual_jod,
        max_branches=req.max_branches,
        max_users=req.max_users,
        max_transactions_monthly=req.max_transactions_monthly,
        has_telegram_bot=req.has_telegram_bot,
        has_jofotara_qr=req.has_jofotara_qr,
        has_ai_daily_brief=req.has_ai_daily_brief,
        has_tax_reports=req.has_tax_reports,
        badge_color=req.badge_color,
        is_active=req.is_active
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"message": f"تم إنشاء خطة الاشتراك '{plan.name}' بنجاح!", "plan_id": plan.id}


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: str,
    req: UpdatePlanRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تعديل بيانات خطة الاشتراك الحالية وأسعارها وميزاتها.
    """
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="خطة الاشتراك غير موجودة."
        )
    
    if req.name is not None:
        plan.name = req.name.strip()
    if req.description is not None:
        plan.description = req.description.strip()
    if req.price_monthly_jod is not None:
        plan.price_monthly_jod = req.price_monthly_jod
    if req.price_annual_jod is not None:
        plan.price_annual_jod = req.price_annual_jod
    if req.max_branches is not None:
        plan.max_branches = req.max_branches
    if req.max_users is not None:
        plan.max_users = req.max_users
    if req.max_transactions_monthly is not None:
        plan.max_transactions_monthly = req.max_transactions_monthly
    if req.has_telegram_bot is not None:
        plan.has_telegram_bot = req.has_telegram_bot
    if req.has_jofotara_qr is not None:
        plan.has_jofotara_qr = req.has_jofotara_qr
    if req.has_ai_daily_brief is not None:
        plan.has_ai_daily_brief = req.has_ai_daily_brief
    if req.has_tax_reports is not None:
        plan.has_tax_reports = req.has_tax_reports
    if req.badge_color is not None:
        plan.badge_color = req.badge_color
    if req.is_active is not None:
        plan.is_active = req.is_active
        
    db.commit()
    return {"message": f"تم تحديث بيانات خطة الاشتراك '{plan.name}' بنجاح!"}


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: str,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    حذف خطة الاشتراك من المنصة بشرط عدم وجود منشآت نشطة مرتبطة بها.
    """
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="خطة الاشتراك غير موجودة."
        )
    
    active_count = db.query(Organization).filter(
        Organization.subscription_plan == plan.code
    ).count()
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"لا يمكن حذف الخطة '{plan.name}' لوجود {active_count} منشأة مشتركة بها حالياً. يمكنك إلغاء تفعيلها بدلاً من ذلك."
        )
        
    db.delete(plan)
    db.commit()
    return {"message": f"تم حذف خطة الاشتراك '{plan.name}' بنجاح!"}


@router.get("/organizations")
def list_organizations(
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استعراض كافة المنشآت والأنشطة التجارية المشتركة في المنصة مع تفاصيل الاشتراكات والأداء.
    """
    orgs = db.query(Organization).order_by(Organization.created_at.desc()).all()
    results = []
    now_utc = datetime.now(timezone.utc)

    for org in orgs:
        branches = [{"id": b.id, "name": b.name} for b in org.branches]
        user_count = db.query(User).filter(User.organization_id == org.id).count()
        tx_count = db.query(Transaction).filter(Transaction.organization_id == org.id).count()

        # حساب المبيعات الإجمالية للمنشأة
        org_sales = db.query(func.coalesce(func.sum(Transaction.total_amount), 0.0)).filter(
            Transaction.organization_id == org.id,
            Transaction.transaction_type == "SALE"
        ).scalar() or 0.0

        # استخراج حساب المدير الأساسي للمنشأة
        admin_user_obj = db.query(User).filter(
            User.organization_id == org.id,
            User.role == UserRoleEnum.ORG_ADMIN
        ).first()

        admin_info = None
        if admin_user_obj:
            admin_info = {
                "id": admin_user_obj.id,
                "username": admin_user_obj.username,
                "full_name": admin_user_obj.full_name,
                "email": admin_user_obj.email or "",
                "is_active": admin_user_obj.is_active
            }

        # حساب الأيام المتبقية وحالة الاشتراك الفعلية
        days_remaining = 0
        status_val = org.subscription_status or "ACTIVE"
        if org.subscription_expires_at:
            exp = org.subscription_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            exp_delta = exp - now_utc
            days_remaining = max(0, exp_delta.days)
            if exp_delta.total_seconds() <= 0 and status_val not in ["SUSPENDED"]:
                status_val = "EXPIRED"

        results.append({
            "id": org.id,
            "name": org.name,
            "industry_type": org.industry_type,
            "tax_number": org.tax_number or "",
            "currency": org.currency,
            "is_active": org.is_active,
            "subscription_plan": org.subscription_plan or "PRO",
            "subscription_status": status_val,
            "subscription_expires_at": org.subscription_expires_at.strftime("%Y-%m-%d") if org.subscription_expires_at else "",
            "days_remaining": days_remaining,
            "subscription_price_jod": round(float(org.subscription_price_jod or 0.0), 2),
            "contact_email": org.contact_email or (admin_info["email"] if admin_info else ""),
            "contact_phone": org.contact_phone or "",
            "total_sales": round(float(org_sales), 3),
            "admin_user": admin_info,
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
    إنشاء منشأة تجارية جديدة بالكامل وتعيين خطة الاشتراك وبياناتها الضريبية وفروعها وحساب مالكها.
    """
    clean_username = req.admin_username.strip()
    existing_user = db.query(User).filter(User.username.ilike(clean_username)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"اسم المستخدم '{clean_username}' مسجل مسبقاً، يرجى اختيار اسم مستخدم آخر."
        )

    # احتساب تاريخ انتهاء الاشتراك بناءً على الخطة والمدة
    now_utc = datetime.now(timezone.utc)
    plan_upper = req.subscription_plan.strip().upper() if req.subscription_plan else "PRO"
    if plan_upper == "TRIAL":
        expires_at = now_utc + timedelta(days=14)
        sub_status = "TRIAL"
        price = 0.0
    else:
        duration_months = req.subscription_duration_months if req.subscription_duration_months > 0 else 12
        expires_at = now_utc + timedelta(days=duration_months * 30)
        sub_status = "ACTIVE"
        price = req.subscription_price_jod

    contact_email = req.contact_email.strip() if req.contact_email else (clean_username if "@" in clean_username else f"{clean_username}@tenant.local")

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
        subscription_plan=plan_upper,
        subscription_status=sub_status,
        subscription_expires_at=expires_at,
        subscription_price_jod=price,
        contact_email=contact_email,
        contact_phone=req.contact_phone.strip() if req.contact_phone else None,
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
        email=contact_email,
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
        "message": f"تم إنشاء المنشأة '{org.name}' وتفعيل خطة ({org.subscription_plan}) بنجاح!",
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
    تعديل البيانات والاشتراك الخاص بالنشاط التجاري (خاص بمالك المنصة فقط).
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="لم يتم العثور على المنشأة المحددة.")

    if req.name is not None:
        org.name = req.name.strip()

    if req.industry_type is not None:
        org.industry_type = req.industry_type.strip()

    if req.currency is not None:
        org.currency = req.currency.strip()

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

    # حقول الاشتراك
    if req.subscription_plan is not None:
        org.subscription_plan = req.subscription_plan.strip().upper()

    if req.subscription_status is not None:
        org.subscription_status = req.subscription_status.strip().upper()

    if req.subscription_price_jod is not None:
        org.subscription_price_jod = max(0.0, float(req.subscription_price_jod))

    if req.contact_email is not None:
        org.contact_email = req.contact_email.strip() if req.contact_email.strip() else None

    if req.contact_phone is not None:
        org.contact_phone = req.contact_phone.strip() if req.contact_phone.strip() else None

    if req.subscription_expires_at is not None:
        try:
            exp_date = datetime.strptime(req.subscription_expires_at.strip(), "%Y-%m-%d")
            org.subscription_expires_at = exp_date.replace(tzinfo=timezone.utc)
        except Exception:
            pass

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
        "message": f"تم تحديث بيانات منشأة '{org.name}' بنجاح!",
        "organization_id": org.id
    }


@router.delete("/organizations/{org_id}")
def delete_organization(
    org_id: str,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    حذف منشأة تجارية بالكامل وكافة بياناتها وحساباتها وإيقاف البوت الخاص بها.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="المنشأة غير موجودة.")

    # إيقاف البوت إذا كان قيد التشغيل
    try:
        from app.services.telegram_bot import multi_bot_manager
        multi_bot_manager.stop_bot(org.id)
    except Exception as e:
        print(f"[Admin] Bot stop error during org delete: {e}")

    org_name = org.name
    db.delete(org)
    db.commit()

    return {"message": f"تم حذف المنشأة '{org_name}' وكافة فروعها وبياناتها بنجاح."}


@router.post("/organizations/{org_id}/toggle-status")
def toggle_organization_status(
    org_id: str,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تبديل حالة تفعيل المنشأة (تعليق / تفعيل) فوراً.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="المنشأة غير موجودة.")

    org.is_active = not org.is_active
    if not org.is_active:
        org.subscription_status = "SUSPENDED"
    else:
        now_dt = datetime.now(timezone.utc)
        if org.subscription_expires_at:
            exp = org.subscription_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now_dt > exp:
                org.subscription_status = "EXPIRED"
            else:
                org.subscription_status = "ACTIVE"
        else:
            org.subscription_status = "ACTIVE"

    db.commit()

    # مزامنة بوت تيليجرام
    try:
        from app.services.telegram_bot import multi_bot_manager
        if org.is_active and org.telegram_bot_token:
            multi_bot_manager.start_or_reload_bot(org.id, org.telegram_bot_token)
        else:
            multi_bot_manager.stop_bot(org.id)
    except Exception as e:
        print(f"[Admin] Bot sync error on toggle status: {e}")

    status_str = "مفعلة" if org.is_active else "معلقة / موقوفة"
    return {
        "message": f"تم تغيير حالة منشأة '{org.name}' إلى {status_str}.",
        "is_active": org.is_active,
        "subscription_status": org.subscription_status
    }


@router.put("/profile")
def update_admin_profile(
    req: AdminProfileUpdateRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تحديث الملف الشخصي لمالك المنصة (الاسم، البريد الإلكتروني، وتغيير كلمة السر بعد تأكيد الحالية).
    """
    if req.full_name is not None and req.full_name.strip():
        current_admin.full_name = req.full_name.strip()

    if req.email is not None and req.email.strip():
        current_admin.email = req.email.strip()

    if req.new_password:
        if not req.current_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="يرجى إدخال كلمة المرور الحالية لتأكيد التغيير."
            )
        if not verify_password(req.current_password, current_admin.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="كلمة المرور الحالية غير صحيحة."
            )
        if len(req.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="يجب ألا تقل كلمة المرور الجديدة عن 6 خانات."
            )
        current_admin.hashed_password = hash_password(req.new_password)

    # Update Support Contact if any fields are provided
    if any([
        req.support_phone is not None,
        req.support_whatsapp is not None,
        req.support_email is not None,
        req.working_hours is not None,
        req.support_notes is not None
    ]):
        contact = db.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
        if not contact:
            contact = PlatformSupportContact(id="default")
            db.add(contact)
        if req.support_phone is not None:
            contact.support_phone = req.support_phone.strip() if req.support_phone.strip() else None
        if req.support_whatsapp is not None:
            contact.support_whatsapp = req.support_whatsapp.strip() if req.support_whatsapp.strip() else None
        if req.support_email is not None:
            contact.support_email = req.support_email.strip() if req.support_email.strip() else None
        if req.working_hours is not None:
            contact.working_hours = req.working_hours.strip() if req.working_hours.strip() else None
        if req.support_notes is not None:
            contact.support_notes = req.support_notes.strip() if req.support_notes.strip() else None

    db.commit()
    db.refresh(current_admin)

    return {
        "message": "تم تحديث بيانات حساب مالك المنصة وقنوات الدعم بنجاح!",
        "user": {
            "id": current_admin.id,
            "username": current_admin.username,
            "full_name": current_admin.full_name,
            "email": current_admin.email,
            "role": current_admin.role
        }
    }


@router.get("/support-contact")
def get_admin_support_contact(
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    استرجاع إعدادات قنوات الدعم الفني الحالية للمنصة لمالك المنصة.
    """
    contact = db.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
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
        db.add(contact)
        db.commit()
        db.refresh(contact)

    return {
        "support_phone": contact.support_phone or "",
        "support_whatsapp": contact.support_whatsapp or "",
        "support_email": contact.support_email or "",
        "working_hours": contact.working_hours or "",
        "support_notes": contact.support_notes or "",
        "is_active": contact.is_active
    }


@router.put("/support-contact")
def update_admin_support_contact(
    req: SupportContactUpdateRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تحديث قنوات الدعم الفني المعتمدة للمنصة (هاتف، واتساب، بريد إلكتروني، ساعات العمل وملاحظات المساعدة).
    """
    contact = db.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
    if not contact:
        contact = PlatformSupportContact(id="default")
        db.add(contact)

    if req.support_phone is not None:
        contact.support_phone = req.support_phone.strip() if req.support_phone.strip() else None

    if req.support_whatsapp is not None:
        contact.support_whatsapp = req.support_whatsapp.strip() if req.support_whatsapp.strip() else None

    if req.support_email is not None:
        contact.support_email = req.support_email.strip() if req.support_email.strip() else None

    if req.working_hours is not None:
        contact.working_hours = req.working_hours.strip() if req.working_hours.strip() else None

    if req.support_notes is not None:
        contact.support_notes = req.support_notes.strip() if req.support_notes.strip() else None

    if req.is_active is not None:
        contact.is_active = req.is_active

    db.commit()
    db.refresh(contact)

    return {
        "message": "تم تحديث قنوات الدعم الفني والتواصل المعتمدة للمنصة بنجاح!",
        "contact": {
            "support_phone": contact.support_phone,
            "support_whatsapp": contact.support_whatsapp,
            "support_email": contact.support_email,
            "working_hours": contact.working_hours,
            "support_notes": contact.support_notes,
            "is_active": contact.is_active
        }
    }



@router.post("/users/{user_id}/reset-password")
def direct_reset_user_password(
    user_id: str,
    req: DirectResetPasswordRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    إعادة تعيين كلمة مرور مستخدم المنشأة مباشرة من قِبل مالك المنصة.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    if getattr(user, "is_primary_owner", False) and current_admin.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="محظور أمنياً: لا يمكن للمالكين الآخرين إعادة تعيين كلمة مرور المالك الأساسي للمنصة."
        )

    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يجب ألا تقل كلمة المرور عن 6 خانات."
        )

    user.hashed_password = hash_password(req.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    db.commit()

    return {"message": f"تم تعيين كلمة المرور الجديدة للمستخدم '{user.username}' بنجاح."}


@router.post("/users/{user_id}/generate-reset-link")
def generate_user_reset_link(
    user_id: str,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    توليد رابط أمني سري لإعادة تعيين كلمة المرور (صالح لمدة 24 ساعة)، لإرساله للعميل عبر الإيميل أو الواتساب أو نسخه مباشرة.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    if getattr(user, "is_primary_owner", False) and current_admin.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="محظور أمنياً: لا يمكن للمالكين الآخرين توليد رابط استعادة لحساب المالك الأساسي للمنصة."
        )

    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    db.commit()

    reset_url = f"/index.html?reset_token={token}"

    return {
        "message": f"تم إنشاء رابط إعادة تعيين كلمة المرور بنجاح للمستخدم '{user.username}' (صالح لمدة 24 ساعة).",
        "reset_token": token,
        "reset_url": reset_url,
        "user_id": user.id,
        "username": user.username,
        "user_email": user.email or "",
        "user_name": user.full_name,
        "expires_in_hours": 24
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
            "is_primary_owner": bool(getattr(u, "is_primary_owner", False)),
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
        is_active=True,
        is_primary_owner=False
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
    تعطيل أو حذف مستخدم من النظام مع تطبيق ضوابط الصلاحية المطلقة (Super Power):
    - المالك الأساسي لا يمكن حذفه بأي شكل.
    - المالك الأساسي يستطيع حذف أي مستخدم بما في ذلك المالكين الآخرين للمنصة.
    - المالكون الآخرون لا يمكنهم حذف المالك الأساسي أو حذف مالكي المنصة الآخرين.
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لا يمكنك حذف أو تعطيل حسابك الشخصي كمالك للمنصة."
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    # 1. حماية المالك الأساسي ذو الصلاحية المطلقة (Super Power) بشكل قطعي
    if getattr(user, "is_primary_owner", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="محظور أمنياً: لا يمكن حذف أو تعطيل حساب المالك الأساسي للمنصة (صاحب الصلاحية المطلقة / Super Power)."
        )

    # 2. إذا كان الحساب المستهدف هو مالك منصة آخر (SUPER_ADMIN)
    if user.role == UserRoleEnum.SUPER_ADMIN:
        if not getattr(current_admin, "is_primary_owner", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="محظور أمنياً: فقط المالك الأساسي للمنصة (صاحب الصلاحية المطلقة / Super Power) يمتلك صلاحية حذف مالكي المنصة الآخرين."
            )

    db.delete(user)
    db.commit()
    return {"message": f"تم حذف المستخدم '{user.username}' بنجاح."}


@router.put("/users/{user_id}")
def update_user_details_and_role(
    user_id: str,
    req: UpdateUserRequest,
    current_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """
    تعديل بيانات المستخدم، الأدوار والصلاحيات (RBAC)، والمنشأة التابع لها.
    متاح لكافة مالكي المنصة (Super Admins) مع حماية أمنية مشددة لرتبة وبيانات المالك الأساسي.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    # حماية المالك الأساسي ذو الصلاحية المطلقة (Super Power)
    if getattr(user, "is_primary_owner", False):
        # المالك الأساسي لا يمكن لمالك آخر تعديل بياناته
        if current_admin.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="محظور أمنياً: لا يمكن للمالكين الآخرين تعديل بيانات أو صلاحيات المالك الأساسي للمنصة."
            )
        # ولا يمكن تنزيل رتبة المالك الأساسي
        if req.role and req.role != UserRoleEnum.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="محظور أمنياً: لا يمكن تغيير أو تنزيل رتبة المالك الأساسي للمنصة."
            )

    # التحقق من اسم المستخدم الجديد إن تم تغييره
    if req.username:
        clean_username = req.username.strip()
        if clean_username.lower() != user.username.lower():
            existing = db.query(User).filter(User.username.ilike(clean_username), User.id != user_id).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"اسم المستخدم '{clean_username}' محجوز مسبقاً لمستخدم آخر."
                )
            user.username = clean_username

    # تحديث الاسم الكامل
    if req.full_name is not None:
        user.full_name = req.full_name.strip()

    # تحديث البريد الإلكتروني
    if req.email is not None:
        user.email = req.email.strip() if req.email.strip() else None

    # تحديث الدور والمنشأة
    if req.role:
        allowed_roles = [UserRoleEnum.SUPER_ADMIN, UserRoleEnum.ORG_ADMIN, UserRoleEnum.ACCOUNTANT, UserRoleEnum.CASHIER]
        if req.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"الرتبة المحددة غير صالحة. الرتب المسموحة هي: {', '.join(allowed_roles)}"
            )

        if req.role == UserRoleEnum.SUPER_ADMIN:
            user.organization_id = None
        else:
            if req.organization_id is not None:
                user.organization_id = req.organization_id.strip() if req.organization_id.strip() else None
            if not user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="يجب ربط المستخدم برتبة (مدير، محاسب، كاشير) بمنشأة تجارية محددة."
                )
        user.role = req.role
    elif req.organization_id is not None:
        if user.role != UserRoleEnum.SUPER_ADMIN:
            user.organization_id = req.organization_id.strip() if req.organization_id.strip() else None

    # تحديث حالة التفعيل
    if req.is_active is not None:
        if getattr(user, "is_primary_owner", False) and not req.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="لا يمكن تعطيل حساب المالك الأساسي للمنصة."
            )
        user.is_active = req.is_active

    # تحديث كلمة المرور إن أُرسلت
    if req.new_password:
        if len(req.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="يجب ألا تقل كلمة المرور عن 6 خانات."
            )
        user.hashed_password = hash_password(req.new_password)
        user.reset_token = None
        user.reset_token_expires_at = None

    db.commit()
    db.refresh(user)

    return {
        "message": f"تم تحديث بيانات وصلاحيات المستخدم '{user.username}' بنجاح!",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "is_primary_owner": bool(getattr(user, "is_primary_owner", False)),
            "organization_id": user.organization_id,
            "organization_name": user.organization.name if user.organization else "مالك المنصة (النظام العام)"
        }
    }
