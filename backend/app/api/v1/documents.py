import hashlib
import uuid
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schema import Organization, Branch, Document, Transaction, TransactionItem, AuditFlag
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum
from app.services.ai_parser import AIParserService
from app.services.validator import FinancialValidator

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload")
async def upload_and_process_document(
    file: Optional[UploadFile] = File(None),
    text_notes: Optional[str] = Form(None),
    organization_id: Optional[str] = Form(None),
    branch_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    رفع ومعالجة مستند أو صورة إغلاق كاشير Z-Report واستخراج المبالغ والضرائب والتفاصيل آلياً.
    """
    # التحقق من وجود المنشأة الافتراضية أو إنشاؤها تلقائياً
    if not organization_id:
        org = db.query(Organization).first()
        if not org:
            org = Organization(name="المؤسسة التجارية", industry_type="retail", currency="JOD")
            db.add(org)
            db.commit()
            db.refresh(org)
        organization_id = org.id
    else:
        org = db.query(Organization).filter(Organization.id == organization_id).first()

    business_context = None
    if org:
        branches_list = [b.name for b in org.branches] if org.branches else []
        business_context = {
            "business_name": org.name,
            "industry_type": org.industry_type,
            "tax_number": org.tax_number,
            "branches": branches_list
        }

    image_bytes = None
    file_hash = None
    mime_type = "image/jpeg"

    if file:
        image_bytes = await file.read()
        file_hash = hashlib.sha256(image_bytes).hexdigest()
        mime_type = file.content_type or "image/jpeg"

        # التحقق من عدم تكرار رفع نفس المستند
        existing_doc = db.query(Document).filter(
            Document.organization_id == organization_id,
            Document.file_hash == file_hash
        ).first()

        if existing_doc:
            raise HTTPException(status_code=400, detail="تم رفع هذه الفاتورة/المستند مسبقاً في النظام لمنع تكرار القيود.")

    # 1. الاستخراج الذكي عبر نماذج الذكاء الاصطناعي
    extracted_data: ExtractedDocumentData = await AIParserService.parse_document(
        image_bytes=image_bytes,
        text_content=text_notes,
        mime_type=mime_type,
        business_context=business_context
    )

    if extracted_data.notes == "API_TEMPORARY_ERROR":
        raise HTTPException(
            status_code=503, 
            detail="محرك التحليل الذكي يواجه ضغطاً مؤقتاً في الخدمة، يرجى إعادة المحاولة بعد لحظات."
        )

    # 2. التدقيق المحاسبي وفحص الامتثال الضريبي والرياضي
    validation = FinancialValidator.validate(extracted_data)

    # 3. حفظ المستند في قاعدة البيانات
    doc = Document(
        organization_id=organization_id,
        branch_id=branch_id,
        file_hash=file_hash,
        document_type=extracted_data.document_type.value,
        raw_ai_response=extracted_data.model_dump(),
        status=validation.status
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 4. حفظ المعاملة المالية
    tx_type = "SALE" if extracted_data.document_type in [DocumentTypeEnum.SALES_Z_REPORT, DocumentTypeEnum.SALES_RECEIPT] else "EXPENSE"
    if extracted_data.document_type == DocumentTypeEnum.PURCHASE_INVOICE:
        tx_type = "PURCHASE"

    parsed_date = date.today()
    if extracted_data.date:
        try:
            parsed_date = datetime.strptime(extracted_data.date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = date.today()

    tx = Transaction(
        organization_id=organization_id,
        branch_id=branch_id,
        document_id=doc.id,
        transaction_type=tx_type,
        transaction_date=parsed_date,
        invoice_number=extracted_data.invoice_number,
        merchant_or_supplier_name=extracted_data.merchant_or_branch_name,
        subtotal=extracted_data.subtotal,
        tax_amount=extracted_data.tax_amount,
        discount_amount=extracted_data.discount_amount,
        total_amount=extracted_data.total_amount,
        payment_breakdown=extracted_data.payment_breakdown.model_dump(),
        supplier_tax_id=extracted_data.supplier_tax_id,
        is_deductible_expense=validation.tax_deductible,
        notes=extracted_data.notes
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    # 5. حفظ بنود المعاملة إن وجدت
    for item in extracted_data.items:
        t_item = TransactionItem(
            transaction_id=tx.id,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_price=item.total_price,
            tax_rate=item.tax_rate or 0.16,
            tax_amount=item.tax_amount or 0.0
        )
        db.add(t_item)

    # 6. تسجيل تنبيهات التدقيق في حال وجود ملاحظات أو فروقات
    for flag in validation.flags:
        a_flag = AuditFlag(
            organization_id=organization_id,
            transaction_id=tx.id,
            document_id=doc.id,
            severity=flag.severity,
            flag_type=flag.flag_type,
            message=flag.message
        )
        db.add(a_flag)

    db.commit()

    return {
        "success": True,
        "message": "تمت معالجة وتدقيق المستند بنجاح.",
        "document_id": doc.id,
        "transaction_id": tx.id,
        "validation_status": validation.status,
        "flags_count": len(validation.flags),
        "flags": [f.model_dump() for f in validation.flags],
        "extracted_summary": {
            "type": tx_type,
            "total_amount": tx.total_amount,
            "tax_amount": tx.tax_amount,
            "payment_breakdown": tx.payment_breakdown,
            "merchant_or_branch": tx.merchant_or_supplier_name
        }
    }
