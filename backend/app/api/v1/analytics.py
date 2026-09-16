from datetime import date, timedelta, datetime
from typing import Optional, Dict, Any, List
import io
import csv
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.database import get_db
from app.models.schema import Organization, Branch, Transaction, AuditFlag, Document, TransactionItem, User
from app.core.security import get_optional_current_user, resolve_tenant_org_id, UserRoleEnum
from app.services.daily_summary import DailySummaryService

class TransactionUpdatePayload(BaseModel):
    transaction_type: Optional[str] = None
    merchant_or_supplier_name: Optional[str] = None
    total_amount: Optional[float] = None
    subtotal: Optional[float] = None
    service_charge: Optional[float] = None
    tax_amount: Optional[float] = None
    supplier_tax_id: Optional[str] = None
    payment_breakdown: Optional[Dict[str, float]] = None
    notes: Optional[str] = None
    approve: bool = True

class OrganizationProfilePayload(BaseModel):
    name: str
    industry_type: Optional[str] = "مطاعم ومقاهي"
    tax_number: Optional[str] = None
    branches: Optional[List[str]] = None
    auto_daily_brief_enabled: Optional[bool] = True
    daily_brief_time: Optional[str] = "08:30"

class BriefingSchedulePayload(BaseModel):
    auto_daily_brief_enabled: bool = True
    daily_brief_time: str = "08:30"

router = APIRouter(prefix="/analytics", tags=["Analytics & Reporting"])

