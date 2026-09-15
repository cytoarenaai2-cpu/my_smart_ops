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
