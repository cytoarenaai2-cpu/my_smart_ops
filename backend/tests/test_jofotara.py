import pytest
from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.schema import Base, Organization, Branch, Transaction
from app.services.jofotara_service import JoFotaraService
from app.main import app
from app.core.database import get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    org = Organization(
        id="test-org-jofotara",
        name="مطعم وكافيه الروشة التجاري",
        tax_number="123456789",
        industry_type="restaurant"
    )
    db.add(org)

    branch = Branch(
        id="test-branch-1",
        organization_id="test-org-jofotara",
        name="فرع خلدا الرئيسي"
    )
    db.add(branch)

    tx1 = Transaction(
        id="test-tx-sale-1",
        organization_id="test-org-jofotara",
        branch_id="test-branch-1",
        transaction_type="SALE",
        transaction_date=date(2026, 9, 16),
        merchant_or_supplier_name="الفرع الرئيسي",
        invoice_number="INV-2026-001",
        subtotal=100.000,
        service_charge=10.000,
        tax_amount=17.600,
        total_amount=127.600,
        payment_breakdown={"cash": 50.0, "card": 77.6},
        tax_status="STANDARD_16",
        is_e_invoice_compliant=True
    )
    db.add(tx1)

    tx2 = Transaction(
        id="test-tx-purchase-1",
        organization_id="test-org-jofotara",
        transaction_type="PURCHASE",
        transaction_date=date(2026, 9, 15),
        merchant_or_supplier_name="شركة الألبان الوطنية",
        invoice_number="PUR-9988",
        subtotal=50.000,
        service_charge=0.000,
        tax_amount=8.000,
        total_amount=58.000,
        supplier_tax_id="987654321",
        payment_breakdown={"cash": 58.0}
    )
    db.add(tx2)

    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


def test_tlv_encoding_and_decoding():
    seller = "مطعم وكافيه الروشة"
    tax_id = "123456789"
    timestamp = "2026-09-16T12:00:00"
    total = 127.600
    tax = 17.600

    b64 = JoFotaraService.encode_tlv(seller, tax_id, timestamp, total, tax)
    assert isinstance(b64, str)
    assert len(b64) > 20

    res = JoFotaraService.decode_tlv(b64)
    assert res["valid"] is True
    decoded = res["decoded"]
    assert decoded["seller_name"]["value"] == seller
    assert decoded["tax_id"]["value"] == tax_id
    assert decoded["timestamp"]["value"] == timestamp
    assert decoded["total_amount"]["value"] == "127.600"
    assert decoded["tax_amount"]["value"] == "17.600"


def test_qr_png_generation():
    tlv_b64 = JoFotaraService.encode_tlv(
        seller_name="سوبرماركت الخير",
        tax_id="112233445",
        timestamp="2026-09-16T14:30:00",
        total_amount=50.000,
        tax_amount=8.000
    )
    png_bytes = JoFotaraService.generate_qr_png_bytes(tlv_b64)
    assert isinstance(png_bytes, bytes)
    # PNG signature header: \x89PNG\r\n\x1a\n
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 200

    data_uri = JoFotaraService.generate_qr_data_uri(tlv_b64)
    assert data_uri.startswith("data:image/png;base64,")


def test_einvoice_payload_generation():
    db = TestingSessionLocal()
    org = db.query(Organization).first()
    branch = db.query(Branch).first()
    tx = db.query(Transaction).filter(Transaction.id == "test-tx-sale-1").first()

    payload = JoFotaraService.generate_einvoice_payload(tx, org, branch)
    db.close()

    assert payload["jofotara_schema_version"] == "2025.1"
    assert payload["invoice_uuid"] == "test-tx-sale-1"
    assert payload["invoice_number"] == "INV-2026-001"
    assert payload["document_currency_code"] == "JOD"
    assert payload["seller_supplier_party"]["tax_identification_number"] == "123456789"
    assert payload["seller_supplier_party"]["branch_name"] == "فرع خلدا الرئيسي"
    assert payload["legal_monetary_total"]["payable_amount"] == 127.600
    assert payload["compliance_status"]["is_tin_valid"] is True
    assert payload["compliance_status"]["is_amounts_balanced"] is True
    assert payload["qr_code_tlv_base64"] is not None


def test_api_get_transaction_qr_json():
    res = client.get("/api/v1/tax/transactions/test-tx-sale-1/jofotara-qr")
    assert res.status_code == 200
    data = res.json()
    assert data["transaction_id"] == "test-tx-sale-1"
    assert data["tax_id"] == "123456789"
    assert data["qr_data_uri"].startswith("data:image/png;base64,")
    assert data["is_compliant"] is True
    assert "decoded_info" in data


def test_api_get_transaction_qr_image():
    res = client.get("/api/v1/tax/transactions/test-tx-sale-1/jofotara-qr?format=png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_api_get_transaction_payload():
    res = client.get("/api/v1/tax/transactions/test-tx-sale-1/jofotara-payload")
    assert res.status_code == 200
    data = res.json()
    assert data["invoice_uuid"] == "test-tx-sale-1"
    assert data["seller_supplier_party"]["party_name"] == "مطعم وكافيه الروشة التجاري"
    assert data["compliance_status"]["is_ready_for_istd_transmission"] is True


def test_api_decode_qr_endpoint():
    # Valid TLV
    tlv_b64 = JoFotaraService.encode_tlv(
        seller_name="مطعم الروشة",
        tax_id="123456789",
        timestamp="2026-09-16T10:00:00",
        total_amount=25.000,
        tax_amount=4.000
    )
    res = client.post("/api/v1/tax/jofotara/decode", json={"qr_content": tlv_b64})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["decoded"]["seller_name"]["value"] == "مطعم الروشة"
    assert data["decoded"]["tax_id"]["value"] == "123456789"

    # Invalid string
    res_bad = client.post("/api/v1/tax/jofotara/decode", json={"qr_content": "invalid_base64_&&&"})
    assert res_bad.status_code == 200
    assert res_bad.json()["valid"] is False
