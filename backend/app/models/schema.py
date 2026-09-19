import uuid
from datetime import datetime, timezone, date
from typing import Optional, List
from sqlalchemy import (
    Column, String, Boolean, Float, Date, DateTime, ForeignKey, Text, JSON, Enum, Integer
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utc_now():
    return datetime.now(timezone.utc)

class UserRoleEnum:
    SUPER_ADMIN = "SUPER_ADMIN"  # مالك المنصة
    ORG_ADMIN = "ORG_ADMIN"      # مدير / مالك المنشأة
    ACCOUNTANT = "ACCOUNTANT"    # محاسب قانوني
    CASHIER = "CASHIER"          # كاشير / موظف فرع


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, index=True, nullable=False)  # TRIAL, BASIC, PRO, ENTERPRISE, CUSTOM
    name = Column(String(100), nullable=False)                          # اسم الخطة بالعربية
    description = Column(Text, nullable=True)                          # وصف الخطة
    price_monthly_jod = Column(Float, default=0.0)                     # السعر الشهري بالدينار الأردني
    price_annual_jod = Column(Float, default=0.0)                      # السعر السنوي بالدينار الأردني
    max_branches = Column(Integer, default=1)                          # أقصى عدد فروع (-1 يعني غير محدود)
    max_users = Column(Integer, default=3)                             # أقصى عدد مستخدمين (-1 يعني غير محدود)
    max_transactions_monthly = Column(Integer, default=1000)           # الحد الشهري للعمليات (-1 يعني غير محدود)
    has_telegram_bot = Column(Boolean, default=True)                   # بوت تلغرام مخصص
    has_jofotara_qr = Column(Boolean, default=True)                    # فك وترميز فواتير JoFotara
    has_ai_daily_brief = Column(Boolean, default=True)                 # تقارير الذكاء الاصطناعي اليومية
    has_tax_reports = Column(Boolean, default=True)                    # تقارير الإقرار الضريبي الرسمي
    badge_color = Column(String(30), default="emerald")                # لون الشارة في الواجهة
    is_active = Column(Boolean, default=True)                          # الخطة متاحة للاشتراك
    created_at = Column(DateTime, default=utc_now)


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    industry_type = Column(String(100), default="retail")
    currency = Column(String(10), default="JOD")
    
    # Phase 2 Tax Compliance fields (Ready in schema)
    tax_number = Column(String(50), nullable=True)  # الرقم الضريبي / الرقم الوطني للمنشأة
    is_tax_registered = Column(Boolean, default=False)
    tax_filing_period = Column(String(20), default="MONTHLY") # MONTHLY, BIMONTHLY

    # Phase 3 Automation & Dedicated Telegram Bot fields
    telegram_bot_token = Column(String(100), nullable=True)  # توكن بوت تيليجرام المستقل الخاص بالمنشأة
    telegram_chat_id = Column(String(50), nullable=True)
    auto_daily_brief_enabled = Column(Boolean, default=True)
    daily_brief_time = Column(String(10), default="08:30")
    is_active = Column(Boolean, default=True)

    # Phase 4 SaaS Subscription & Management fields
    subscription_plan = Column(String(50), default="PRO")  # TRIAL, BASIC, PRO, ENTERPRISE
    subscription_status = Column(String(30), default="ACTIVE")  # ACTIVE, TRIAL, SUSPENDED, EXPIRED
    subscription_expires_at = Column(DateTime, nullable=True)
    subscription_price_jod = Column(Float, default=0.0)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=utc_now)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    branches = relationship("Branch", back_populates="organization", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="organization", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="organization", cascade="all, delete-orphan")
    audit_flags = relationship("AuditFlag", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)  # NULL لمالك المنصة (SUPER_ADMIN)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(30), default=UserRoleEnum.ORG_ADMIN, nullable=False)  # SUPER_ADMIN, ORG_ADMIN, ACCOUNTANT, CASHIER
    is_active = Column(Boolean, default=True)
    is_primary_owner = Column(Boolean, default=False, nullable=False)  # مالك المنصة الأساسي ذو الصلاحية المطلقة (Super Power)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="users")


