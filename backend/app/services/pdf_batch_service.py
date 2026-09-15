import io
import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Callable, Awaitable
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

from app.models.schema import Organization, Branch, Document, Transaction, TransactionItem, AuditFlag
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum
from app.services.ai_parser import AIParserService
from app.services.validator import FinancialValidator

class PDFBatchService:
    """
    خدمة تفكيك ومعالجة ملفات الـ PDF متعددة الصفحات والفواتير.
    تضمن استقلالية المعالجة (Isolated Pipeline)، وتسجيل كل فاتورة على حدى،
    واحتساب الإحصائيات الكاملة للحزمة.
    """

    @classmethod
    async def process_pdf(
        cls,
        pdf_bytes: bytes,
        file_name: str,
        db: Session,
        organization_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        if not pdf_bytes:
            raise ValueError("ملف الـ PDF فارغ أو غير صالح.")

        # 1. فتح الـ PDF وحساب عدد الصفحات
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            total_pages = len(reader.pages)
        except Exception as e:
            raise ValueError(f"تعذر قراءة ملف PDF: {e}")

        if total_pages == 0:
            raise ValueError("ملف الـ PDF لا يحتوي على أي صفحات.")

        # 2. تحديد المنشأة وسياق النشاط التجاري
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

        # 3. تهيئة عدادات الإحصائيات الشاملة
        batch_id = str(uuid.uuid4())
        created_transactions = []
        audit_warnings = []
        
        sales_count = 0
        total_sales_amount = 0.0
        total_output_tax = 0.0

        purchases_count = 0
        total_purchases_amount = 0.0
        total_input_tax = 0.0

        expenses_count = 0
        total_expenses_amount = 0.0

        approved_count = 0
        needs_review_count = 0
        total_invoices_found = 0

        # 4. المعالجة صفحة بصفحة (Isolated Page Splitting)
        for page_idx in range(total_pages):
            page_num = page_idx + 1
            if progress_callback:
                try:
                    await progress_callback(page_num, total_pages)
                except Exception:
                    pass

            # استخراج بايتات الصفحة كـ PDF أحادي مستقل
            writer = PdfWriter()
            writer.add_page(reader.pages[page_idx])
            page_buf = io.BytesIO()
            writer.write(page_buf)
            single_page_bytes = page_buf.getvalue()

            try:
                page_invoices = await AIParserService.parse_pdf_page(
                    pdf_page_bytes=single_page_bytes,
                    page_number=page_num,
                    business_context=business_context
                )
            except Exception as e:
                print(f"[PDFBatchService] Error processing page {page_num}: {e}", flush=True)
                audit_warnings.append(f"صفحة {page_num}: تعذر استخراج الفواتير آلياً بسبب خطأ مؤقت ({str(e)[:80]})")
                continue

            if not page_invoices:
                print(f"[PDFBatchService] Page {page_num}: No invoices found.", flush=True)
                continue

            # 5. تدقيق وتسجيل كل فاتورة في الصفحة على حدى
            for inv_sub_idx, inv_data in enumerate(page_invoices):
                # تجاهل الفواتير الوهمية أو الصفرية بدون بنود
                if inv_data.total_amount <= 0 and not inv_data.items:
                    continue

                total_invoices_found += 1
                validation = FinancialValidator.validate(inv_data)

                # حفظ سجل المستند
                doc = Document(
                    organization_id=organization_id,
                    branch_id=branch_id,
                    file_hash=None,
                    file_url=f"batch:{batch_id}:{file_name}:p{page_num}",
                    document_type=inv_data.document_type.value,
                    raw_ai_response=inv_data.model_dump(),
                    status=validation.status
                )
                db.add(doc)
                db.flush()

                # تحديد نوع المعاملة
                if inv_data.document_type in [DocumentTypeEnum.SALES_RECEIPT, DocumentTypeEnum.SALES_Z_REPORT]:
                    tx_type = "SALE"
                elif inv_data.document_type == DocumentTypeEnum.PURCHASE_INVOICE:
                    tx_type = "PURCHASE"
                else:
                    tx_type = "EXPENSE"

                # تاريخ المعاملة
                parsed_date = date.today()
                if inv_data.date:
                    try:
                        parsed_date = datetime.strptime(inv_data.date, "%Y-%m-%d").date()
                    except ValueError:
                        parsed_date = date.today()

                inv_number = inv_data.invoice_number or f"PDF-P{page_num}-{inv_sub_idx+1}"
                merchant_name = inv_data.merchant_or_branch_name or ("الفرع الرئيسي" if tx_type == "SALE" else "مورد تجاري")

                # حفظ المعاملة المستقلة
                tx = Transaction(
                    organization_id=organization_id,
                    branch_id=branch_id,
                    document_id=doc.id,
                    transaction_type=tx_type,
                    transaction_date=parsed_date,
                    invoice_number=inv_number,
                    merchant_or_supplier_name=merchant_name,
                    subtotal=round(inv_data.subtotal, 3),
                    tax_amount=round(inv_data.tax_amount, 3),
                    discount_amount=round(inv_data.discount_amount, 3),
                    total_amount=round(inv_data.total_amount, 3),
                    payment_breakdown=inv_data.payment_breakdown.model_dump(),
                    supplier_tax_id=inv_data.supplier_tax_id,
                    is_deductible_expense=validation.tax_deductible,
                    notes=f"مستخرج من صفحة {page_num} من ملف ({file_name})" + (f" | {inv_data.notes}" if inv_data.notes else "")
                )
                db.add(tx)
                db.flush()

                # حفظ البنود إن وجدت
                for item in inv_data.items:
                    t_item = TransactionItem(
                        transaction_id=tx.id,
                        description=item.description,
                        quantity=item.quantity,
                        unit_price=round(item.unit_price, 3),
                        total_price=round(item.total_price, 3),
                        tax_rate=item.tax_rate or 0.16,
                        tax_amount=round(item.tax_amount or 0.0, 3)
                    )
                    db.add(t_item)

                # تسجيل تنبيهات التدقيق إن وجدت
                for flag in validation.flags:
                    a_flag = AuditFlag(
                        organization_id=organization_id,
                        transaction_id=tx.id,
                        document_id=doc.id,
                        severity=flag.severity,
                        flag_type=flag.flag_type,
                        message=f"[صفحة {page_num}] {flag.message}"
                    )
                    db.add(a_flag)

                # تحديث عدادات الحزمة
                if validation.status == "PROCESSED":
                    approved_count += 1
                else:
                    needs_review_count += 1
                    for f in validation.flags:
                        audit_warnings.append(f"صفحة {page_num} ({merchant_name}): {f.message}")

                if tx_type == "SALE":
                    sales_count += 1
                    total_sales_amount += tx.total_amount
                    total_output_tax += tx.tax_amount
                elif tx_type == "PURCHASE":
                    purchases_count += 1
                    total_purchases_amount += tx.total_amount
                    total_input_tax += tx.tax_amount
                else: # EXPENSE
                    expenses_count += 1
                    total_expenses_amount += tx.total_amount
                    if validation.tax_deductible:
                        total_input_tax += tx.tax_amount

                created_transactions.append({
                    "id": tx.id,
                    "page_number": page_num,
                    "type": tx_type,
                    "merchant_or_supplier": merchant_name,
                    "invoice_number": inv_number,
                    "total_amount": round(tx.total_amount, 3),
                    "tax_amount": round(tx.tax_amount, 3),
                    "status": validation.status,
                    "payment_breakdown": tx.payment_breakdown,
                    "flags": [f.message for f in validation.flags]
                })

        db.commit()

        net_tax = round(total_output_tax - total_input_tax, 3)

        return {
            "batch_id": batch_id,
            "file_name": file_name,
            "total_pages": total_pages,
            "processed_pages": total_pages,
            "total_invoices": total_invoices_found,
            "sales_count": sales_count,
            "total_sales_amount": round(total_sales_amount, 3),
            "purchases_count": purchases_count,
            "total_purchases_amount": round(total_purchases_amount, 3),
            "expenses_count": expenses_count,
            "total_expenses_amount": round(total_expenses_amount, 3),
            "total_output_tax": round(total_output_tax, 3),
            "total_input_tax": round(total_input_tax, 3),
            "net_tax_liability": net_tax,
            "approved_count": approved_count,
            "needs_review_count": needs_review_count,
            "warnings": audit_warnings,
            "invoices": created_transactions
        }
