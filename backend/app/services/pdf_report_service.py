import os
import io
from typing import Dict, Any, Optional
from datetime import datetime

import arabic_reshaper
from bidi.algorithm import get_display

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class PDFReportGenerator:
    """
    محرك توليد تقارير PDF الرسمية بهوية المنشأة ووفق معايير الامتثال الضريبي الأردني (JoFotara / ISTD).
    يدعم اللغة العربية بنسبة 100% مع ضبط الاتجاه (RTL) وتشكيل الحروف وتنسيق الجداول.
    """

    _fonts_registered = False
    _font_regular = "Helvetica"
    _font_bold = "Helvetica-Bold"

    @classmethod
    def _ensure_fonts(cls):
        if cls._fonts_registered:
            return

        candidate_pairs = [
            ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
            ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
            ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        ]

        for reg_path, bold_path in candidate_pairs:
            if os.path.exists(reg_path) and os.path.exists(bold_path):
                try:
                    pdfmetrics.registerFont(TTFont("Arabic-Regular", reg_path))
                    pdfmetrics.registerFont(TTFont("Arabic-Bold", bold_path))
                    cls._font_regular = "Arabic-Regular"
                    cls._font_bold = "Arabic-Bold"
                    cls._fonts_registered = True
                    return
                except Exception as e:
                    print(f"[PDFReportGenerator] Error registering font {reg_path}: {e}")

        cls._font_regular = "Helvetica"
        cls._font_bold = "Helvetica-Bold"
        cls._fonts_registered = True

    @classmethod
    def ar(cls, text: Any) -> str:
        """تهيئة وتشكيل النص العربي للعرض السليم (RTL) في مستندات PDF"""
        if text is None:
            return ""
        s = str(text).strip()
        if not s:
            return ""
        try:
            reshaper = arabic_reshaper.ArabicReshaper(
                configuration={
                    "delete_harakat": True,
                    "support_ligatures": True,
                }
            )
            reshaped = reshaper.reshape(s)
            return get_display(reshaped)
        except Exception:
            return s

    @classmethod
    def generate_tax_report_pdf(cls, report_data: Dict[str, Any]) -> bytes:
        """
        بناء مستند PDF رسمي للإقرار ومراجعة التدقيق الضريبي الشامل.
        يرجع مصفوفة بايتات (bytes) مباشرة للتحميل عبر الويب أو الإرسال لتيليجرام.
        """
        cls._ensure_fonts()

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=28,
            rightMargin=28,
            topMargin=26,
            bottomMargin=26
        )

        font_reg = cls._font_regular
        font_bld = cls._font_bold

        styles = getSampleStyleSheet()
        
        style_title = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName=font_bld,
            fontSize=16,
            leading=22,
            alignment=1,
            textColor=colors.HexColor("#0f172a")
        )
        
        style_subtitle = ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontName=font_reg,
            fontSize=9.0,
            leading=13,
            alignment=1,
            textColor=colors.HexColor("#475569")
        )

        style_sec_header = ParagraphStyle(
            "SectionHeader",
            parent=styles["Normal"],
            fontName=font_bld,
            fontSize=10.5,
            leading=15,
            alignment=2,
            textColor=colors.HexColor("#0284c7")
        )

        meta = report_data.get("metadata", {})
        pos = report_data.get("tax_position", {})
        rec = report_data.get("payment_reconciliation", {})
        cpa_recs = report_data.get("cpa_recommendations", [])

        story = []

        # 1. الترويسة الرئيسية والشعار
        story.append(Paragraph(cls.ar("ملف المراجعة والإقرار الضريبي الشامل (JoFotara / ISTD)"), style_title))
        story.append(Spacer(1, 3))
        story.append(Paragraph(cls.ar("مستخرج آلياً وفقاً لقانون الضريبة العامة على المبيعات ونظام الفوترة الإلكترونية الأردني 2025"), style_subtitle))
        story.append(Spacer(1, 10))

        # 2. بطاقة معلومات المنشأة والفترة (Metadata Card)
        comp_score = meta.get("compliance_score", 100)
        is_ready = meta.get("is_audit_ready", True)
        status_badge_text = f"درجة الجاهزية: {comp_score}% ({'جاهز للاعتماد الضريبي' if is_ready else 'يتطلب مراجعة'})"

        date_range_str = "—"
        if meta.get("date_range") and meta["date_range"].get("from"):
            date_range_str = f"{meta['date_range']['from']} إلى {meta['date_range'].get('to', '')}"

        meta_data = [
            [
                cls.ar(f"اسم المنشأة: {meta.get('organization_name', 'المنشأة التجارية')}"),
                cls.ar(f"الرقم الضريبي: {meta.get('tax_number', 'غير مدخل')}")
            ],
            [
                cls.ar(f"فترة الإقرار: {meta.get('period', 'كافة العمليات')}"),
                cls.ar(f"عدد العمليات المشمولة: {meta.get('transactions_count', 0)} فاتورة")
            ],
            [
                cls.ar(f"نطاق التواريخ: {date_range_str}"),
                cls.ar(f"تاريخ استخراج التقرير: {meta.get('report_generated_date', datetime.today().strftime('%Y-%m-%d'))}")
            ],
            [
                cls.ar(status_badge_text),
                cls.ar("العملة المعتمدة: دينار أردني (JOD)")
            ]
        ]

        meta_table = Table(meta_data, colWidths=[270, 270])
        meta_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_bld),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
            ("BACKGROUND", (0, 3), (0, 3), colors.HexColor("#dcfce7") if is_ready else colors.HexColor("#fef3c7")),
            ("TEXTCOLOR", (0, 3), (0, 3), colors.HexColor("#15803d") if is_ready else colors.HexColor("#b45309")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 12))

        # 3. جدول ملخص ضريبة المبيعات العامة 16% (Sales Tax Breakdown)
        story.append(Paragraph(cls.ar("1. وعاء ضريبة المبيعات العامة (16%) والموقف الضريبي الصافي:"), style_sec_header))
        story.append(Spacer(1, 4))

        tax_table_data = [
            [cls.ar("البيان المحاسبي والضريبي (ISTD)"), cls.ar("المبلغ (دينار أردني)")],
            [cls.ar("إجمالي المبيعات الخاضعة للضريبة 16% (شاملة بدل الخدمة)"), f"{pos.get('taxable_sales_subtotal', 0.0):,.3f}"],
            [cls.ar("ضريبة المبيعات العامة المحصلة - ضريبة المخرجات (Output Tax 16%)"), f"{pos.get('output_tax_collected', 0.0):,.3f}"],
            [cls.ar("ضريبة المدخلات المقبولة للخصم قانونياً (Eligible Input Tax)"), f"({pos.get('eligible_input_tax', 0.0):,.3f})"],
            [cls.ar("مشتريات ونفقات غير مقبولة ضريبياً (لغياب الرقم الضريبي/JoFotara)"), f"{pos.get('ineligible_expenses_subtotal', 0.0):,.3f}"],
            [cls.ar("ضريبة مهددة بالضياع نتيجة فواتير غير معززة برقم ضريبي"), f"{pos.get('lost_input_tax_deduction', 0.0):,.3f}"],
        ]

        net_payable = pos.get("net_sales_tax_payable", 0.0)
        tax_credit = pos.get("tax_credit_carried_forward", 0.0)

        if net_payable > 0:
            tax_table_data.append([
                cls.ar("صافي ضريبة المبيعات المستحقة للدفع لدائرة ضريبة الدخل والمبيعات:"),
                f"{net_payable:,.3f} د.أ (مستحق للدفع)"
            ])
        else:
            tax_table_data.append([
                cls.ar("رصيد ضريبي دائن مدور للفترات القادمة:"),
                f"{tax_credit:,.3f} د.أ (رصيد دائن)"
            ])

        tax_table = Table(tax_table_data, colWidths=[380, 160])
        tax_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_reg),
            ("FONTNAME", (0, 0), (-1, 0), font_bld),
            ("FONTNAME", (0, -1), (-1, -1), font_bld),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#f0fdf4")),
            ("BACKGROUND", (0, 4), (-1, 5), colors.HexColor("#fff1f2")),
            ("TEXTCOLOR", (1, 4), (1, 5), colors.HexColor("#be123c")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e0f2fe") if net_payable > 0 else colors.HexColor("#f0fdf4")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#0369a1") if net_payable > 0 else colors.HexColor("#15803d")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (0, -1), 8),
        ]))
        story.append(tax_table)
        story.append(Spacer(1, 12))

        # 4. جدول مطابقة المبيعات مع وسائل التحصيل الفعلية (Payment Reconciliation)
        story.append(Paragraph(cls.ar("2. مطابقة المبيعات المصرحة مع المقبوضات الفعلية (Reconciliation):"), style_sec_header))
        story.append(Spacer(1, 4))

        has_disc = rec.get("has_discrepancy", False)
        variance = rec.get("variance", 0.0)
        total_reported = rec.get("total_sales_reported", 0.0) or 1.0

        def calc_pct(val):
            return f"{(val / total_reported * 100):.1f}%" if total_reported > 0 else "0.0%"

        cash = rec.get("cash_collected", 0.0)
        cards = rec.get("cards_pos_collected", 0.0)
        cliq = rec.get("cliq_collected", 0.0)
        delivery = rec.get("delivery_collected", 0.0)
        other = (rec.get("bank_transfer_collected", 0.0) or 0.0) + (rec.get("other_collected", 0.0) or 0.0)
        total_rec = rec.get("total_payments_reconciled", 0.0)

        rec_table_data = [
            [cls.ar("طريقة التحصيل / الدفع"), cls.ar("المبلغ المحصل (د.أ)"), cls.ar("النسبة من المبيعات")],
            [cls.ar("النقد في الصندوق (Cash)"), f"{cash:,.3f}", calc_pct(cash)],
            [cls.ar("البطاقات وأجهزة نقاط البيع (POS / Visa / Master)"), f"{cards:,.3f}", calc_pct(cards)],
            [cls.ar("التحويل الفوري (CliQ)"), f"{cliq:,.3f}", calc_pct(cliq)],
        ]

        if delivery > 0:
            rec_table_data.append([cls.ar("تطبيقات التوصيل (Delivery Apps)"), f"{delivery:,.3f}", calc_pct(delivery)])
        if other > 0:
            rec_table_data.append([cls.ar("تحويلات بنكية وأخرى (Bank Transfers / Other)"), f"{other:,.3f}", calc_pct(other)])

        rec_table_data.append([
            cls.ar("إجمالي المقبوضات الفعلية المطابقة:"),
            f"{total_rec:,.3f}",
            cls.ar("100% مطابقة" if not has_disc else f"فارق: {variance:,.3f}")
        ])

        rec_table = Table(rec_table_data, colWidths=[270, 140, 130])
        rec_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_reg),
            ("FONTNAME", (0, 0), (-1, 0), font_bld),
            ("FONTNAME", (0, -1), (-1, -1), font_bld),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (2, -1), (2, -1), colors.HexColor("#15803d") if not has_disc else colors.HexColor("#b45309")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (0, -1), 8),
        ]))
        story.append(rec_table)
        story.append(Spacer(1, 12))

        # 5. قسم توصيات وملاحظات المحاسب القانوني (CPA Recommendations)
        if cpa_recs:
            recs_story = []
            recs_story.append(Paragraph(cls.ar("3. توصيات وملاحظات المحاسب القانوني (CPA Audit Notes):"), style_sec_header))
            recs_story.append(Spacer(1, 4))

            rec_rows = []
            for r_txt in cpa_recs:
                rec_rows.append([cls.ar(f"• {r_txt}")])

            recs_table = Table(rec_rows, colWidths=[540])
            recs_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font_reg),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            recs_story.append(recs_table)
            story.append(KeepTogether(recs_story))
            story.append(Spacer(1, 10))

        # 6. التذييل والإخلاء القانوني (Footer Disclaimer)
        disclaimer_text = meta.get(
            "disclaimer",
            "هذا التقرير تم إعداده للأغراض الإدارية والرقابية بناءً على البيانات والمستندات المدخلة، ويخضع للتدقيق النهائي من قبل المحاسب القانوني المعتمد وفقاً لقوانين المملكة الأردنية الهاشمية."
        )

        footer_story = [
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=5),
            Paragraph(cls.ar(disclaimer_text), style_subtitle),
            Spacer(1, 2),
            Paragraph(cls.ar("نظام Smart Ops & JoFotara Compliance Engine — تم التوليد بنجاح"), style_subtitle)
        ]
        story.append(KeepTogether(footer_story))

        doc.build(story)
        return buf.getvalue()
