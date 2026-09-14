import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.schema import Base, Organization, Branch, Transaction, AuditFlag
from app.models.extraction_schemas import (
    ExtractedDocumentData, DocumentTypeEnum, ExtractedPaymentBreakdown, ExtractedItem
)
from app.services.validator import FinancialValidator
from app.services.daily_summary import DailySummaryService
from app.main import app
from app.core.database import get_db

# Use StaticPool so all connections share the exact same in-memory SQLite tables
TEST_SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    yield session
    session.close()

@pytest.fixture
def client():
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def test_arithmetic_validation_clean_data():
    """اختبار بيانات نظيفة ومتطابقة 100%"""
    data = ExtractedDocumentData(
        document_type=DocumentTypeEnum.SALES_Z_REPORT,
        merchant_or_branch_name="فرع الجبيهة",
        subtotal=100.0,
        tax_amount=16.0,
        discount_amount=0.0,
        total_amount=116.0,
        payment_breakdown=ExtractedPaymentBreakdown(
            cash=50.0,
            card=46.0,
            cliq=20.0
        )
    )
    result = FinancialValidator.validate(data)
    assert result.is_valid is True
    assert result.status == "PROCESSED"
    assert len(result.flags) == 0

def test_arithmetic_mismatch_detection():
    """اختبار اكتشاف خطأ في حساب الإجمالي"""
    data = ExtractedDocumentData(
        document_type=DocumentTypeEnum.SALES_Z_REPORT,
        subtotal=100.0,
        tax_amount=16.0,
        total_amount=150.0,  # خطأ! يجب أن يكون 116
        payment_breakdown=ExtractedPaymentBreakdown(cash=150.0)
    )
    result = FinancialValidator.validate(data)
    assert result.is_valid is False
    assert result.status == "NEEDS_REVIEW"
    assert any(f.flag_type == "ARITHMETIC_MISMATCH" for f in result.flags)

def test_payment_reconciliation_mismatch():
    """اختبار عدم تطابق المبيعات مع مجموع وسائل الدفع (كاش + شبكة + كليك)"""
    data = ExtractedDocumentData(
        document_type=DocumentTypeEnum.SALES_Z_REPORT,
        subtotal=200.0,
        tax_amount=0.0,
        total_amount=200.0,
        payment_breakdown=ExtractedPaymentBreakdown(
            cash=100.0,
            card=50.0,
            cliq=20.0 # المجموع 170 بينما المبيعات 200 (فرق 30 د.أ)
        )
    )
    result = FinancialValidator.validate(data)
    assert result.status == "NEEDS_REVIEW"
    assert any(f.flag_type == "PAYMENT_MISMATCH" for f in result.flags)

def test_jordan_tax_deductibility_warning():
    """اختبار التحقق الضريبي الأردني لمصروف كبير بدون رقم ضريبي"""
    data = ExtractedDocumentData(
        document_type=DocumentTypeEnum.PURCHASE_INVOICE,
        merchant_or_branch_name="مورد أجهزة",
        supplier_tax_id=None,  # غير متوفر
        subtotal=750.0,
        tax_amount=0.0,
        total_amount=750.0,  # أكبر من 500 د.أ
        payment_breakdown=ExtractedPaymentBreakdown(cash=750.0)
    )
    result = FinancialValidator.validate(data)
    assert result.tax_deductible is False
    assert any(f.flag_type == "MISSING_TAX_INVOICE" for f in result.flags)

def test_daily_morning_brief_generation(db_session):
    """اختبار توليد التقرير الصباحي التنفيذي"""
    org = Organization(name="سلسلة مطاعم النور", currency="JOD")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    branch = Branch(organization_id=org.id, name="فرع الشميساني")
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    sale_tx = Transaction(
        organization_id=org.id,
        branch_id=branch.id,
        transaction_type="SALE",
        transaction_date=date.today(),
        subtotal=500.0,
        tax_amount=80.0,
        total_amount=580.0,
        payment_breakdown={"cash": 300.0, "card": 200.0, "cliq": 80.0}
    )
    expense_tx = Transaction(
        organization_id=org.id,
        branch_id=branch.id,
        transaction_type="EXPENSE",
        transaction_date=date.today(),
        subtotal=50.0,
        tax_amount=0.0,
        total_amount=50.0
    )
    db_session.add_all([sale_tx, expense_tx])
    db_session.commit()

    brief = DailySummaryService.generate_morning_brief(db_session, org.id, date.today())
    assert brief["metrics"]["sales_total"] == 580.0
    assert brief["metrics"]["expenses_total"] == 50.0
    assert brief["metrics"]["net_estimate"] == 530.0
    assert "سلسلة مطاعم النور" in brief["whatsapp_formatted_text"]
    assert "فرع الشميساني" in brief["whatsapp_formatted_text"]

def test_api_root_and_documents_upload(client):
    """اختبار نقاط نهاية API الفعلية (Root & Document Upload)"""
    # 1. Root check
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert root_res.json()["currency"] == "JOD"

    # 2. Upload document (simulation via text notes)
    upload_res = client.post(
        "/api/v1/documents/upload",
        data={"text_notes": "تقرير إغلاق كاشير يومي مبيعات فرع الجبيهة"}
    )
    assert upload_res.status_code == 200
    data = upload_res.json()
    assert data["success"] is True
    assert data["extracted_summary"]["type"] == "SALE"

    # 3. Analytics brief check
    brief_res = client.get("/api/v1/analytics/daily-brief")
    assert brief_res.status_code == 200
    brief_data = brief_res.json()
    assert brief_data["metrics"]["sales_total"] > 0
    assert "صباح الخير" in brief_data["whatsapp_formatted_text"]

    # 4. Dashboard summary check
    dash_res = client.get("/api/v1/analytics/dashboard-summary?days=7")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["kpis"]["total_sales"] > 0
