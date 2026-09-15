import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.schema import Base, Organization, Branch, Transaction, AuditFlag
from app.services.tax_engine import JordanTaxEngine
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

def test_tax_calculation_standard_sales():
    """اختبار احتساب ضريبة المبيعات 16% على المبيعات القياسية"""
    txs = [
        Transaction(
            transaction_type="SALE",
            subtotal=1000.0,
            tax_amount=160.0,
            total_amount=1160.0,
            tax_status="STANDARD_16"
        ),
        Transaction(
            transaction_type="SALE",
            subtotal=500.0,
            tax_amount=0.0,
            total_amount=500.0,
            tax_status="EXEMPT"
        )
    ]
    res = JordanTaxEngine.calculate_tax_position(txs)
    assert res.gross_sales == 1660.0
    assert res.taxable_sales_subtotal == 1000.0
    assert res.output_tax_collected == 160.0
    assert res.exempt_or_zero_sales == 500.0
    assert res.net_sales_tax_payable == 160.0

def test_tax_deduction_eligibility_with_and_without_tax_id():
    """اختبار قبول خصم ضريبة المدخلات فقط للفواتير التي تحمل رقماً ضريبياً (JoFotara)"""
    txs = [
        # بيع
        Transaction(
            transaction_type="SALE",
            subtotal=2000.0,
            tax_amount=320.0,
            total_amount=2320.0,
            tax_status="STANDARD_16"
        ),
        # شراء مؤهل (مع رقم ضريبي)
        Transaction(
            transaction_type="PURCHASE",
            subtotal=500.0,
            tax_amount=80.0,
            total_amount=580.0,
            supplier_tax_id="100998822",
            is_deductible_expense=True
        ),
        # شراء غير مؤهل (بدون رقم ضريبي - مخالف لتعليمات 2025)
        Transaction(
            transaction_type="PURCHASE",
            subtotal=300.0,
            tax_amount=48.0,
            total_amount=348.0,
            supplier_tax_id=None,
            is_deductible_expense=False
        )
    ]
    res = JordanTaxEngine.calculate_tax_position(txs)
    assert res.output_tax_collected == 320.0
    assert res.eligible_purchases_subtotal == 500.0
    assert res.eligible_input_tax == 80.0  # تم قبول خصم الـ 80 فقط
    assert res.ineligible_expenses_subtotal == 348.0
    assert res.lost_input_tax_deduction == 48.0  # ضاعت الـ 48 لغياب الرقم الضريبي
    assert res.net_sales_tax_payable == 240.0    # 320 - 80 = 240 د.أ

def test_tax_credit_carried_forward():
    """اختبار توليد رصيد دائن مدور عندما تفوق ضريبة المدخلات ضريبة المخرجات"""
    txs = [
        # بيع قليل
        Transaction(
            transaction_type="SALE",
            subtotal=500.0,
            tax_amount=80.0,
            total_amount=580.0,
            tax_status="STANDARD_16"
        ),
        # مشتريات كبيرة (بضاعة خام وأصول) برقم ضريبي معتمد
        Transaction(
            transaction_type="PURCHASE",
            subtotal=1000.0,
            tax_amount=160.0,
            total_amount=1160.0,
            supplier_tax_id="99887766",
            is_deductible_expense=True
        )
    ]
    res = JordanTaxEngine.calculate_tax_position(txs)
    assert res.output_tax_collected == 80.0
    assert res.eligible_input_tax == 160.0
    assert res.net_sales_tax_payable == 0.0
    assert res.tax_credit_carried_forward == 80.0  # رصيد ضريبي دائن لصالح المنشأة

def test_tax_api_and_pre_filing_report(client, db_session):
    """اختبار نقاط النهاية الخاصة بمحرك الضرائب والتقرير الشامل قبل الإقرار"""
    org = Organization(name="مخابز ومطاعم الشرق", currency="JOD", tax_number="100554433")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    # إضافة حركة بيع وشراء
    s = Transaction(
        organization_id=org.id,
        transaction_type="SALE",
        transaction_date=date.today(),
        subtotal=1000.0,
        tax_amount=160.0,
        total_amount=1160.0,
        payment_breakdown={"cash": 600.0, "card": 560.0},
        tax_status="STANDARD_16"
    )
    p_risk = Transaction(
        organization_id=org.id,
        transaction_type="EXPENSE",
        transaction_date=date.today(),
        merchant_or_supplier_name="تاجر حبوب ومواد خام",
        invoice_number="EXP-991",
        subtotal=600.0,
        tax_amount=96.0,
        total_amount=696.0,
        supplier_tax_id=None,  # غير مؤهل
        is_deductible_expense=False
    )
    db_session.add_all([s, p_risk])
    db_session.commit()

    # 1. فحص ملخص الضريبة
    sum_res = client.get(f"/api/v1/tax/summary?organization_id={org.id}&days=30")
    assert sum_res.status_code == 200
    sum_data = sum_res.json()
    assert sum_data["tax_position"]["output_tax_collected"] == 160.0

    # 2. فحص تقرير المراجعة الشامل قبل الإقرار
    rep_res = client.get(f"/api/v1/tax/pre-filing-report?organization_id={org.id}")
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert rep_data["metadata"]["tax_number"] == "100554433"
    assert len(rep_data["cpa_recommendations"]) > 0
    assert "disclaimer" in rep_data["metadata"]

    # 3. فحص كشف الفواتير المعرضة للخطر
    risk_res = client.get(f"/api/v1/tax/risk-invoices?organization_id={org.id}")
    assert risk_res.status_code == 200
    risk_data = risk_res.json()
    assert len(risk_data) == 1
    assert risk_data[0]["invoice_number"] == "EXP-991"

def test_historical_invoices_tax_report_fallback(client, db_session):
    """فحص عدم تصفير التقرير للفواتير التاريخية (أقدم من 30 يوماً) واسترجاعها بذكاء"""
    org = Organization(name="مطعم وكافيه الروشة القديم", currency="JOD", tax_number="999888777")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    old_tx = Transaction(
        organization_id=org.id,
        transaction_type="SALE",
        transaction_date=date(2022, 4, 5),
        invoice_number="INV-OLD-1",
        subtotal=100.0,
        service_charge=10.0,
        tax_amount=17.6,
        total_amount=127.6,
        payment_breakdown={"other": 127.6},
        tax_status="STANDARD_16"
    )
    db_session.add(old_tx)
    db_session.commit()

    # طلب التقرير مع days=30 (الوضع الافتراضي القديم الذي كان يعيد أصفاراً)
    res = client.get(f"/api/v1/tax/pre-filing-report?organization_id={org.id}&days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["transactions_count"] == 1
    assert data["tax_position"]["gross_sales"] == 127.6
    assert data["tax_position"]["taxable_sales_subtotal"] == 110.0  # 100 + 10 service
    assert data["tax_position"]["output_tax_collected"] == 17.6
    assert data["payment_reconciliation"]["other_collected"] == 127.6
    assert data["payment_reconciliation"]["variance"] == 0.0

