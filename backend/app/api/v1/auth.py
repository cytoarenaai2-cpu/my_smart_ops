from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.schema import User, Organization, UserRoleEnum
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user
)

router = APIRouter(prefix="/auth", tags=["Authentication & SaaS Accounts"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    organization: Optional[dict] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, db: Session = Depends(get_db)):
    """
    تسجيل الدخول وإصدار رمز JWT مشفر يحمل صلاحيات المستخدم والمنشأة التابع لها.
    يدعم كلاً من JSON payload و x-www-form-urlencoded و FormData.
    """
    content_type = request.headers.get("content-type", "")
    identifier = ""
    password = ""

    if "application/json" in content_type:
        try:
            body = await request.json()
            identifier = str(body.get("username") or body.get("email") or "").strip()
            password = str(body.get("password", ""))
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            identifier = str(form.get("username") or form.get("email") or "").strip()
            password = str(form.get("password", ""))
        except Exception:
            pass

    if not identifier or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يرجى إدخال البريد الإلكتروني أو اسم المستخدم وكلمة المرور."
        )

    clean_id = identifier.lower()
    user = db.query(User).filter(
        (func.lower(User.username) == clean_id) | (func.lower(User.email) == clean_id)
    ).first()

    if not user:
        org = db.query(Organization).filter(func.lower(Organization.contact_email) == clean_id).first()
        if org:
            user = db.query(User).filter(
                User.organization_id == org.id,
                User.role == UserRoleEnum.ORG_ADMIN
            ).first()
            if not user:
                user = db.query(User).filter(User.organization_id == org.id).first()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="البريد الإلكتروني / اسم المستخدم أو كلمة المرور غير صحيحة.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذا الحساب معطل حالياً، يرجى مراجعة إدارة المنصة."
        )

    org_data = None
    if user.organization_id:
        org = db.query(Organization).filter(Organization.id == user.organization_id).first()
        if org:
            if not org.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="حساب هذه المنشأة التجارية معطل، يرجى مراجعة إدارة المنصة."
                )
            org_data = {
                "id": org.id,
                "name": org.name,
                "industry_type": org.industry_type,
                "tax_number": org.tax_number,
                "currency": org.currency,
                "has_dedicated_bot": bool(org.telegram_bot_token),
                "auto_daily_brief_enabled": org.auto_daily_brief_enabled,
                "daily_brief_time": org.daily_brief_time
            }

    token_payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "organization_id": user.organization_id
    }
    token = create_access_token(token_payload)

    user_data = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "organization_id": user.organization_id
    }

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_data,
        "organization": org_data
    }


@router.get("/me")
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    استرجاع بيانات الحساب المسجل حالياً والتحقق الفوري من صلاحياته.
    """
    org_data = None
    if current_user.organization_id:
        org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
        if org:
            org_data = {
                "id": org.id,
                "name": org.name,
                "industry_type": org.industry_type,
                "tax_number": org.tax_number,
                "currency": org.currency,
                "has_dedicated_bot": bool(org.telegram_bot_token),
                "auto_daily_brief_enabled": org.auto_daily_brief_enabled,
                "daily_brief_time": org.daily_brief_time
            }

    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "email": current_user.email,
            "role": current_user.role,
            "organization_id": current_user.organization_id
        },
        "organization": org_data
    }


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    تغيير كلمة المرور الخاصة بالمستخدم الحالي بعد التأكد من صحة القديمة.
    """
    if not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="كلمة المرور الحالية غير صحيحة."
        )

    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يجب أن تتكون كلمة المرور الجديدة من 6 خانات على الأقل."
        )

    current_user.hashed_password = hash_password(req.new_password)
    db.commit()

    return {"message": "تم تحديث كلمة المرور بنجاح!"}


class ResetPasswordPublicRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
def reset_password_with_token(
    req: ResetPasswordPublicRequest,
    db: Session = Depends(get_db)
):
    """
    إعادة تعيين كلمة المرور للمستخدم بواسطة رمز الأمان السري المؤقت (Reset Token) المرسل عبر الإيميل أو الرابط المباشر.
    """
    clean_token = req.token.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="رمز إعادة التعيين مطلوب.")

    user = db.query(User).filter(User.reset_token == clean_token).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="رمز إعادة تعيين كلمة المرور غير صالح أو تم استخدامه مسبقاً."
        )

    # التحقق من صلاحية الرمز الزمنية (24 ساعة)
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    if user.reset_token_expires_at:
        expires_at = user.reset_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now_utc > expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="انتهت صلاحية رمز إعادة التعيين (أكثر من 24 ساعة). يرجى طلب رابط جديد من مالك المنصة."
            )

    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يجب أن تتكون كلمة المرور الجديدة من 6 خانات على الأقل."
        )

    user.hashed_password = hash_password(req.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    db.commit()

    return {
        "message": f"تم تعيين كلمة المرور بنجاح للمستخدم '{user.username}'! يمكنك الآن تسجيل الدخول.",
        "username": user.username
    }


@router.get("/support-contact")
def get_public_support_contact(db: Session = Depends(get_db)):
    """
    استرجاع قنوات وبيانات التواصل والدعم الفني المعتمدة للمنصة (هاتف، واتساب، إيميل، وساعات العمل).
    متاحة للعامة لإظهارها لشاشات تسجيل الدخول وطلب المساعدة.
    """
    from app.models.schema import PlatformSupportContact
    contact = db.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
    if not contact:
        return {
            "support_phone": "+962 7 9000 0000",
            "support_whatsapp": "962790000000",
            "support_email": "support@smartops.jo",
            "working_hours": "يومياً من 9:00 صباحاً حتى 10:00 مساءً",
            "support_notes": "فريق الدعم الفني جاهز لمساعدتكم في استعادة الحساب وتأكيد بيانات المنشأة عبر واتساب أو الهاتف.",
            "is_active": True
        }

    return {
        "support_phone": contact.support_phone if contact.is_active else None,
        "support_whatsapp": contact.support_whatsapp if contact.is_active else None,
        "support_email": contact.support_email if contact.is_active else None,
        "working_hours": contact.working_hours if contact.is_active else None,
        "support_notes": contact.support_notes if contact.is_active else None,
        "is_active": contact.is_active
    }


class ForgotPasswordRequest(BaseModel):
    identifier: str


@router.post("/forgot-password")
def forgot_password_inquiry(
    req: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    توجيه المستخدم لقنوات الدعم الفني المعتمدة لحماية المنشأة ومنع إعادة التعيين العشوائية.
    """
    from app.models.schema import PlatformSupportContact
    contact = db.query(PlatformSupportContact).filter(PlatformSupportContact.id == "default").first()
    return {
        "success": True,
        "message": "لحماية أمان وسرية بيانات منشأتك، يتم تأكيد استعادة الحساب حصراً عبر التواصل مع إدارة المنصة والدعم الفني المعتمد.",
        "support": {
            "phone": contact.support_phone if contact else None,
            "whatsapp": contact.support_whatsapp if contact else None,
            "email": contact.support_email if contact else None,
            "notes": contact.support_notes if contact else None
        }
    }


