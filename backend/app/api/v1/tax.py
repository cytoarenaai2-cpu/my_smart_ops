from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schema import Organization, Transaction, AuditFlag
from app.services.tax_engine import JordanTaxEngine

router = APIRouter(prefix="/tax", tags=["Jordan Tax & JoFotara Compliance"])

@router.get("/summary")
def get_tax_summary(
    organization_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    ملخص الحسابات الضريبية للفترة المحددة (المبيعات، ضريبة المخرجات، ضريبة المدخلات المقبولة، الصافي).
    """
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة.")
        organization_id = org.id

    start_date = date.today() - timedelta(days=days)

    txs = db.query(Transaction).filter(
        Transaction.organization_id == organization_id,
        Transaction.transaction_date >= start_date
    ).all()

    tax_pos = JordanTaxEngine.calculate_tax_position(txs)
    reconcile = JordanTaxEngine.reconcile_payments(txs)

    return {
        "period_days": days,
        "tax_position": tax_pos.model_dump(),
        "payment_reconciliation": reconcile.model_dump()
    }


@router.get("/pre-filing-report")
def get_pre_filing_report(
    organization_id: Optional[str] = Query(None),
    period_name: str = Query("الشهر الحالي"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    توليد ملف التدقيق الشامل الموجه للمحاسب القانوني قبل تقديم الإقرار لضريبة الدخل والمبيعات الأردنية.
    """
    org = None
    if organization_id:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        org = db.query(Organization).first()
    if not org:
        raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة.")

    start_date = date.today() - timedelta(days=days)

    txs = db.query(Transaction).filter(
        Transaction.organization_id == org.id,
        Transaction.transaction_date >= start_date
    ).all()

    flags = db.query(AuditFlag).filter(
        AuditFlag.organization_id == org.id,
        AuditFlag.resolved == False
    ).all()

    return JordanTaxEngine.generate_pre_filing_audit_report(
        organization=org,
        transactions=txs,
        audit_flags=flags,
        period_name=period_name
    )


@router.get("/risk-invoices")
def get_risk_invoices(
    organization_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    استرجاع الفواتير والمصروفات المعرضة لخطر الرفض الضريبي لعدم اكتمال بيانات المورد بموجب نظام JoFotara.
    """
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة.")
        organization_id = org.id

    # الفواتير والمصروفات بدون رقم ضريبي أو معلمة كغير قابلة للخصم
    risk_txs = db.query(Transaction).filter(
        Transaction.organization_id == organization_id,
        Transaction.transaction_type.in_(["EXPENSE", "PURCHASE"]),
        (Transaction.supplier_tax_id == None) | (Transaction.is_deductible_expense == False)
    ).order_by(Transaction.transaction_date.desc()).limit(20).all()

    return [
        {
            "id": tx.id,
            "invoice_number": tx.invoice_number or "بدون رقم",
            "date": str(tx.transaction_date),
            "supplier_or_merchant": tx.merchant_or_supplier_name or "غير محدد",
            "amount": tx.total_amount,
            "tax_amount": tx.tax_amount,
            "supplier_tax_id": tx.supplier_tax_id,
            "risk_reason": "فاتورة غير معززة برقم ضريبي للمورد (مخالفة لتعليمات الفوترة الإلكترونية 2025)" if not tx.supplier_tax_id else "مصروف معلم كغير قابل للخصم"
        }
        for tx in risk_txs
    ]