@router.get("/daily-brief")
def get_daily_morning_brief(
    organization_id: Optional[str] = Query(None),
    target_date: Optional[date] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    إرجاع ملخص الصباح التنفيذي الحقيقي للعمليات المسجلة مع عزل المنشآت.
    """
    organization_id = resolve_tenant_org_id(current_user, organization_id, db)
    if not organization_id:
        raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة مسجلة.")

    chosen_date = target_date or date.today()
    return DailySummaryService.generate_morning_brief(db, organization_id, chosen_date)


@router.get("/dashboard-summary")
def get_dashboard_summary(
    organization_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=90),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    تغذية لوحة التحكم التنفيذية بمخططات الأداء الحقيقية مع عزل المنشآت.
    """
    organization_id = resolve_tenant_org_id(current_user, organization_id, db)
    if not organization_id:
        raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة.")

    start_date = date.today() - timedelta(days=days)

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

    # 2. التنبيهات غير المحلولة
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
            "total_tax_collected": round(total_tax, 3),
            "transactions_count": len(txs)
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


@router.get("/recent-transactions")
def get_recent_transactions(
    organization_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    branch: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    سجل العمليات الفعلي المباشر مع عزل المنشآت الصارم.
    """
    organization_id = resolve_tenant_org_id(current_user, organization_id, db)
    if not organization_id:
        return []

    query = db.query(Transaction).filter(Transaction.organization_id == organization_id)

    if branch and branch != "ALL":
        query = query.filter(Transaction.merchant_or_supplier_name.ilike(f"%{branch}%"))

    if tx_type and tx_type != "ALL":
        query = query.filter(Transaction.transaction_type == tx_type)

    if days and days > 0:
        start_d = date.today() - timedelta(days=days)
        query = query.filter(Transaction.transaction_date >= start_d)

    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Transaction.merchant_or_supplier_name.ilike(s),
                Transaction.invoice_number.ilike(s),
                Transaction.notes.ilike(s),
                Transaction.supplier_tax_id.ilike(s)
            )
        )

    txs = query.order_by(Transaction.created_at.desc()).all()

    type_labels = {
        "SALE": "مبيعات (كاشير)",
        "EXPENSE": "مصروف تشغيلي",
        "PURCHASE": "مشتريات بضاعة"
    }

    result = []
    for t in txs:
        unresolved_flags = [f.message for f in t.audit_flags if not f.resolved]
        item_status = "معتمد"
        if unresolved_flags:
            item_status = "يحتاج مراجعة"

        if status and status != "ALL":
            if status == "APPROVED" and item_status != "معتمد":
                continue
            elif status == "NEEDS_REVIEW" and item_status != "يحتاج مراجعة":
                continue

        result.append({
            "id": t.id,
            "date": str(t.transaction_date),
            "type": type_labels.get(t.transaction_type, t.transaction_type),
            "raw_type": t.transaction_type,
            "merchant_or_branch": t.merchant_or_supplier_name or "الفرع الرئيسي",
            "invoice_number": t.invoice_number or "بدون رقم",
            "subtotal": round(t.subtotal or 0.0, 3),
            "service_charge": round(t.service_charge or 0.0, 3),
            "tax_amount": round(t.tax_amount, 3),
            "total_amount": round(t.total_amount, 3),
            "supplier_tax_id": t.supplier_tax_id or "",
            "payment_breakdown": t.payment_breakdown or {},
            "status": item_status,
            "flags": unresolved_flags,
            "notes": t.notes or ""
        })

    return result[:limit]


@router.get("/export/transactions")
def export_transactions_csv(
    organization_id: Optional[str] = Query(None),
    branch: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    تصدير كشف العمليات الحسابية والضريبية بملف CSV متوافق 100% مع Microsoft Excel باللغة العربية (UTF-8 BOM).
    """
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            raise HTTPException(status_code=404, detail="لم يتم العثور على منشأة")
        organization_id = org.id

    query = db.query(Transaction).filter(Transaction.organization_id == organization_id)

    if branch and branch != "ALL":
        query = query.filter(Transaction.merchant_or_supplier_name.ilike(f"%{branch}%"))

    if tx_type and tx_type != "ALL":
        query = query.filter(Transaction.transaction_type == tx_type)

    if days and days > 0:
        start_d = date.today() - timedelta(days=days)
        query = query.filter(Transaction.transaction_date >= start_d)

    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Transaction.merchant_or_supplier_name.ilike(s),
                Transaction.invoice_number.ilike(s),
                Transaction.notes.ilike(s),
                Transaction.supplier_tax_id.ilike(s)
            )
        )

    txs = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).all()

    type_labels = {
        "SALE": "مبيعات (كاشير)",
        "EXPENSE": "مصروف تشغيلي",
        "PURCHASE": "مشتريات بضاعة"
    }

    output = io.StringIO()
    # Write UTF-8 BOM so Excel opens it with perfect Arabic font
    output.write('\ufeff')
    writer = csv.writer(output)

    # Headers
    writer.writerow([
        "معرف العملية",
        "التاريخ",
        "نوع العملية",
        "الفرع / المتجر / المورد",
        "رقم الفاتورة",
        "المبلغ قبل الضريبة (د.أ)",
        "بدل الخدمة (د.أ)",
        "قيمة الضريبة 16% (د.أ)",
        "المبلغ الإجمالي الفعلي (د.أ)",
        "الرقم الضريبي للمورد (JoFotara)",
        "نقد (كاش)",
        "بطاقات (POS)",
        "كليك (CliQ)",
        "تطبيقات التوصيل",
        "حالة الاعتماد المحاسبي",
        "ملاحظات التدقيق والتسوية"
    ])

    for t in txs:
        unresolved_flags = [f.message for f in t.audit_flags if not f.resolved]
        item_status = "معتمد ومطابق"
        if unresolved_flags:
            item_status = "يحتاج مراجعة"

        if status and status != "ALL":
            if status == "APPROVED" and item_status != "معتمد ومطابق":
                continue
            elif status == "NEEDS_REVIEW" and item_status != "يحتاج مراجعة":
                continue

        pb = t.payment_breakdown or {}
        writer.writerow([
            t.id,
            str(t.transaction_date),
            type_labels.get(t.transaction_type, t.transaction_type),
            t.merchant_or_supplier_name or "الفرع الرئيسي",
            t.invoice_number or "",
            f"{t.subtotal or 0.0:.3f}",
            f"{t.service_charge or 0.0:.3f}",
            f"{t.tax_amount or 0.0:.3f}",
            f"{t.total_amount or 0.0:.3f}",
            t.supplier_tax_id or "",
            f"{pb.get('cash', 0.0):.3f}",
            f"{pb.get('card', 0.0):.3f}",
            f"{pb.get('cliq', 0.0):.3f}",
            f"{pb.get('delivery_apps', 0.0):.3f}",
            item_status,
            t.notes or (" ; ".join(unresolved_flags) if unresolved_flags else "")
        ])

    csv_content = output.getvalue()
    filename = f"smart_ops_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=csv_content.encode('utf-8-sig'),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.put("/transactions/{transaction_id}")
