from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.schema import Organization, Transaction, AuditFlag, Branch
from app.services.daily_summary import DailySummaryService

router = APIRouter(prefix="/analytics", tags=["Analytics & Reporting"])

@router.get("/daily-brief")
def get_daily_morning_brief(
    organization_id: Optional[str] = Query(None),
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """
    ????? ???? ?????? ???????? ??????? ??????? ??? ??????/????????.
    """
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            raise HTTPException(status_code=404, detail="?? ??? ?????? ??? ????? ?????.")
        organization_id = org.id

    chosen_date = target_date or date.today()
    return DailySummaryService.generate_morning_brief(db, organization_id, chosen_date)


@router.get("/dashboard-summary")
def get_dashboard_summary(
    organization_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """
    ????? ???? ?????? ????????? ??????? ?????? (????????? ?????????? ??? ?????? ?????????).
    """
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            raise HTTPException(status_code=404, detail="?? ??? ?????? ??? ?????.")
        organization_id = org.id

    start_date = date.today() - timedelta(days=days)

    # 1. ???????? ???????? ???????
    txs = db.query(Transaction).filter(
        Transaction.organization_id == organization_id,
        Transaction.transaction_date >= start_date
    ).all()

    daily_trend = {}
    total_sales = 0.0
    total_expenses = 0.0
    total_tax = 0.0
    payment_methods = {"cash": 0.0, "card": 0.0, "cliq": 0.0, "delivery_apps": 0.0}

    for tx in txs:
        d_str = str(tx.transaction_date)
        if d_str not in daily_trend:
            daily_trend[d_str] = {"sales": 0.0, "expenses": 0.0}

        if tx.transaction_type == "SALE":
            total_sales += tx.total_amount
            total_tax += tx.tax_amount
            daily_trend[d_str]["sales"] += tx.total_amount
            if tx.payment_breakdown:
                for k, v in tx.payment_breakdown.items():
                    if k in payment_methods and isinstance(v, (int, float)):
                        payment_methods[k] += v
        else:
            total_expenses += tx.total_amount
            daily_trend[d_str]["expenses"] += tx.total_amount

    # 2. ?????????
    flags = db.query(AuditFlag).filter(
        AuditFlag.organization_id == organization_id,
        AuditFlag.resolved == False
    ).order_by(AuditFlag.created_at.desc()).limit(10).all()

    return {
        "period_days": days,
        "kpis": {
            "total_sales": round(total_sales, 3),
            "total_expenses": round(total_expenses, 3),
            "net_cash_flow": round(total_sales - total_expenses, 3),
            "total_tax_collected": round(total_tax, 3)
        },
        "daily_trend": [{"date": k, **v} for k, v in sorted(daily_trend.items())],
        "payment_distribution": payment_methods,
        "recent_audit_flags": [
            {
                "id": f.id,
                "severity": f.severity,
                "flag_type": f.flag_type,
                "message": f.message,
                "created_at": str(f.created_at)
            } for f in flags
        ]
    }
