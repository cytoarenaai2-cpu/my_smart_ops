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

    # Phase 3 Automation & Telegram Briefing fields
    telegram_chat_id = Column(String(50), nullable=True)
    auto_daily_brief_enabled = Column(Boolean, default=True)
    daily_brief_time = Column(String(10), default="08:30")
    
    created_at = Column(DateTime, default=utc_now)

    branches = relationship("Branch", back_populates="organization", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="organization", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="organization", cascade="all, delete-orphan")
    audit_flags = relationship("AuditFlag", back_populates="organization", cascade="all, delete-orphan")


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
