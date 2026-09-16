from typing import List, Dict, Any
from datetime import date
from sqlalchemy.orm import Session
from app.models.schema import Transaction, Branch, AuditFlag, Organization
from app.core.config import settings

class DailySummaryService:
    @classmethod
    def generate_morning_brief(
        cls, 
        db: Session, 
        organization_id: str, 
        target_date: date
    ) -> Dict[str, Any]:
        """
        توليد التقرير الصباحي التنفيذي للمالك مع تحليل فوري للمبيعات والمصروفات والتنبيهات.
        """
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        org_name = org.name if org else "المنشأة"
        currency = org.currency if org else settings.DEFAULT_CURRENCY

        # 1. استرجاع معاملات اليوم المستهدف (مع الرجوع الذكي لأحدث يوم عمل إذا لم تسجل حركات في التاريخ المحدد)
        txs = db.query(Transaction).filter(
            Transaction.organization_id == organization_id,
            Transaction.transaction_date == target_date
        ).all()

        if not txs:
            latest_tx = db.query(Transaction).filter(
                Transaction.organization_id == organization_id
            ).order_by(Transaction.transaction_date.desc()).first()
            if latest_tx:
                target_date = latest_tx.transaction_date
                txs = db.query(Transaction).filter(
                    Transaction.organization_id == organization_id,
                    Transaction.transaction_date == target_date
                ).all()

        sales_total = 0.0
        tax_collected = 0.0
        expenses_total = 0.0
        
        cash_total = 0.0
        card_total = 0.0
        cliq_total = 0.0
        delivery_total = 0.0

        branch_sales: Dict[str, float] = {}

        for tx in txs:
            branch_name = tx.branch.name if tx.branch else "المركز الرئيسي"
            if tx.transaction_type == "SALE":
                sales_total += tx.total_amount
                tax_collected += tx.tax_amount
                branch_sales[branch_name] = branch_sales.get(branch_name, 0.0) + tx.total_amount
                
                # توزيع المدفوعات
                if tx.payment_breakdown:
                    cash_total += tx.payment_breakdown.get("cash", 0.0)
                    card_total += tx.payment_breakdown.get("card", 0.0)
                    cliq_total += tx.payment_breakdown.get("cliq", 0.0)
                    delivery_total += tx.payment_breakdown.get("delivery_apps", 0.0)
            elif tx.transaction_type in ["EXPENSE", "PURCHASE"]:
                expenses_total += tx.total_amount

        net_estimate = sales_total - expenses_total

        # 2. استرجاع التنبيهات غير المحلولة
        flags = db.query(AuditFlag).filter(
            AuditFlag.organization_id == organization_id,
            AuditFlag.resolved == False
        ).all()

        # 3. صياغة التقرير التنفيذي المناسب للواتساب وتيليجرام
        briefing_lines = [
            f"☕ *صباح الخير، ملخص أعمالك ليوم {target_date.strftime('%Y-%m-%d')}*",
            f"🏢 منشأة: *{org_name}*",
            "───────────────────",
            f"📈 *إجمالي المبيعات:* {sales_total:,.3f} {currency}",
            f"💰 *المصروفات المسجلة:* {expenses_total:,.3f} {currency}",
            f"💵 *صافي التدفق اليومي:* {net_estimate:,.3f} {currency}",
            "",
            "📊 *تفصيل طرق استلام الأموال:*",
            f"  • النقد (الكاش): {cash_total:,.3f} {currency}",
            f"  • البطاقات (POS/Visa): {card_total:,.3f} {currency}",
            f"  • كليك (CliQ): {cliq_total:,.3f} {currency}",
        ]

        if delivery_total > 0:
            briefing_lines.append(f"  • تطبيقات التوصيل: {delivery_total:,.3f} {currency}")

        if branch_sales:
            briefing_lines.append("")
            briefing_lines.append("🏬 *أداء الفروع:*")
            for b_name, b_rev in branch_sales.items():
                pct = (b_rev / sales_total * 100) if sales_total > 0 else 0
                briefing_lines.append(f"  • {b_name}: {b_rev:,.3f} {currency} ({pct:.1f}%)")

        if flags:
            briefing_lines.append("")
            briefing_lines.append(f"⚠️ *تنبيهات وملاحظات التدقيق ({len(flags)}):*")
            for flag in flags[:3]:  # أول 3 تنبيهات عاجلة
                briefing_lines.append(f"  - [{flag.severity}] {flag.message}")
        else:
            briefing_lines.append("")
            briefing_lines.append("✅ جميع الأرقام والعمليات الحسابية متطابقة وسليمة.")

        briefing_lines.append("")
        briefing_lines.append(f"ℹ️ _{settings.LEGAL_DISCLAIMER}_")

        formatted_message = "\n".join(briefing_lines)

        return {
            "target_date": str(target_date),
            "organization_name": org_name,
            "currency": currency,
            "metrics": {
                "sales_total": sales_total,
                "expenses_total": expenses_total,
                "net_estimate": net_estimate,
                "tax_collected": tax_collected,
                "payment_breakdown": {
                    "cash": cash_total,
                    "card": card_total,
                    "cliq": cliq_total,
                    "delivery_apps": delivery_total
                },
                "branch_sales": branch_sales,
                "unresolved_flags_count": len(flags)
            },
            "whatsapp_formatted_text": formatted_message
        }

    @classmethod
    def generate_period_report(
        cls,
        db: Session,
        organization_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period_label: str = "الفترة المحددة",
        all_time: bool = False
    ) -> Dict[str, Any]:
        """
        توليد تقرير مالي وإحصائي شامل لأي فترة زمنية مخصصة (شهر معين، سنة، أو كافة العمليات).
        """
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        org_name = org.name if org else "المنشأة"
        currency = org.currency if org else settings.DEFAULT_CURRENCY

        query = db.query(Transaction).filter(Transaction.organization_id == organization_id)
        if not all_time:
            if start_date:
                query = query.filter(Transaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(Transaction.transaction_date <= end_date)

        txs = query.order_by(Transaction.transaction_date.desc()).all()

        if not txs:
            msg = (
                f"📊 *تقرير الأعمال: {period_label}*\n"
                f"🏢 منشأة: *{org_name}*\n"
                "───────────────────\n"
                "ℹ️ لم يتم العثور على أي فواتير أو عمليات مسجلة في هذه الفترة.\n\n"
                "💡 *لتسجيل فواتير جديدة:*\n"
                "أرسل صورة الفاتورة، أو سجل رسالة صوتية، أو ارفع ملف PDF وسيقوم النظام بتسجيلها وتحديث التقارير فوراً!"
            )
            return {
                "period_label": period_label,
                "organization_name": org_name,
                "total_invoices": 0,
                "formatted_text": msg
            }

        sales_txs = [t for t in txs if t.transaction_type == "SALE"]
        expenses_txs = [t for t in txs if t.transaction_type in ["EXPENSE", "PURCHASE"]]

        sales_total = sum(t.total_amount for t in sales_txs)
        service_total = sum(t.service_charge or 0.0 for t in sales_txs)
        tax_collected = sum(t.tax_amount for t in sales_txs)

        expenses_total = sum(t.total_amount for t in expenses_txs)
        eligible_input_tax = sum(t.tax_amount for t in expenses_txs if t.supplier_tax_id and t.is_deductible_expense)
        net_estimate = sales_total - expenses_total
        net_tax_liability = tax_collected - eligible_input_tax

        # تفصيل طرق الدفع
        cash_total = 0.0
        card_total = 0.0
        cliq_total = 0.0
        delivery_total = 0.0
        other_total = 0.0

        branch_sales: Dict[str, float] = {}

        for tx in sales_txs:
            branch_name = tx.branch.name if tx.branch else "المركز الرئيسي"
            branch_sales[branch_name] = branch_sales.get(branch_name, 0.0) + tx.total_amount

            pb = tx.payment_breakdown or {}
            if not pb or not any(pb.values()):
                cash_total += tx.total_amount
            else:
                cash_total += pb.get("cash", 0.0)
                card_total += pb.get("card", 0.0)
                cliq_total += pb.get("cliq", 0.0)
                delivery_total += pb.get("delivery_apps", 0.0)
                other_total += pb.get("bank_transfer", 0.0) + pb.get("other", 0.0)

        earliest = str(min(t.transaction_date for t in txs))
        latest = str(max(t.transaction_date for t in txs))

        lines = [
            f"📊 *تقرير الأعمال المالي: {period_label}*",
            f"🏢 منشأة: *{org_name}*",
            f"📅 نطاق التواريخ: `{earliest}` إلى `{latest}`",
            f"🧾 العمليات: *{len(txs)} فاتورة* ({len(sales_txs)} مبيعات، {len(expenses_txs)} مشتريات)",
            "───────────────────",
            f"📈 *إجمالي المبيعات:* {sales_total:,.3f} {currency}",
        ]

        if service_total > 0:
            lines.append(f"  • منها بدل خدمة: {service_total:,.3f} {currency}")

        lines.extend([
            f"🛒 *المشتريات والمصروفات:* {expenses_total:,.3f} {currency}",
            f"💵 *صافي الأرباح التشغيلية:* {net_estimate:,.3f} {currency}",
            "",
            "🏛️ *الموقف الضريبي (JoFotara):*",
            f"  • ضريبة المخرجات: {tax_collected:,.3f} {currency}",
            f"  • ضريبة المدخلات المقبولة: {eligible_input_tax:,.3f} {currency}",
            f"  • صافي الالتزام الضريبي: {net_tax_liability:,.3f} {currency}",
            "",
            "💳 *طرق التحصيل الفعلية:*",
            f"  • كاش الصندوق: {cash_total:,.3f} {currency}",
            f"  • بطاقات (POS): {card_total:,.3f} {currency}",
            f"  • كليك (CliQ): {cliq_total:,.3f} {currency}",
        ])

        if delivery_total > 0:
            lines.append(f"  • تطبيقات التوصيل: {delivery_total:,.3f} {currency}")
        if other_total > 0:
            lines.append(f"  • تحويل بنكي / أخرى: {other_total:,.3f} {currency}")

        if branch_sales and len(branch_sales) > 1:
            lines.append("")
            lines.append("🏬 *أداء الفروع:*")
            for b_name, b_rev in branch_sales.items():
                pct = (b_rev / sales_total * 100) if sales_total > 0 else 0
                lines.append(f"  • {b_name}: {b_rev:,.3f} {currency} ({pct:.1f}%)")

        lines.append("")
        lines.append("🖥️ _مستخرج فورياً من قاعدة البيانات المحاسبية الذكية_")

        return {
            "period_label": period_label,
            "organization_name": org_name,
            "total_invoices": len(txs),
            "sales_total": sales_total,
            "expenses_total": expenses_total,
            "net_estimate": net_estimate,
            "formatted_text": "\n".join(lines)
        }

    @classmethod
    def generate_tax_telegram_brief(
        cls,
        db: Session,
        organization_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period_name: Optional[str] = None,
        all_time: bool = False
    ) -> str:
        """
        توليد تقرير ضريبي تنفيذي موجه لتطبيق تيليجرام بموجب معايير الفوترة الإلكترونية JoFotara.
        """
        from app.services.tax_engine import JordanTaxEngine

        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if not org:
            return "⚠️ لم يتم العثور على منشأة مسجلة في النظام."

        query = db.query(Transaction).filter(Transaction.organization_id == organization_id)
        if not all_time:
            if start_date:
                query = query.filter(Transaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(Transaction.transaction_date <= end_date)

        txs = query.order_by(Transaction.transaction_date.desc()).all()
        flags = db.query(AuditFlag).filter(
            AuditFlag.organization_id == organization_id,
            AuditFlag.resolved == False
        ).all()

        report = JordanTaxEngine.generate_pre_filing_audit_report(
            organization=org,
            transactions=txs,
            audit_flags=flags,
            period_name=period_name or "كافة العمليات المسجلة"
        )

        m = report["metadata"]
        p = report["tax_position"]
        rec = report["payment_reconciliation"]

        other_payments = (rec.get("bank_transfer_collected", 0.0) or 0.0) + (rec.get("other_collected", 0.0) or 0.0)

        lines = [
            "🏛️ *ملخص التدقيق والإقرار الضريبي (JoFotara / ISTD)*",
            "─────────────────────────────",
            f"🏢 *المنشأة:* {m['organization_name']}",
            f"🔢 *الرقم الضريبي:* `{m['tax_number']}`",
            f"📅 *الفترة:* {m['period']} ({m['transactions_count']} فاتورة)",
            f"🎯 *درجة الجاهزية الضريبية:* {m['compliance_score']}% ({'جاهز للتقديم ✅' if m['is_audit_ready'] else 'يتطلب مراجعة ⚠️'})",
            "",
            "📊 *1. ملخص المبيعات وضريبة المخرجات (16%):*",
            f"  • مبيعات خاضعة للضريبة (16%): {p['taxable_sales_subtotal']:,.3f} د.أ",
        ]

        if p.get('service_charge_total', 0) > 0:
            lines.append(f"    (منها بدل خدمة مطاعم: {p['service_charge_total']:,.3f} د.أ)")

        lines.append(f"  • ضريبة المبيعات المحصلة (16%): {p['output_tax_collected']:,.3f} د.أ")

        if p.get('exempt_or_zero_sales', 0) > 0:
            lines.append(f"  • مبيعات معفاة / بنسبة صفرية: {p['exempt_or_zero_sales']:,.3f} د.أ")

        lines.append(f"  • *إجمالي المبيعات الشامل للضريبة:* `{p['gross_sales']:,.3f} د.أ`")

        lines.extend([
            "",
            "🛒 *2. المشتريات والمصروفات (ضريبة المدخلات):*",
            f"  • إجمالي المشتريات والمصروفات المسجلة: {p.get('gross_expenses_and_purchases', 0.0):,.3f} د.أ",
            f"  • مشتريات معززة برقم ضريبي (JoFotara): {p.get('eligible_purchases_subtotal', 0.0):,.3f} د.أ",
            f"  • ضريبة المدخلات المقبولة للخصم: ({p['eligible_input_tax']:,.3f}) د.أ",
        ])

        if p.get('ineligible_expenses_subtotal', 0) > 0:
            lines.append(f"  • مصروفات فاقدة للرقم الضريبي: {p['ineligible_expenses_subtotal']:,.3f} د.أ")

        if p['net_sales_tax_payable'] > 0:
            lines.append(f"\n⚖️ *صافي الضريبة المستحقة للدفع للدائرة:* `{p['net_sales_tax_payable']:,.3f} د.أ`")
        else:
            lines.append(f"\n⚖️ *رصيد ضريبي دائن مدور للفترة القادمة:* `{p['tax_credit_carried_forward']:,.3f} د.أ`")

        rec_status = "✅ مطابقة تامة" if not rec['has_discrepancy'] else f"⚠️ فارق {rec['variance']:,.3f} د.أ"

        lines.extend([
            "",
            f"💳 *3. مطابقة وسائل التحصيل:* {rec_status}",
            f"  • كاش: {rec['cash_collected']:,.3f} د.أ",
            f"  • بطاقات POS: {rec['cards_pos_collected']:,.3f} د.أ",
            f"  • كليك CliQ: {rec['cliq_collected']:,.3f} د.أ",
        ])

        if rec.get("delivery_collected", 0.0) > 0:
            lines.append(f"  • توصيل: {rec['delivery_collected']:,.3f} د.أ")
        if other_payments > 0:
            lines.append(f"  • تحويل / أخرى: {other_payments:,.3f} د.أ")

        if report.get("cpa_recommendations"):
            lines.append("")
            lines.append("💡 *ملاحظات وتوصيات المحاسب القانوني:*")
            for r_text in report["cpa_recommendations"][:2]:
                lines.append(f"  • {r_text}")

        lines.append("")
        lines.append("📄 _يمكنك طباعة الإقرار وتنزيل ملف PDF من لوحة التحكم مباشرة._")

        return "\n".join(lines)