def update_and_approve_transaction(
    transaction_id: str,
    payload: TransactionUpdatePayload,
    db: Session = Depends(get_db)
):
    """
    تعديل بيانات العملية المحاسبية وإدخال البيانات الناقصة (المبلغ، الضريبة، الرقم الضريبي) واعتمادها.
    """
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="لم يتم العثور على العملية المطلوبة.")

    if payload.transaction_type:
        tx.transaction_type = payload.transaction_type.upper()
    if payload.merchant_or_supplier_name is not None:
        tx.merchant_or_supplier_name = payload.merchant_or_supplier_name.strip()
    if payload.total_amount is not None:
        tx.total_amount = round(float(payload.total_amount), 3)
    if payload.subtotal is not None:
        tx.subtotal = round(float(payload.subtotal), 3)
    if payload.service_charge is not None:
        tx.service_charge = round(float(payload.service_charge), 3)
    if payload.tax_amount is not None:
        tx.tax_amount = round(float(payload.tax_amount), 3)
    if payload.supplier_tax_id is not None:
        tax_id = payload.supplier_tax_id.strip()
        tx.supplier_tax_id = tax_id if tax_id else None
        if tax_id:
            tx.is_deductible_expense = True
    if payload.payment_breakdown is not None:
        tx.payment_breakdown = payload.payment_breakdown

    if payload.approve:
        for flag in tx.audit_flags:
            flag.resolved = True
        if tx.document:
            tx.document.status = "PROCESSED"
        
        approval_note = "[تمت المراجعة والتعديل اليدوي والاعتماد]"
        if payload.notes:
            tx.notes = f"{payload.notes} | {approval_note}"
        elif tx.notes and approval_note not in tx.notes:
            tx.notes = f"{tx.notes} | {approval_note}"
        else:
            tx.notes = approval_note

    db.commit()
    db.refresh(tx)

    return {
        "success": True,
        "message": "تم حفظ تعديلات العملية بنجاح واعتمادها محاسبياً وضريبياً.",
        "transaction_id": tx.id,
        "total_amount": tx.total_amount,
        "transaction_type": tx.transaction_type,
        "status": "معتمد" if payload.approve else "يحتاج مراجعة"
    }


@router.post("/transactions/{transaction_id}/approve")
def approve_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """
    اعتماد العملية المحاسبية وإغلاق ملاحظات وفروقات التدقيق المرتبطة بها يدوياً من قبل المستخدم/المحاسب.
    """
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="لم يتم العثور على العملية المطلوبة.")

    # 1. تسوية وإغلاق جميع تنبيهات وفروقات التدقيق للعملية
    for flag in tx.audit_flags:
        flag.resolved = True

    # 2. تحديث حالة المستند الأصلي المرتبط
    if tx.document:
        tx.document.status = "PROCESSED"

    # 3. إجازة المصروف ضريبياً ومحاسبياً
    tx.is_deductible_expense = True

    # 4. توثيق الاعتماد اليدوي في الملاحظات
    approval_note = "[تم الاعتماد والمطابقة يدوياً بواسطة الإدارة]"
    if tx.notes:
        if approval_note not in tx.notes:
            tx.notes = f"{tx.notes} | {approval_note}"
    else:
        tx.notes = approval_note

    db.commit()
    db.refresh(tx)

    return {
        "success": True,
        "message": "تم اعتماد العملية بنجاح وتسوية كافة ملاحظات وفروقات التدقيق.",
        "transaction_id": tx.id,
        "status": "معتمد"
    }


@router.post("/reset-data")
def reset_all_data(db: Session = Depends(get_db)):
    """
    تصفير كافة العمليات والمعاملات وإرجاع النظام إلى نقطة البداية النظيفة.
    """
    db.query(AuditFlag).delete()
    db.query(TransactionItem).delete()
    db.query(Transaction).delete()
    db.query(Document).delete()
    db.commit()
    return {"success": True, "message": "تم تصفير كافة العمليات بنجاح. النظام الآن نظيف وجاهز لتسجيل عملياتك الحقيقية."}


