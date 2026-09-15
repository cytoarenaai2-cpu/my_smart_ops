from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schema import Organization, Transaction, AuditFlag
from app.services.tax_engine import JordanTaxEngine

router = APIRouter(prefix="/tax", tags=["Jordan Tax & JoFotara Compliance"])

def _filter_tax_transactions(
    db: Session,
    organization_id: str,
    days: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    all_time: bool = False,
    period_name: Optional[str] = None
) -> tuple[List[Transaction], str]:
    query = db.query(Transaction).filter(Transaction.organization_id == organization_id)

    if start_date:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(Transaction.transaction_date <= end_date)

    computed_period = period_name

    # إذا طلب المستخدم صراحة كافة الفترات أو لم يتم تحديد تاريخ
    if all_time or (days is None and not start_date and not end_date):
        txs = query.order_by(Transaction.transaction_date.desc()).all()
        if not computed_period:
            computed_period = "كافة العمليات المسجلة"
        return txs, computed_period

    # في حال تحديد عدد أيام (مثل 30 يوم)
    if days and not start_date:
        cutoff = date.today() - timedelta(days=days)
        period_txs = query.filter(Transaction.transaction_date >= cutoff).order_by(Transaction.transaction_date.desc()).all()
        
        if period_txs:
            if not computed_period:
                computed_period = f"آخر {days} يوم"
            return period_txs, computed_period
        else:
            # إذا لم توجد فواتير في الفترة المحددة ولكن توجد فواتير أرشيفية/سابقة
            all_txs = query.order_by(Transaction.transaction_date.desc()).all()
            if all_txs:
                if not computed_period:
                    computed_period = "كافة العمليات المسجلة (فواتير أرشيفية)"
                return all_txs, computed_period
            else:
                if not computed_period:
                    computed_period = f"آخر {days} يوم"
                return [], computed_period

    txs = query.order_by(Transaction.transaction_date.desc()).all()
    if not computed_period:
        if start_date and end_date:
            computed_period = f"من {start_date} إلى {end_date}"
        elif start_date:
            computed_period = f"من {start_date}"
        else:
            computed_period = "الفترة المحددة"
    return txs, computed_period


@router.get("/summary")
def get_tax_summary(
    organization_id: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=3650),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    all_time: bool = Query(False),
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

    txs, computed_period = _filter_tax_transactions(
        db=db,
        organization_id=organization_id,
        days=days,
        start_date=start_date,
        end_date=end_date,
        all_time=all_time
    )

    tax_pos = JordanTaxEngine.calculate_tax_position(txs)
    reconcile = JordanTaxEngine.reconcile_payments(txs)

    return {
        "period": computed_period,
        "period_days": days,
        "transactions_count": len(txs),
        "tax_position": tax_pos.model_dump(),
        "payment_reconciliation": reconcile.model_dump()
    }


@router.get("/pre-filing-report")
def get_pre_filing_report(
    organization_id: Optional[str] = Query(None),
    period_name: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=3650),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    all_time: bool = Query(False),
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

    txs, computed_period = _filter_tax_transactions(
        db=db,
        organization_id=org.id,
        days=days,
        start_date=start_date,
        end_date=end_date,
        all_time=all_time,
        period_name=period_name
    )

    flags = db.query(AuditFlag).filter(
        AuditFlag.organization_id == org.id,
        AuditFlag.resolved == False
    ).all()

    return JordanTaxEngine.generate_pre_filing_audit_report(
        organization=org,
        transactions=txs,
        audit_flags=flags,
        period_name=computed_period
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
