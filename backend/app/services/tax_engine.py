from typing import List, Dict, Any, Optional
from datetime import date
from pydantic import BaseModel, Field
from app.models.schema import Transaction, AuditFlag, Organization
from app.core.config import settings

class TaxPositionResult(BaseModel):
    # مبيعات
    gross_sales: float = Field(0.0, description="إجمالي المبيعات الشاملة")
    taxable_sales_subtotal: float = Field(0.0, description="المبيعات الخاضعة للضريبة قبل الـ 16%")
    output_tax_collected: float = Field(0.0, description="ضريبة المبيعات المحصلة لحساب الضريبة (16%)")
    exempt_or_zero_sales: float = Field(0.0, description="مبيعات معفاة أو بنسبة صفرية")

    # مشتريات ومصروفات
    gross_expenses_and_purchases: float = Field(0.0, description="إجمالي المشتريات والمصروفات المسجلة")
    eligible_purchases_subtotal: float = Field(0.0, description="المشتريات المؤهلة المقبولة ضريبياً")
    eligible_input_tax: float = Field(0.0, description="ضريبة المدخلات القابلة للخصم قانونياً (رد الضريبة)")
    
    # المخاطر والنفقات المرفوضة
    ineligible_expenses_subtotal: float = Field(0.0, description="نفقات ومصروفات غير مقبولة ضريبياً (فاقدة للرقم الضريبي/المستند)")
    lost_input_tax_deduction: float = Field(0.0, description="ضريبة مهددة بالضياع لعدم وجود فواتير إلكترونية مؤهلة")

    # الصافي النهائي
    net_sales_tax_payable: float = Field(0.0, description="صافي ضريبة المبيعات المستحقة للدفع للدائرة")
    tax_credit_carried_forward: float = Field(0.0, description="رصيد ضريبي دائن مدور للفترة التالية")

    # ضريبة الدخل التقديرية
    estimated_taxable_income: float = Field(0.0, description="صافي الدخل التقديري الخاضع لضريبة الدخل")

class PaymentReconciliationSummary(BaseModel):
    total_sales_reported: float = 0.0
    cash_collected: float = 0.0
    cards_pos_collected: float = 0.0
    cliq_collected: float = 0.0
    delivery_collected: float = 0.0
    bank_transfer_collected: float = 0.0
    other_collected: float = 0.0
    total_payments_reconciled: float = 0.0
    variance: float = 0.0
    has_discrepancy: bool = False