class Branch(Base):
    __tablename__ = "branches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., 'فرع خلدا', 'الفرع الرئيسي'
    manager_name = Column(String(100), nullable=True)
    phone_number = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="branches")
    documents = relationship("Document", back_populates="branch")
    transactions = relationship("Transaction", back_populates="branch")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    branch_id = Column(String(36), ForeignKey("branches.id"), nullable=True)
    
    file_url = Column(Text, nullable=True)
    file_hash = Column(String(64), index=True, nullable=True)  # SHA256 to prevent duplicate upload
    document_type = Column(String(50), nullable=False)  # SALES_Z_REPORT, EXPENSE_RECEIPT, PURCHASE_INVOICE, BANK_STATEMENT
    raw_ai_response = Column(JSON, nullable=True)
    status = Column(String(30), default="PROCESSED")  # PROCESSED, NEEDS_REVIEW, FAILED
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="documents")
    branch = relationship("Branch", back_populates="documents")
    transactions = relationship("Transaction", back_populates="document")
    audit_flags = relationship("AuditFlag", back_populates="document")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    branch_id = Column(String(36), ForeignKey("branches.id"), nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=True)

    transaction_type = Column(String(20), nullable=False)  # SALE, PURCHASE, EXPENSE
    transaction_date = Column(Date, default=date.today, nullable=False)
    invoice_number = Column(String(100), nullable=True)
    merchant_or_supplier_name = Column(String(255), nullable=True)

    # Financial breakdown (3 decimals for JOD Fils precision)
    subtotal = Column(Float, default=0.0)
    service_charge = Column(Float, default=0.0)  # بدل الخدمة في المطاعم (Service Charge)
    tax_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)

    # Payment Reconciliation Breakdown
    # Format: {"cash": 100.0, "card": 50.0, "cliq": 25.0, "delivery": 30.0}
    payment_breakdown = Column(JSON, default=dict)

    # Phase 2 Tax Compliance & JoFotara Fields
    tax_status = Column(String(30), default="STANDARD_16")  # STANDARD_16, REDUCED_TAX, ZERO_TAX, EXEMPT
    is_e_invoice_compliant = Column(Boolean, default=False)
    supplier_tax_id = Column(String(50), nullable=True)  # الرقم الضريبي للمورد
    is_deductible_expense = Column(Boolean, default=True)  # مؤهل للخصم الضريبي
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="transactions")
    branch = relationship("Branch", back_populates="transactions")
    document = relationship("Document", back_populates="transactions")
    items = relationship("TransactionItem", back_populates="transaction", cascade="all, delete-orphan")
    audit_flags = relationship("AuditFlag", back_populates="transaction")


class TransactionItem(Base):
    __tablename__ = "transaction_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=False)
    description = Column(String(255), nullable=False)
    quantity = Column(Float, default=1.0)
    unit_price = Column(Float, default=0.0)
    total_price = Column(Float, nullable=False)
    tax_rate = Column(Float, default=0.16)  # Default 16% in Jordan
    tax_amount = Column(Float, default=0.0)

    transaction = relationship("Transaction", back_populates="items")


class AuditFlag(Base):
    __tablename__ = "audit_flags"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=True)

    severity = Column(String(20), default="WARNING")  # INFO, WARNING, CRITICAL
    flag_type = Column(String(50), nullable=False)   # ARITHMETIC_MISMATCH, PAYMENT_MISMATCH, MISSING_TAX_INVOICE, DUPLICATE_INVOICE
    message = Column(Text, nullable=False)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="audit_flags")
    transaction = relationship("Transaction", back_populates="audit_flags")
    document = relationship("Document", back_populates="audit_flags")


class PlatformSupportContact(Base):
    __tablename__ = "platform_support_contacts"

    id = Column(String(36), primary_key=True, default="default")
    support_phone = Column(String(50), nullable=True)
    support_whatsapp = Column(String(50), nullable=True)
    support_email = Column(String(100), nullable=True)
    working_hours = Column(String(150), nullable=True)
    support_notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

