import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.schema import Base, Organization, Transaction
from app.services.pdf_report_service import PDFReportGenerator
from app.main import app
from app.core.database import get_db

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


def test_pdf_report_generator_direct():
    """فحص محرك توليد الـ PDF المباشر والتأكد من توليد بايتات سليمة"""
    sample_report_data = {
        "metadata": {
            "organization_name": "مطعم وكافيه النخبة التجاري",
            "tax_number": "123456789",
            "period": "كافة العمليات المسجلة",
            "transactions_count": 5,
            "date_range": {"from": "2026-01-01", "to": "2026-03-31"},
            "report_generated_date": "2026-09-16",
            "compliance_score": 92,
            "is_audit_ready": True,
            "disclaimer": "تقرير تدقيق استرشادي"
        },
        "tax_position": {
            "taxable_sales_subtotal": 3500.000,
            "output_tax_collected": 560.000,
            "eligible_input_tax": 200.000,
            "ineligible_expenses_subtotal": 50.000,
            "lost_input_tax_deduction": 8.000,
            "net_sales_tax_payable": 360.000,
            "tax_credit_carried_forward": 0.0
        },
        "payment_reconciliation": {
            "total_sales_reported": 3500.000,
            "cash_collected": 1500.000,
            "cards_pos_collected": 1200.000,
            "cliq_collected": 800.000,
            "delivery_collected": 0.0,
            "bank_transfer_collected": 0.0,
            "other_collected": 0.0,
            "total_payments_reconciled": 3500.000,
            "variance": 0.0,
            "has_discrepancy": False
        },
        "cpa_recommendations": [
            "الضريبة العامة المستحقة للتصريح والدفع هي: 360.000 د.أ.",
            "المطابقة تامة مع الكاش والـ POS وكليك."
        ]
    }

    pdf_bytes = PDFReportGenerator.generate_tax_report_pdf(sample_report_data)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_report_generator_empty():
    """فحص توليد الـ PDF عند وجود بيانات فارغة أو أصفار"""
    empty_report_data = {
        "metadata": {
            "organization_name": "مؤسسة جديدة",
            "tax_number": None,
            "period": "فترة تجريبية",
            "transactions_count": 0,
            "compliance_score": 100,
            "is_audit_ready": True
        },
        "tax_position": {},
        "payment_reconciliation": {},
        "cpa_recommendations": []
    }

    pdf_bytes = PDFReportGenerator.generate_tax_report_pdf(empty_report_data)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_api_pdf_report_all_time(client, db_session):
    """فحص واجهة الـ API وتنزيل ملف الـ PDF لكافة العمليات"""
    org = Organization(name="مطعم الروشة التجاري", currency="JOD", tax_number="123456789")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    tx = Transaction(
        organization_id=org.id,
        transaction_type="SALE",
        transaction_date=date(2026, 9, 10),
        invoice_number="INV-101",
        subtotal=1000.0,
        tax_amount=160.0,
        total_amount=1160.0,
        payment_breakdown={"cash": 1160.0},
        tax_status="STANDARD_16"
    )
    db_session.add(tx)
    db_session.commit()

    response = client.get(f"/api/v1/tax/pre-filing-report/pdf?organization_id={org.id}&all_time=true")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"
    assert "attachment;" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 1000


def test_api_pdf_report_days_filter(client, db_session):
    """فحص واجهة الـ API وتنزيل ملف الـ PDF لفترة محددة بالأيام"""
    org = Organization(name="سوبرماركت البركة", currency="JOD", tax_number="987654321")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    tx = Transaction(
        organization_id=org.id,
        transaction_type="SALE",
        transaction_date=date.today(),
        invoice_number="INV-202",
        subtotal=500.0,
        tax_amount=80.0,
        total_amount=580.0,
        payment_breakdown={"cash": 580.0},
        tax_status="STANDARD_16"
    )
    db_session.add(tx)
    db_session.commit()

    response = client.get(f"/api/v1/tax/pre-filing-report/pdf?organization_id={org.id}&days=30")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 1000