class JordanTaxEngine:
    """
    محرك التدقيق والامتثال الضريبي الأردني (Jordan Tax & JoFotara Compliance Engine).
    يقوم بمطابقة الفواتير مع تعليمات الفوترة الإلكترونية وقانون ضريبة المبيعات والدخل.
    """
    STANDARD_SALES_TAX_RATE = 0.16  # النسبة العامة 16% في الأردن

    @classmethod
    def calculate_tax_position(cls, transactions: List[Transaction]) -> TaxPositionResult:
        gross_sales = 0.0
        taxable_sales_subtotal = 0.0
        output_tax_collected = 0.0
        exempt_or_zero_sales = 0.0

        gross_expenses = 0.0
        eligible_purchases_subtotal = 0.0
        eligible_input_tax = 0.0
        ineligible_expenses_subtotal = 0.0
        lost_input_tax = 0.0

        for tx in transactions:
            if tx.transaction_type == "SALE":
                gross_sales += tx.total_amount
                if tx.tax_status == "STANDARD_16":
                    # احتساب الوعاء الخاضع للضريبة بما يشمل بدل الخدمة في قطاع المطاعم
                    taxable_sales_subtotal += (tx.subtotal + (tx.service_charge or 0.0))
                    output_tax_collected += tx.tax_amount
                else:
                    exempt_or_zero_sales += tx.total_amount
            
            elif tx.transaction_type in ["PURCHASE", "EXPENSE"]:
                gross_expenses += tx.total_amount
                
                # فحص أهلية الخصم الضريبي بموجب تعليمات الفوترة الإلكترونية الأردنية (JoFotara)
                # شرط: وجود رقم ضريبي للمورد + عدم وسم المصروف كغير مقبول
                is_eligible = bool(tx.supplier_tax_id and tx.is_deductible_expense)

                if is_eligible:
                    eligible_purchases_subtotal += tx.subtotal
                    eligible_input_tax += tx.tax_amount
                else:
                    ineligible_expenses_subtotal += tx.total_amount
                    # الضريبة التي كان يمكن استردادها لكنها فُقدت لغياب الفاتورة النظامية
                    lost_input_tax += tx.tax_amount

        # حساب الصافي المستحق أو الرصيد الدائن المدور
        net_difference = output_tax_collected - eligible_input_tax
        net_payable = max(0.0, net_difference)
        tax_credit = max(0.0, -net_difference)

        # تقدير الدخل الخاضع لضريبة الدخل (الإيرادات - المصروفات المقبولة فقط)
        estimated_taxable_income = max(0.0, taxable_sales_subtotal - eligible_purchases_subtotal)

        return TaxPositionResult(
            gross_sales=round(gross_sales, 3),
            taxable_sales_subtotal=round(taxable_sales_subtotal, 3),
            output_tax_collected=round(output_tax_collected, 3),
            exempt_or_zero_sales=round(exempt_or_zero_sales, 3),
            gross_expenses_and_purchases=round(gross_expenses, 3),
            eligible_purchases_subtotal=round(eligible_purchases_subtotal, 3),
            eligible_input_tax=round(eligible_input_tax, 3),
            ineligible_expenses_subtotal=round(ineligible_expenses_subtotal, 3),
            lost_input_tax_deduction=round(lost_input_tax, 3),
            net_sales_tax_payable=round(net_payable, 3),
            tax_credit_carried_forward=round(tax_credit, 3),
            estimated_taxable_income=round(estimated_taxable_income, 3)
        )

    @classmethod
    def reconcile_payments(cls, transactions: List[Transaction]) -> PaymentReconciliationSummary:
        total_sales = 0.0
        cash = 0.0
        cards = 0.0
        cliq = 0.0
        delivery = 0.0
        bank_transfer = 0.0
        other = 0.0

        for tx in transactions:
            if tx.transaction_type == "SALE":
                total_sales += tx.total_amount
                pb = tx.payment_breakdown or {}
                # في حال عدم وجود تفصيل للمدفوعات، تعتبر نقدية كاش افتراضياً
                if not pb or not any(pb.values()):
                    cash += tx.total_amount
                else:
                    cash += pb.get("cash", 0.0)
                    cards += pb.get("card", 0.0)
                    cliq += pb.get("cliq", 0.0)
                    delivery += pb.get("delivery_apps", 0.0)
                    bank_transfer += pb.get("bank_transfer", 0.0)
                    other += pb.get("other", 0.0)

        total_payments = cash + cards + cliq + delivery + bank_transfer + other
        variance = round(abs(total_sales - total_payments), 3)
        has_discrepancy = variance > 0.050  # أكثر من 50 فلس

        return PaymentReconciliationSummary(
            total_sales_reported=round(total_sales, 3),
            cash_collected=round(cash, 3),
            cards_pos_collected=round(cards, 3),
            cliq_collected=round(cliq, 3),
            delivery_collected=round(delivery, 3),
            bank_transfer_collected=round(bank_transfer, 3),
            other_collected=round(other, 3),
            total_payments_reconciled=round(total_payments, 3),
            variance=variance,
            has_discrepancy=has_discrepancy
        )

    @classmethod
    def generate_pre_filing_audit_report(
        cls, 
        organization: Organization, 
        transactions: List[Transaction], 
        audit_flags: List[AuditFlag],
        period_name: str = "الفترة الحالية"
    ) -> Dict[str, Any]:
        """
        توليد ملف التدقيق الشامل قبل تقديم الإقرار لضريبة الدخل والمبيعات الأردنية (ISTD).
        """
        tax_pos = cls.calculate_tax_position(transactions)
        reconcile = cls.reconcile_payments(transactions)

        # حساب درجة الامتثال (Compliance Score) من 100
        critical_count = sum(1 for f in audit_flags if f.severity == "CRITICAL" and not f.resolved)
        warning_count = sum(1 for f in audit_flags if f.severity == "WARNING" and not f.resolved)
        
        score_penalty = (critical_count * 15) + (warning_count * 5)
        if tax_pos.lost_input_tax_deduction > 50:
            score_penalty += 10
        if reconcile.has_discrepancy:
            score_penalty += 10

        compliance_score = max(50, 100 - score_penalty)

        # تحديد التوصيات الموجهة للمحاسب القانوني
        recommendations = []
        if tax_pos.ineligible_expenses_subtotal > 0:
            recommendations.append(
                f"يوجد مصروفات بقيمة {tax_pos.ineligible_expenses_subtotal:,.3f} د.أ غير معززة برقم ضريبي للمورد، يوصى بطلب فواتير إلكترونية JoFotara لخصمها."
            )
        if reconcile.has_discrepancy:
            recommendations.append(
                f"يوجد فارق تسوية ({reconcile.variance:,.3f} د.أ) بين مبيعات الكاشير والمقبوضات البنكية وكليك، يرجى مطابقة كشف الحساب البنكي."
            )
        if tax_pos.net_sales_tax_payable > 0:
            recommendations.append(
                f"الضريبة العامة على المبيعات المقدرة للتصريح والدفع هي: {tax_pos.net_sales_tax_payable:,.3f} د.أ."
            )
        else:
            recommendations.append(
                f"لديك رصيد ضريبي دائن مدور بقيمة: {tax_pos.tax_credit_carried_forward:,.3f} د.أ يمكن ترصيده للفترات الضريبية القادمة."
            )

        earliest_date = str(min((t.transaction_date for t in transactions), default=""))
        latest_date = str(max((t.transaction_date for t in transactions), default=""))

        return {
            "metadata": {
                "organization_name": organization.name,
                "tax_number": organization.tax_number or "غير مدخل",
                "period": period_name,
                "transactions_count": len(transactions),
                "date_range": {
                    "from": earliest_date if earliest_date else None,
                    "to": latest_date if latest_date else None
                },
                "report_generated_date": str(date.today()),
                "compliance_score": compliance_score,
                "is_audit_ready": compliance_score >= 85,
                "disclaimer": settings.LEGAL_DISCLAIMER
            },
            "tax_position": tax_pos.model_dump(),
            "payment_reconciliation": reconcile.model_dump(),
            "unresolved_audit_flags_count": len([f for f in audit_flags if not f.resolved]),
            "audit_flags": [
                {"severity": f.severity, "type": f.flag_type, "message": f.message}
                for f in audit_flags if not f.resolved
            ],
            "cpa_recommendations": recommendations
        }
