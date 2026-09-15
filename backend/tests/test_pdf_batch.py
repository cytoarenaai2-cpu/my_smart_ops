import io
import pytest
from unittest.mock import patch
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.schema import Base, Organization, Branch, Transaction, Document, AuditFlag
from app.models.extraction_schemas import (
    ExtractedDocumentData, DocumentTypeEnum, ExtractedPaymentBreakdown, ExtractedItem
)
from app.services.pdf_batch_service import PDFBatchService
from app.main import app
from app.core.database import get_db

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def init_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture
def db():
    session = TestingSession()
    # Create test org
    org = Organization(
        name="سلسلة مطاعم الأفق",
        industry_type="مطاعم ومخابز",
        currency="JOD",
        tax_number="123456789",
        is_tax_registered=True
    )
    session.add(org)
    session.commit()
    session.refresh(org)
    yield session
    session.close()

def create_sample_multipage_pdf(num_pages=3) -> bytes:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

import asyncio

def test_pdf_batch_processing(db):
    async def _test():
        pdf_bytes = create_sample_multipage_pdf(3)

        # Mock AI response per page:
        # Page 1: 1 Sale Z-Report
        # Page 2: 2 Invoices (1 Purchase invoice + 1 Expense invoice)
        # Page 3: Blank (0 invoices)
        async def mock_parse_page(pdf_page_bytes, page_number, business_context=None):
            if page_number == 1:
                return [
                    ExtractedDocumentData(
                        document_type=DocumentTypeEnum.SALES_Z_REPORT,
                        merchant_or_branch_name="الفرع الرئيسي",
                        invoice_number="Z-P1-001",
                        subtotal=150.0,
                        tax_amount=24.0,
                        discount_amount=0.0,
                        total_amount=174.0,
                        payment_breakdown=ExtractedPaymentBreakdown(cash=100.0, card=74.0)
                    )
                ]
            elif page_number == 2:
                return [
                    ExtractedDocumentData(
                        document_type=DocumentTypeEnum.PURCHASE_INVOICE,
                        merchant_or_branch_name="شركة توريد المواد الغذائية",
                        supplier_tax_id="998877665",
                        invoice_number="INV-SUP-882",
                        subtotal=100.0,
                        tax_amount=16.0,
                        total_amount=116.0,
                        payment_breakdown=ExtractedPaymentBreakdown(cash=116.0)
                    ),
                    ExtractedDocumentData(
                        document_type=DocumentTypeEnum.EXPENSE_RECEIPT,
                        merchant_or_branch_name="محطة محروقات",
                        invoice_number="EXP-991",
                        subtotal=20.0,
                        tax_amount=0.0,
                        total_amount=20.0,
                        payment_breakdown=ExtractedPaymentBreakdown(cash=20.0)
                    )
                ]
            else: # Page 3
                return []

        with patch("app.services.ai_parser.AIParserService.parse_pdf_page", side_effect=mock_parse_page):
            res = await PDFBatchService.process_pdf(
                pdf_bytes=pdf_bytes,
                file_name="invoices_test.pdf",
                db=db
            )

        assert res["total_pages"] == 3
        assert res["processed_pages"] == 3
        assert res["total_invoices"] == 3

        assert res["sales_count"] == 1
        assert res["total_sales_amount"] == 174.0
        assert res["total_output_tax"] == 24.0

        assert res["purchases_count"] == 1
        assert res["total_purchases_amount"] == 116.0
        assert res["total_input_tax"] == 16.0

        assert res["expenses_count"] == 1
        assert res["total_expenses_amount"] == 20.0

        # Net tax: 24.0 - 16.0 = 8.0
        assert res["net_tax_liability"] == 8.0
        assert res["approved_count"] == 3
        assert res["needs_review_count"] == 0

        # Verify transactions in SQLite
        txs = db.query(Transaction).all()
        assert len(txs) == 3

        sale_tx = next(t for t in txs if t.transaction_type == "SALE")
        assert sale_tx.invoice_number == "Z-P1-001"
        assert "صفحة 1" in sale_tx.notes

        pur_tx = next(t for t in txs if t.transaction_type == "PURCHASE")
        assert pur_tx.invoice_number == "INV-SUP-882"
        assert "صفحة 2" in pur_tx.notes

        exp_tx = next(t for t in txs if t.transaction_type == "EXPENSE")
        assert exp_tx.invoice_number == "EXP-991"
        assert "صفحة 2" in exp_tx.notes

    asyncio.run(_test())

def test_api_upload_pdf_batch(db):
    pdf_bytes = create_sample_multipage_pdf(2)

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    async def mock_parse_page(pdf_page_bytes, page_number, business_context=None):
        return [
            ExtractedDocumentData(
                document_type=DocumentTypeEnum.SALES_RECEIPT,
                invoice_number=f"INV-P{page_number}",
                subtotal=50.0,
                tax_amount=8.0,
                total_amount=58.0,
                payment_breakdown=ExtractedPaymentBreakdown(cash=58.0)
            )
        ]

    with patch("app.services.ai_parser.AIParserService.parse_pdf_page", side_effect=mock_parse_page):
        resp = client.post(
            "/api/v1/documents/upload-pdf-batch",
            files={"file": ("test_batch.pdf", pdf_bytes, "application/pdf")}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["is_batch"] is True
    assert data["batch_summary"]["total_pages"] == 2
    assert data["batch_summary"]["total_invoices"] == 2

    app.dependency_overrides.clear()