@router.get("/organization-profile")
def get_organization_profile(
    organization_id: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    جلب بيانات هوية المنشأة والنشاط التجاري والفروع مع عزل الصلاحيات.
    """
    target_org_id = resolve_tenant_org_id(current_user, organization_id, db)
    org = db.query(Organization).filter(Organization.id == target_org_id).first() if target_org_id else db.query(Organization).first()
    if not org:
        org = Organization(name="المؤسسة التجارية", industry_type="مطاعم ومقاهي", currency="JOD")
        db.add(org)
        db.commit()
        db.refresh(org)
        
    branches = db.query(Branch).filter(Branch.organization_id == org.id).all()
    if not branches:
        main_b = Branch(organization_id=org.id, name="الفرع الرئيسي")
        db.add(main_b)
        db.commit()
        branches = [main_b]

    is_super = bool(current_user and current_user.role == UserRoleEnum.SUPER_ADMIN)

    return {
        "id": org.id,
        "name": org.name,
        "industry_type": org.industry_type or "مطاعم ومقاهي",
        "tax_number": org.tax_number or "",
        "currency": org.currency or "JOD",
        "branches": [b.name for b in branches],
        "telegram_chat_id": org.telegram_chat_id or "",
        "has_dedicated_bot": bool(org.telegram_bot_token),
        "auto_daily_brief_enabled": org.auto_daily_brief_enabled if org.auto_daily_brief_enabled is not None else True,
        "daily_brief_time": org.daily_brief_time or "08:30",
        "is_locked_for_user": not is_super
    }


@router.put("/organization-profile")
def update_organization_profile(
    payload: OrganizationProfilePayload,
    organization_id: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    تحديث هوية المنشأة:
    - محمي ومقفل: لا يستطيع مدير المنشأة العادي تعديل الاسم، النشاط، الرقم الضريبي، أو الفروع.
    - يسمح فقط لمدير المنشأة بتعديل الجدولة الصباحية.
    - مالك المنصة (Super Admin) هو الوحيد المخول بتعديل كافة الحقول.
    """
    target_org_id = resolve_tenant_org_id(current_user, organization_id, db)
    org = db.query(Organization).filter(Organization.id == target_org_id).first() if target_org_id else db.query(Organization).first()
    if not org:
        raise HTTPException(status_code=404, detail="لم يتم العثور على المنشأة.")

    is_super = bool(current_user and current_user.role == UserRoleEnum.SUPER_ADMIN)

    if current_user and not is_super:
        has_name_change = payload.name and payload.name.strip() != org.name
        has_industry_change = payload.industry_type and payload.industry_type.strip() != (org.industry_type or "")
        current_tin = (org.tax_number or "").strip()
        new_tin = (payload.tax_number or "").strip()
        has_tax_change = payload.tax_number is not None and new_tin != current_tin
        
        current_branches = {b.name.strip() for b in org.branches}
        new_branches = {b.strip() for b in (payload.branches or []) if b.strip()}
        has_branch_change = payload.branches is not None and current_branches != new_branches

        if has_name_change or has_industry_change or has_tax_change or has_branch_change:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="عذراً، تعديل اسم المنشأة ونوع النشاط والرقم الضريبي وإدارة الفروع محصور بمالك المنصة (Super Admin) فقط. يمكنك فقط تعديل الجدولة الصباحية."
            )

    if is_super:
        if payload.name:
            org.name = payload.name.strip()
        if payload.industry_type:
            org.industry_type = payload.industry_type.strip()
        if payload.tax_number is not None:
            org.tax_number = payload.tax_number.strip() or None
            org.is_tax_registered = bool(org.tax_number)

        if payload.branches is not None:
            existing_branches = db.query(Branch).filter(Branch.organization_id == org.id).all()
            existing_names = {b.name.strip() for b in existing_branches}
            target_names = {b.strip() for b in payload.branches if b.strip()}
            for b in existing_branches:
                if b.name.strip() not in target_names:
                    db.delete(b)
            for name in target_names:
                if name not in existing_names:
                    db.add(Branch(organization_id=org.id, name=name))

    if payload.auto_daily_brief_enabled is not None:
        org.auto_daily_brief_enabled = payload.auto_daily_brief_enabled
    if payload.daily_brief_time is not None:
        org.daily_brief_time = payload.daily_brief_time.strip()

    db.commit()
    db.refresh(org)

    branches = db.query(Branch).filter(Branch.organization_id == org.id).all()

    return {
        "success": True,
        "message": "تم حفظ الإعدادات بنجاح.",
        "profile": {
            "id": org.id,
            "name": org.name,
            "industry_type": org.industry_type,
            "tax_number": org.tax_number or "",
            "branches": [b.name for b in branches],
            "telegram_chat_id": org.telegram_chat_id or "",
            "auto_daily_brief_enabled": org.auto_daily_brief_enabled,
            "daily_brief_time": org.daily_brief_time or "08:30",
            "is_locked_for_user": not is_super
        }
    }


@router.put("/briefing-schedule")
def update_briefing_schedule(
    payload: BriefingSchedulePayload,
    organization_id: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    نقطة مخصصة لمدير المنشأة لضبط الجدولة الآلية للتقرير الصباحي وموعده بحرية تامة في أي وقت.
    """
    target_org_id = resolve_tenant_org_id(current_user, organization_id, db)
    org = db.query(Organization).filter(Organization.id == target_org_id).first() if target_org_id else db.query(Organization).first()
    if not org:
        raise HTTPException(status_code=404, detail="لم يتم العثور على المنشأة.")

    org.auto_daily_brief_enabled = payload.auto_daily_brief_enabled
    org.daily_brief_time = payload.daily_brief_time.strip()
    db.commit()

    return {
        "success": True,
        "message": f"تم تحديث الجدولة الصباحية بنجاح إلى الساعة {org.daily_brief_time}.",
        "auto_daily_brief_enabled": org.auto_daily_brief_enabled,
        "daily_brief_time": org.daily_brief_time
    }
