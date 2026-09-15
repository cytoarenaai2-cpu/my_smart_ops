import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum

class AuditFlagResult(BaseModel):
    severity: str  # INFO, WARNING, CRITICAL
    flag_type: str # ARITHMETIC_MISMATCH, PAYMENT_MISMATCH, MISSING_TAX_INVOICE, UNUSUAL_TAX_RATE
    message: str

class ValidationResult(BaseModel):
    is_valid: bool
    status: str  # PROCESSED, NEEDS_REVIEW
    flags: List[AuditFlagResult] = []
    reconciled_total: float
    tax_deductible: bool = True

class FinancialValidator:
    """
    المحرك المسؤول عن فحص العمليات الحسابية ومنع أي أخطاء قد تضر العميل 
    وتجهيز البيانات للفحص الضريبي الأردني.
    """
    
    TOLERANCE = 0.015  # السماحية الحسابية (15 فلساً للتعامل مع التدوير وتقريب الفلس)

    @classmethod
    def validate(cls, data: ExtractedDocumentData) -> ValidationResult:
        flags: List[AuditFlagResult] = []
        status = "PROCESSED"
        is_tax_deductible = True

        # 1. فحص سلامة البنود مقارنة بالمجموع الجزئي أو الإجمالي (Items sum check)
        # في قطاع المطاعم والتجزئة، قد تكون أسعار قائمة الطعام:
        # أ) قبل الضريبة والخدمة (تطابق subtotal)
        # ب) شاملة الضريبة والخدمة Gross (تطابق total_amount)
        # ج) شاملة بدل الخدمة (تطابق subtotal + service_charge)
        if data.items:
            items_sum = round(sum(item.total_price for item in data.items), 3)
            diff_subtotal = abs(items_sum - data.subtotal)
            diff_total = abs(items_sum - data.total_amount)
            diff_with_service = abs(items_sum - (data.subtotal + data.service_charge))

            min_diff = min(diff_subtotal, diff_total, diff_with_service)
            if data.subtotal > 0 and min_diff > cls.TOLERANCE:
                flags.append(AuditFlagResult(
                    severity="WARNING",
                    flag_type="ARITHMETIC_MISMATCH",
                    message=f"مجموع بنود الفاتورة ({items_sum:.3f}) لا يطابق الإجمالي قبل الضريبة ({data.subtotal:.3f}) أو الإجمالي النهائي ({data.total_amount:.3f}) بفارق {min_diff:.3f} د.أ"
                ))
                status = "NEEDS_REVIEW"

        # 2. فحص المعادلة الكلية:
        # الإجمالي = المجموع قبل الضريبة والخدمة + بدل الخدمة + الضريبة - الخصم
        # التحقق التلقائي الذكي من بدل الخدمة إذا كان مدوناً في الملاحظات أو الفارق
        expected_total = round(data.subtotal + data.service_charge + data.tax_amount - data.discount_amount, 3)
        total_diff = abs(expected_total - data.total_amount)

        if total_diff > cls.TOLERANCE and data.service_charge == 0:
            diff_gap = round(data.total_amount - (data.subtotal + data.tax_amount - data.discount_amount), 3)
            # فحص إذا كان الفارق مطابقاً لقيمة خدمة مدونة في الملاحظات
            notes_str = str(data.notes or "")
            s_match = re.search(r'(?:service|خدمة|بدل خدمة)\s*[:=]?\s*(\d+(?:\.\d+)?)', notes_str, re.IGNORECASE)
            if s_match:
                notes_service = float(s_match.group(1))
                if abs(notes_service - diff_gap) <= cls.TOLERANCE:
                    data.service_charge = notes_service
                    expected_total = round(data.subtotal + data.service_charge + data.tax_amount - data.discount_amount, 3)
                    total_diff = abs(expected_total - data.total_amount)

        if data.subtotal > 0 and total_diff > cls.TOLERANCE:
            flags.append(AuditFlagResult(
                severity="CRITICAL",
                flag_type="ARITHMETIC_MISMATCH",
                message=f"الإجمالي النهائي المسجل ({data.total_amount:.3f}) لا يطابق (المجموع: {data.subtotal:.3f} + الخدمة: {data.service_charge:.3f} + الضريبة: {data.tax_amount:.3f} - الخصم: {data.discount_amount:.3f} = {expected_total:.3f}) بفارق {total_diff:.3f} د.أ"
            ))
            status = "NEEDS_REVIEW"

        # 3. مطابقة وسائل الدفع (Payment Reconciliation) لكشوفات الكاشير Z-Report
        total_payments = data.payment_breakdown.total_payments
        if total_payments > 0:
            pay_diff = abs(total_payments - data.total_amount)
            if pay_diff > cls.TOLERANCE:
                flags.append(AuditFlagResult(
                    severity="CRITICAL",
                    flag_type="PAYMENT_MISMATCH",
                    message=f"مجموع وسائل الدفع (كاش: {data.payment_breakdown.cash}, بطاقات: {data.payment_breakdown.card}, كليك: {data.payment_breakdown.cliq}) = {total_payments:.3f} لا يطابق إجمالي المبيعات ({data.total_amount:.3f}) بفارق {pay_diff:.3f} د.أ"
                ))
                status = "NEEDS_REVIEW"

        # 4. التأسيس للمرحلة الضريبية (Jordan JoFotara & ISTD Pre-validation)
        if data.document_type in [DocumentTypeEnum.PURCHASE_INVOICE, DocumentTypeEnum.EXPENSE_RECEIPT]:
            # شرط تعليمات الفوترة الإلكترونية 2025 للمصروفات الكبيرة
            if data.total_amount >= 500.0 and not data.supplier_tax_id:
                flags.append(AuditFlagResult(
                    severity="WARNING",
                    flag_type="MISSING_TAX_INVOICE",
                    message=f"تنبيه ضريبي (JoFotara): المصروف بقيمة {data.total_amount:.3f} د.أ غير معزز برقم ضريبي للمورد. بموجب تعليمات الفوترة الإلكترونية، قد لا يُقبل هذا المصروف ضريبياً."
                ))
                is_tax_deductible = False

            # فحص النسبة الضريبية غير الاعتيادية
            if data.subtotal > 0 and data.tax_amount > 0:
                effective_rate = data.tax_amount / data.subtotal
                # إذا كانت النسبة أعلى من 16% بكثير (أكثر من 17%)
                if effective_rate > 0.17:
                    flags.append(AuditFlagResult(
                        severity="WARNING",
                        flag_type="UNUSUAL_TAX_RATE",
                        message=f"النسبة الضريبية المحسوبة ({effective_rate * 100:.1f}%) أعلى من النسبة العامة المعتادة في الأردن (16%). يرجى مراجعة البند مع المحاسب."
                    ))

        return ValidationResult(
            is_valid=(len([f for f in flags if f.severity == "CRITICAL"]) == 0),
            status=status,
            flags=flags,
            reconciled_total=data.total_amount,
            tax_deductible=is_tax_deductible
        )
