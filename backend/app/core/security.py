import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schema import User, Organization, UserRoleEnum

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "smart_ops_saas_super_secret_jwt_key_2026_jordan_secure!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    """تشفير كلمة المرور بتقنية bcrypt مع Salt عالي الأمان"""
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """التحقق من مطابقة كلمة المرور مع الهاش المخزن"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """توليد رمز JWT مشفر يحمل هوية ورتبة المستخدم والمنشأة"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """فك وتدقيق رمز JWT والتأكد من صلاحيته وعدم التلاعب به"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """استخراج والتحقق من هوية المستخدم النشط من رمز الـ Bearer Token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="يجب تسجيل الدخول أولاً للوصول إلى هذه البيانات.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exception

    # التأكد من أن المنشأة التابع لها المستخدم غير معطلة (إلا إذا كان Super Admin)
    if user.role != UserRoleEnum.SUPER_ADMIN and user.organization_id:
        org = db.query(Organization).filter(Organization.id == user.organization_id).first()
        if not org or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="تم تعطيل حساب هذه المنشأة التجارية، يرجى التواصل مع إدارة المنصة."
            )

    return user


def get_optional_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """استخراج المستخدم إن وُجد بدون إيقاف الطلب إذا لم يسجل دخوله (للتوافق الرجعي)"""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id: str = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def require_roles(allowed_roles: List[str]):
    """فحص الأدوار والصلاحيات (RBAC Permission Gatekeeper)"""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ليس لديك الصلاحية الكافية للقيام بهذا الإجراء."
            )
        return current_user
    return role_checker


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """التحقق الحصري من رتبة مالك المنصة (Super Admin)"""
    if current_user.role != UserRoleEnum.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذا الإجراء متاح حصراً لمالك المنصة (Super Admin)."
        )
    return current_user


def resolve_tenant_org_id(
    current_user: Optional[User],
    requested_org_id: Optional[str] = None,
    db: Optional[Session] = None
) -> str:
    """
    عزل بيانات المنشأة الصارم (Strict Tenant Isolation):
    - إذا كان المستخدم Super Admin: يُسمح له بطلب أي منشأة، أو اختيار الأولى افتراضياً.
    - إذا كان المستخدم مدير منشأة أو محاسب أو كاشير: يُجبر حصراً على منشأته ويُمنع من الوصول لغيرها.
    - إذا لم يسجل الدخول (نمط محلي للتوافق): يعود للمنشأة الأولى.
    """
    if not current_user:
        if requested_org_id:
            return requested_org_id
        if db:
            org = db.query(Organization).first()
            return org.id if org else ""
        return ""

    if current_user.role == UserRoleEnum.SUPER_ADMIN:
        if requested_org_id:
            return requested_org_id
        if db:
            first_org = db.query(Organization).first()
            return first_org.id if first_org else ""
        return ""

    if requested_org_id and requested_org_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح لك بالوصول إلى بيانات منشأة تجارية أخرى."
        )

    return current_user.organization_id or ""
