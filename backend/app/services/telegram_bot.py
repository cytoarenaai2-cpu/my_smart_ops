import asyncio
import re
import calendar
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Document, Transaction, AuditFlag
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum
from app.services.ai_parser import AIParserService
from app.services.validator import FinancialValidator
from app.services.daily_summary import DailySummaryService
from app.services.pdf_batch_service import PDFBatchService

class TelegramBotRunner:
    """
    مشغل بوت تيليجرام بنظام الاستطلاع الفردي (Single Instance Long Polling).
    دقيق 100% - يدعم الصور والنصوص والفويس نوت والجدولة الصباحية الآلية.
    """

    MONTH_MAP = {
        'يناير': 1, 'كانون الثاني': 1, 'كانون اول': 12, 'كانون الاول': 12,
        'فبراير': 2, 'شباط': 2,
        'مارس': 3, 'آذار': 3, 'اذار': 3,
        'ابريل': 4, 'أبريل': 4, 'نيسان': 4,
        'مايو': 5, 'أيار': 5, 'ايار': 5,
        'يونيو': 6, 'حزيران': 6,
        'يوليو': 7, 'تموز': 7,
        'اغسطس': 8, 'أغسطس': 8, 'آب': 8, 'اب': 8,
        'سبتمبر': 9, 'أيلول': 9, 'ايلول': 9,
        'اكتوبر': 10, 'أكتوبر': 10, 'تشرين الأول': 10, 'تشرين اول': 10,
        'نوفمبر': 11, 'تشرين الثاني': 11, 'تشرين ثاني': 11,
        'ديسمبر': 12
    }

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://149.154.166.110/bot{self.token}"
        self.file_base_url = f"https://149.154.166.110/file/bot{self.token}"
        self.headers = {"Host": "api.telegram.org"}
        self.offset = 0
        self.is_running = False

    def get_main_keyboard(self) -> dict:
        """لوحة الأزرار السريعة الثابتة أسفل شاشة تيليجرام للتسهيل على العملاء"""
        return {
            "keyboard": [
                [{"text": "📊 تقرير اليوم"}, {"text": "📅 تقرير الشهر"}],
                [{"text": "🏛️ الإقرار الضريبي"}, {"text": "⚠️ تنبيهات التدقيق"}],
                [{"text": "📈 كافة العمليات"}, {"text": "❓ مساعدة وأوامر"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    def get_report_inline_keyboard(self) -> dict:
        """أزرار تفاعلية مضمنة في الرسالة لاختيار فترات التقارير بنقرة واحدة"""
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 تقرير اليوم", "callback_data": "rep_today"},
                    {"text": "⏮️ تقرير الأمس", "callback_data": "rep_yesterday"}
                ],
                [
                    {"text": "📅 الشهر الحالي", "callback_data": "rep_this_month"},
                    {"text": "📆 شهر 4 (2022)", "callback_data": "rep_month_2022_04"}
                ],
                [
                    {"text": "🗓️ سنة 2022 كاملة", "callback_data": "rep_year_2022"},
                    {"text": "📈 كافة العمليات", "callback_data": "rep_all"}
                ],
                [
                    {"text": "🏛️ ملخص JoFotara الضريبي", "callback_data": "tax_all"},
                    {"text": "⚠️ فحص التدقيق", "callback_data": "audit_check"}
                ],
                [
                    {"text": "📄 تحميل إقرار PDF رسمي", "callback_data": "pdf_tax_all"}
                ]
            ]
        }

    async def set_bot_commands(self):
        """تسجيل قائمة الأوامر الرسمية في تيليجرام لتظهر كزر Menu أزرق بجانب خانة الكتابة"""
        url = f"{self.base_url}/setMyCommands"
        commands = [
            {"command": "start", "description": "🚀 بدء التشغيل ولوحة الأزرار"},
            {"command": "today", "description": "📊 تقرير مبيعات اليوم"},
            {"command": "yesterday", "description": "⏮️ تقرير مبيعات الأمس"},
            {"command": "month", "description": "📅 تقرير مبيعات الشهر الحالي"},
            {"command": "tax", "description": "🏛️ الإقرار الضريبي JoFotara"},
            {"command": "pdf", "description": "📄 تحميل إقرار الضريبة PDF"},
            {"command": "all", "description": "📈 كشف كافة العمليات المسجلة"},
            {"command": "audit", "description": "⚠️ تنبيهات التدقيق والمطابقة"},
            {"command": "report", "description": "📑 اختيار أو طلب تقرير مخصص"},
            {"command": "help", "description": "❓ شرح الأوامر وطرق التخصيص"}
        ]
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            try:
                res = await client.post(url, json={"commands": commands}, headers=self.headers)
                if res.status_code == 200:
                    print("[TelegramBot] Registered bot commands menu (setMyCommands).", flush=True)
            except Exception as e:
                print(f"[TelegramBot] set_bot_commands error: {e}", flush=True)

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown", reply_markup: Optional[dict] = None):
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            try:
                res = await client.post(url, json=payload, headers=self.headers)
                if res.status_code != 200:
                    payload.pop("parse_mode", None)
                    await client.post(url, json=payload, headers=self.headers)
            except Exception as e:
                print(f"[TelegramBot] send_message error: {e}")

    async def send_document(
        self,
        chat_id: int,
        file_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None
    ):
        """إرسال مستندات وملفات PDF مباشرة للمستخدم عبر تيليجرام"""
        import json
        url = f"{self.base_url}/sendDocument"
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)

        files = {"document": (filename, file_bytes, "application/pdf")}

        async with httpx.AsyncClient(timeout=35.0, verify=False) as client:
            try:
                res = await client.post(url, data=data, files=files, headers=self.headers)
                if res.status_code != 200:
                    # إعادة المحاولة بدون parse_mode في حال تعذر التنسيق
                    data.pop("parse_mode", None)
                    await client.post(url, data=data, files=files, headers=self.headers)
            except Exception as e:
                print(f"[TelegramBot] send_document error: {e}", flush=True)

    async def _send_tax_report_pdf(
        self,
        chat_id: int,
        start_d: Optional[date] = None,
        end_d: Optional[date] = None,
        label: str = "كافة العمليات المسجلة",
        all_time: bool = False
    ):
        """توليد ملف PDF رسمي للإقرار الضريبي وإرساله كمستند احترافي للمستخدم"""
        from app.services.tax_engine import JordanTaxEngine
        from app.services.pdf_report_service import PDFReportGenerator

        db = SessionLocal()
        try:
            org = db.query(Organization).first()
            if not org:
                await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة.")
                return

            query = db.query(Transaction).filter(Transaction.organization_id == org.id)
            if not all_time:
                if start_d:
                    query = query.filter(Transaction.transaction_date >= start_d)
                if end_d:
                    query = query.filter(Transaction.transaction_date <= end_d)

            txs = query.order_by(Transaction.transaction_date.desc()).all()
            flags = db.query(AuditFlag).filter(
                AuditFlag.organization_id == org.id,
                AuditFlag.resolved == False
            ).all()

            report_data = JordanTaxEngine.generate_pre_filing_audit_report(
                organization=org,
                transactions=txs,
                audit_flags=flags,
                period_name=label
            )

            await self.send_message(chat_id, "⏳ جاري إعداد وتوليد ملف PDF الرسمي للإقرار الضريبي...")
            pdf_bytes = PDFReportGenerator.generate_tax_report_pdf(report_data)

            caption = (
                f"📄 *ملف التدقيق والإقرار الضريبي الرسمي (JoFotara / ISTD)*\n"
                f"🏢 المنشأة: *{org.name}*\n"
                f"📅 الفترة: *{label}*\n"
                f"🎯 درجة الجاهزية: *{report_data['metadata']['compliance_score']}%*"
            )

            filename = f"JoFotara_Tax_Report_{datetime.today().strftime('%Y%m%d')}.pdf"
            await self.send_document(
                chat_id=chat_id,
                file_bytes=pdf_bytes,
                filename=filename,
                caption=caption,
                reply_markup=self.get_main_keyboard()
            )
        except Exception as e:
            print(f"[TelegramBot] _send_tax_report_pdf error: {e}", flush=True)
            await self.send_message(chat_id, f"❌ حدث خطأ أثناء إنشاء ملف PDF: {e}")
        finally:
            db.close()

    def _update_org_chat_id(self, chat_id: int):
        db = SessionLocal()
        try:
            org = db.query(Organization).first()
            if org and str(org.telegram_chat_id) != str(chat_id):
                org.telegram_chat_id = str(chat_id)
                db.commit()
        except Exception as e:
            print(f"[TelegramBot] _update_org_chat_id error: {e}")
        finally:
            db.close()

    def _get_business_context(self) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            org = db.query(Organization).first()
            if org:
                branches = [b.name for b in org.branches] if org.branches else []
                return {
                    "business_name": org.name,
                    "industry_type": org.industry_type,
                    "tax_number": org.tax_number,
                    "branches": branches
                }
            return None
        except Exception as e:
            print(f"[TelegramBot] _get_business_context error: {e}")
            return None
        finally:
            db.close()

    async def handle_voice(self, chat_id: int, voice_obj: dict):
        file_id = voice_obj.get("file_id")
        mime_type = voice_obj.get("mime_type", "audio/ogg")
        if not mime_type or not mime_type.startswith("audio/"):
            mime_type = "audio/ogg"

        await self.send_message(
            chat_id, 
            "🎙️ *تم استلام التسجيل الصوتي بنجاح!*\nجاري الاستماع وتفريغ الأرقام والعمليات عبر الذكاء الاصطناعي وتدقيق الحسابات والضريبة..."
        )

        async with httpx.AsyncClient(timeout=50.0, verify=False) as client:
            get_file_res = await client.get(f"{self.base_url}/getFile?file_id={file_id}", headers=self.headers)
            if get_file_res.status_code != 200:
                await self.send_message(chat_id, "❌ تعذر جلب رابط التسجيل الصوتي من تيليجرام.")
                return

            file_path = get_file_res.json().get("result", {}).get("file_path")
            dl_res = await client.get(f"{self.file_base_url}/{file_path}", headers=self.headers)
            if dl_res.status_code != 200:
                await self.send_message(chat_id, "❌ فشل تحميل ملف الصوت.")
                return
            
            audio_bytes = dl_res.content

        print(f"[TelegramBot] Received voice note ({len(audio_bytes)} bytes). Parsing with AI audio...", flush=True)
        biz_ctx = self._get_business_context()
        extracted_data = await AIParserService.parse_document(
            image_bytes=audio_bytes,
            mime_type=mime_type,
            business_context=biz_ctx
        )

        await self._process_and_save_data(chat_id, extracted_data)

    async def handle_photo(self, chat_id: int, photo_list: list, caption: Optional[str] = None):
        best_photo = photo_list[-1]
        file_id = best_photo.get("file_id")

        await self.send_message(
            chat_id, 
            "⏳ *تم استلام الصورة بنجاح!*\nجاري قراءة وتفريغ الفاتورة بنموذج الذكاء الاصطناعي وتدقيق الحسابات والضريبة..."
        )

        async with httpx.AsyncClient(timeout=45.0, verify=False) as client:
            get_file_res = await client.get(f"{self.base_url}/getFile?file_id={file_id}", headers=self.headers)
            if get_file_res.status_code != 200:
                await self.send_message(chat_id, "❌ تعذر جلب رابط الصورة من تيليجرام.")
                return

            file_path = get_file_res.json().get("result", {}).get("file_path")
            dl_res = await client.get(f"{self.file_base_url}/{file_path}", headers=self.headers)
            if dl_res.status_code != 200:
                await self.send_message(chat_id, "❌ فشل تحميل ملف الصورة.")
                return
            
            image_bytes = dl_res.content

        print(f"[TelegramBot] Received photo ({len(image_bytes)} bytes). Parsing with AI...", flush=True)
        biz_ctx = self._get_business_context()
        extracted_data = await AIParserService.parse_document(
            image_bytes=image_bytes,
            text_content=caption,
            mime_type="image/jpeg",
            business_context=biz_ctx
        )

        await self._process_and_save_data(chat_id, extracted_data)

    async def handle_document(self, chat_id: int, doc_obj: dict, caption: Optional[str] = None):
        file_name = doc_obj.get("file_name", "document.pdf")
        mime_type = doc_obj.get("mime_type", "")
        file_id = doc_obj.get("file_id")

        if not (file_name.lower().endswith(".pdf") or mime_type == "application/pdf"):
            await self.send_message(
                chat_id,
                "ℹ️ *نوع الملف غير مدعوم حالياً.*\nيدعم النظام ملفات PDF متعددة الفواتير، الصور المباشرة (JPG/PNG)، والرسائل الصوتية."
            )
            return

        await self.send_message(
            chat_id,
            f"📄 *تم استلام ملف PDF ({file_name})!*\nجاري تفكيك الصفحات وقراءة وتدقيق الفواتير بالذكاء الاصطناعي..."
        )

        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            get_file_res = await client.get(f"{self.base_url}/getFile?file_id={file_id}", headers=self.headers)
            if get_file_res.status_code != 200:
                await self.send_message(chat_id, "❌ تعذر جلب رابط ملف الـ PDF من تيليجرام.")
                return

            file_path = get_file_res.json().get("result", {}).get("file_path")
            dl_res = await client.get(f"{self.file_base_url}/{file_path}", headers=self.headers)
            if dl_res.status_code != 200:
                await self.send_message(chat_id, "❌ فشل تحميل ملف الـ PDF.")
                return

            pdf_bytes = dl_res.content

        db = SessionLocal()
        try:
            print(f"[TelegramBot] Processing PDF batch ({file_name}, {len(pdf_bytes)} bytes)...", flush=True)
            batch_res = await PDFBatchService.process_pdf(
                pdf_bytes=pdf_bytes,
                file_name=file_name,
                db=db
            )

            # تنسيق الملخص التنفيذي الشامل للحزمة
            lines = [
                f"📑 *ملخص معالجة حزمة PDF ({file_name})*",
                "─────────────────────────────",
                f"📄 *الصفحات المعالجة:* {batch_res['total_pages']} صفحة",
                f"🧾 *إجمالي الفواتير المستخرجة:* {batch_res['total_invoices']} فاتورة",
                "",
                f"📈 *إجمالي المبيعات:* {batch_res['total_sales_amount']:.3f} د.أ ({batch_res['sales_count']} فاتورة)",
                f"🛒 *مشتريات الموردين:* {batch_res['total_purchases_amount']:.3f} د.أ ({batch_res['purchases_count']} فاتورة)",
                f"💰 *المصروفات النثرية:* {batch_res['total_expenses_amount']:.3f} د.أ ({batch_res['expenses_count']} فاتورة)",
                "",
                "🏛️ *المطابقة الضريبية (JoFotara):*",
                f"  • ضريبة المخرجات: {batch_res['total_output_tax']:.3f} د.أ",
                f"  • ضريبة المدخلات: {batch_res['total_input_tax']:.3f} د.أ",
                f"  • صافي الالتزام الضريبي: {batch_res['net_tax_liability']:.3f} د.أ",
                "",
                "📌 *حالة الاعتماد والمطابقة:*",
                f"  • ✅ معتمدة وسليمة: {batch_res['approved_count']} فاتورة",
                f"  • ⚠️ تحتاج مراجعة: {batch_res['needs_review_count']} فاتورة"
            ]

            if batch_res["warnings"]:
                lines.append("")
                lines.append("⚠️ *ملاحظات وتنبيهات التدقيق:*")
                for w in batch_res["warnings"][:5]:
                    lines.append(f"  - {w}")
                if len(batch_res["warnings"]) > 5:
                    lines.append(f"  - _و {len(batch_res['warnings']) - 5} ملاحظات إضافية في لوحة التحكم..._")

            lines.append("")
            lines.append("🖥️ _تم تسجيل كافة الفواتير كقيود مستقلة وتحديث لوحة التحكم فورياً!_")

            await self.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            print(f"[TelegramBot] Error in PDF processing: {e}", flush=True)
            await self.send_message(chat_id, f"❌ حدث خطأ أثناء معالجة ملف الـ PDF: {str(e)[:150]}")
        finally:
            db.close()

    def _parse_report_request(self, text: str) -> Optional[Dict[str, Any]]:
        """التعرف الذكي على طلبات التقارير المخصصة وتحديد الفترات والتواريخ باللغة العربية والإنجليزية"""
        t = text.strip()
        is_tax = bool(re.search(r'(ضريب|tax|jofotara|جوفاتورة|إقرار|اقرار)', t, re.IGNORECASE))
        is_pdf = bool(re.search(r'(pdf|بي دي اف|ملف|مستند|طباعة)', t, re.IGNORECASE))

        # طلب تقرير عام بدون تحديد فترة
        if t in ["/report", "/تقرير", "تقرير", "ملخص", "تقرير مالي", "التقرير"]:
            return {"kind": "interactive", "is_tax": False, "is_pdf": False}

        if t in ["/tax", "/الضريبة", "الضريبة", "تقرير الضريبة", "الإقرار الضريبي", "الاقرار الضريبي", "🏛️ الإقرار الضريبي"]:
            return {"kind": "all", "start": None, "end": None, "is_tax": True, "is_pdf": is_pdf, "label": "كافة العمليات المسجلة"}

        if t in ["/pdf", "/tax_pdf", "pdf", "بي دي اف", "تحميل pdf", "تقرير pdf", "ملف pdf", "تنزيل pdf"]:
            return {"kind": "all", "start": None, "end": None, "is_tax": True, "is_pdf": True, "label": "كافة العمليات المسجلة"}

        # فحص الطلبات العامة للضريبة أو ملفات الـ PDF دون تاريخ محدد
        if (is_tax or is_pdf) and any(w in t for w in ['تقرير', 'ملف', 'تحميل', 'تنزيل', 'طباعة', 'استخراج', 'كشف']) and not any(k in t for k in ['202', 'شهر', 'سنة', 'عام', 'امس', 'أمس', 'اليوم']):
            return {"kind": "all", "start": None, "end": None, "is_tax": True, "is_pdf": is_pdf, "label": "كافة العمليات المسجلة"}

        # 1. نمط YYYY-MM أو MM-YYYY (مثل: 2022-04 أو 04-2022 أو 2022/4)
        m_ym = re.search(r'\b(20\d\d)[-/](0?[1-9]|1[0-2])\b', t)
        if not m_ym:
            m_ym = re.search(r'\b(0?[1-9]|1[0-2])[-/](20\d\d)\b', t)
            if m_ym:
                month, year = int(m_ym.group(1)), int(m_ym.group(2))
                last_day = calendar.monthrange(year, month)[1]
                return {'kind': 'month', 'year': year, 'month': month, 'start': date(year, month, 1), 'end': date(year, month, last_day), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'شهر {month} لسنة {year}'}
        else:
            year, month = int(m_ym.group(1)), int(m_ym.group(2))
            last_day = calendar.monthrange(year, month)[1]
            return {'kind': 'month', 'year': year, 'month': month, 'start': date(year, month, 1), 'end': date(year, month, last_day), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'شهر {month} لسنة {year}'}

        # 2. فحص أسماء الشهور مع أو بدون سنة (مثل: شهر نيسان 2022 أو نيسان)
        m_year = re.search(r'\b(20\d\d)\b', t)
        for m_name, m_num in self.MONTH_MAP.items():
            if m_name in t:
                year = int(m_year.group(1)) if m_year else date.today().year
                last_day = calendar.monthrange(year, m_num)[1]
                return {'kind': 'month', 'year': year, 'month': m_num, 'start': date(year, m_num, 1), 'end': date(year, m_num, last_day), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'شهر {m_name} ({year})'}

        # 3. فحص رقم الشهر (مثل: شهر 4 أو شهر 04)
        m_month_num = re.search(r'شهر\s*(0?[1-9]|1[0-2])\b', t)
        if m_month_num:
            m_num = int(m_month_num.group(1))
            year = int(m_year.group(1)) if m_year else date.today().year
            last_day = calendar.monthrange(year, m_num)[1]
            return {'kind': 'month', 'year': year, 'month': m_num, 'start': date(year, m_num, 1), 'end': date(year, m_num, last_day), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'شهر {m_num} لسنة {year}'}

        # 4. فحص السنة فقط (مثل: سنة 2022، عام 2022، تقرير 2022، /report 2022)
        if (m_year and any(w in t for w in ['سنة', 'عام', 'year', 'تقرير', '/report', '/tax'])) or (m_year and len(t) <= 10):
            year = int(m_year.group(1))
            return {'kind': 'year', 'year': year, 'start': date(year, 1, 1), 'end': date(year, 12, 31), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'سنة {year}'}

        # 5. اليوم / الأمس / الشهر الحالي / كافة العمليات
        if any(w in t for w in ['/today', 'اليوم', 'تقرير اليوم', 'مبيعات اليوم', '📊 تقرير اليوم']):
            return {'kind': 'today', 'start': date.today(), 'end': date.today(), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'اليوم ({date.today()})'}

        if any(w in t for w in ['/yesterday', 'أمس', 'امس', 'تقرير الأمس', 'مبيعات امس', '⏮️ تقرير الأمس']):
            y_date = date.today() - timedelta(days=1)
            return {'kind': 'day', 'start': y_date, 'end': y_date, 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'يوم أمس ({y_date})'}

        if any(w in t for w in ['/month', 'الشهر الحالي', 'هذا الشهر', 'تقرير الشهر', '📅 تقرير الشهر']):
            td = date.today()
            last_day = calendar.monthrange(td.year, td.month)[1]
            return {'kind': 'month', 'year': td.year, 'month': td.month, 'start': date(td.year, td.month, 1), 'end': date(td.year, td.month, last_day), 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': f'الشهر الحالي ({td.year}-{td.month:02d})'}

        if any(w in t for w in ['/all', 'كافة العمليات', 'جميع العمليات', 'كل الفواتير', 'كافة الفترات', '📈 كافة العمليات']):
            return {'kind': 'all', 'start': None, 'end': None, 'is_tax': is_tax, 'is_pdf': is_pdf, 'label': 'كافة العمليات المسجلة'}

        return None

    async def _execute_custom_report(self, chat_id: int, req: dict):
        """تنفيذ وتوليد التقرير المخصص وإرساله إلى محادثة تيليجرام"""
        if req.get("kind") == "interactive":
            msg = (
                "📑 *اختر فترة التقرير المطلوبة بنقرة واحدة من الأزرار التفاعلية:*\n\n"
                "💡 أو يمكنك كتابة طلبك مباشرة بأي صيغة عربية وسيفهمها النظام تلقائياً:\n"
                "• _'تقرير شهر 4 2022'_\n"
                "• _'تقرير سنة 2022'_\n"
                "• _'تقرير الضريبة لسنة 2022'_\n"
                "• _'تحميل تقرير pdf'_\n"
                "• _/report 2022-04_"
            )
            await self.send_message(
                chat_id, 
                msg, 
                reply_markup=self.get_report_inline_keyboard()
            )
            return

        is_pdf = req.get("is_pdf", False)
        start_d = req.get("start")
        end_d = req.get("end")
        label = req.get("label", "الفترة المحددة")
        all_time = (req.get("kind") == "all")

        # إذا طلب المستخدم صراحة ملف PDF
        if is_pdf:
            await self._send_tax_report_pdf(
                chat_id=chat_id,
                start_d=start_d,
                end_d=end_d,
                label=label,
                all_time=all_time
            )
            return

        db = SessionLocal()
        try:
            org = db.query(Organization).first()
            if not org:
                await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة بعد.")
                return

            is_tax = req.get("is_tax", False)

            if is_tax:
                tax_text = DailySummaryService.generate_tax_telegram_brief(
                    db=db,
                    organization_id=org.id,
                    start_date=start_d,
                    end_date=end_d,
                    period_name=label,
                    all_time=all_time
                )
                await self.send_message(chat_id, tax_text, reply_markup=self.get_main_keyboard())
            else:
                rep = DailySummaryService.generate_period_report(
                    db=db,
                    organization_id=org.id,
                    start_date=start_d,
                    end_date=end_d,
                    period_label=label,
                    all_time=all_time
                )
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
        finally:
            db.close()

    async def handle_callback_query(self, cb_query: dict):
        """التعامل مع نقرات الأزرار التفاعلية الشفافة (Inline Buttons)"""
        cb_id = cb_query.get("id")
        data = cb_query.get("data")
        msg = cb_query.get("message", {})
        chat_id = msg.get("chat", {}).get("id")

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            try:
                await client.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": cb_id},
                    headers=self.headers
                )
            except Exception:
                pass

        if not chat_id or not data:
            return

        db = SessionLocal()
        try:
            org = db.query(Organization).first()
            if not org:
                await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة.")
                return

            if data == "rep_today":
                brief = DailySummaryService.generate_morning_brief(db, org.id, date.today())
                await self.send_message(chat_id, brief["whatsapp_formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "rep_yesterday":
                y_date = date.today() - timedelta(days=1)
                rep = DailySummaryService.generate_period_report(db, org.id, start_date=y_date, end_date=y_date, period_label=f"يوم أمس ({y_date})")
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "rep_this_month":
                td = date.today()
                last_day = calendar.monthrange(td.year, td.month)[1]
                rep = DailySummaryService.generate_period_report(db, org.id, start_date=date(td.year, td.month, 1), end_date=date(td.year, td.month, last_day), period_label=f"الشهر الحالي ({td.year}-{td.month:02d})")
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "rep_month_2022_04":
                rep = DailySummaryService.generate_period_report(db, org.id, start_date=date(2022, 4, 1), end_date=date(2022, 4, 30), period_label="شهر 4 (أبريل) 2022")
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "rep_year_2022":
                rep = DailySummaryService.generate_period_report(db, org.id, start_date=date(2022, 1, 1), end_date=date(2022, 12, 31), period_label="سنة 2022 كاملة")
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "rep_all":
                rep = DailySummaryService.generate_period_report(db, org.id, period_label="كافة العمليات المسجلة", all_time=True)
                await self.send_message(chat_id, rep["formatted_text"], reply_markup=self.get_main_keyboard())
            elif data == "tax_all":
                tax_text = DailySummaryService.generate_tax_telegram_brief(db, org.id, all_time=True)
                await self.send_message(chat_id, tax_text, reply_markup=self.get_main_keyboard())
            elif data == "pdf_tax_all":
                await self._send_tax_report_pdf(chat_id, all_time=True, label="كافة العمليات المسجلة")
            elif data == "audit_check":
                flags = db.query(AuditFlag).filter(AuditFlag.organization_id == org.id, AuditFlag.resolved == False).all()
                if not flags:
                    await self.send_message(chat_id, "✅ *سجل التدقيق نظيف تماماً!*\nلا توجد أي ملاحظات أو تنبيهات غير محلولة.", reply_markup=self.get_main_keyboard())
                else:
                    lines = [f"⚠️ *تنبيهات وملاحظات التدقيق المعلقة ({len(flags)}):*", "───────────────────"]
                    for f in flags[:8]:
                        lines.append(f"• [{f.severity}] {f.message}")
                    lines.append("\n🖥️ _يمكنك حل واعتماد هذه التنبيهات من لوحة التحكم بنقرة واحدة._")
                    await self.send_message(chat_id, "\n".join(lines), reply_markup=self.get_main_keyboard())
        finally:
            db.close()

    async def handle_text(self, chat_id: int, text: str):
        text_clean = text.strip()

        # 1. أوامر البدء والترحيب
        if text_clean in ["/start", "ابدأ", "start"]:
            msg = (
                "👋 *أهلاً بك في نظام الإدارة المالية والتدقيق الذكي!*\n\n"
                "هذا البوت يمنحك تحكماً مالياً وضريبياً كاملاً لعمليات منشأتك عبر تيليجرام:\n\n"
                "📊 *لوحة الأزرار السريعة:*\n"
                "تجد أسفل الشاشة 6 أزرار جاهزة تمكنك من طلب أي تقرير بضغطة زر دون كتابة.\n\n"
                "🎯 *تخصيص التقارير الذكي باللغة الطبيعية:*\n"
                "اكتب أي فترة تريدها وسيفهمها النظام فوراً، مثلاً:\n"
                "• _'تقرير شهر 4 2022'_\n"
                "• _'تقرير سنة 2022'_\n"
                "• _'تقرير الضريبة'_\n"
                "• _'تحميل تقرير pdf'_\n"
                "• _/today_ أو _/month_\n\n"
                "📸 *تسجيل الفواتير الذاتي:*\n"
                "أرسل صورة إغلاق كاشير، أو ملف PDF متعدد الفواتير، أو تسجيل صوتي فويس نوت لتفريغها فورياً."
            )
            await self.send_message(
                chat_id, 
                msg, 
                reply_markup=self.get_main_keyboard()
            )
            return

        # 2. دليل المساعدة والتعليمات للعملاء
        if text_clean in ["/help", "مساعدة", "تعليمات", "اوامر", "أوامر", "❓ مساعدة وأوامر"]:
            guide = (
                "📖 *دليل أوامر واختصارات البوت الذكي (Shortcuts & Commands)*\n"
                "─────────────────────────────\n\n"
                "🔘 *1. الأزرار السريعة (أسفل الشاشة):*\n"
                "• *📊 تقرير اليوم:* ملخص مبيعات الوردية اليومية والتحصيلات.\n"
                "• *📅 تقرير الشهر:* ملخص أعمال الشهر الحالي.\n"
                "• *🏛️ الإقرار الضريبي:* احتساب ضريبة المبيعات ومطابقة JoFotara.\n"
                "• *⚠️ تنبيهات التدقيق:* كشف أي فروقات في الصندوق أو الفواتير المعلقة.\n"
                "• *📈 كافة العمليات:* التقرير الإجمالي الشامل لكافة الفواتير.\n\n"
                "⌨️ *2. أوامر السلاش (Slash Commands):*\n"
                "• `/today` - تقرير اليوم\n"
                "• `/yesterday` - تقرير الأمس\n"
                "• `/month` - تقرير الشهر الحالي\n"
                "• `/report` - إظهار قائمة اختيار التقارير التفاعلية\n"
                "• `/tax` - تقرير الإقرار الضريبي الشامل\n"
                "• `/pdf` - تحميل ملف الإقرار الضريبي الرسمي PDF\n"
                "• `/audit` - فحص التدقيق والفروقات\n"
                "• `/all` - كشف كافة العمليات\n\n"
                "🗣️ *3. طلب تقارير مخصصة باللغة العربية (NLP):*\n"
                "يمكنك ببساطة كتابة رسالة عادية مثل:\n"
                "• _'اعطيني تقرير شهر 4 2022'_\n"
                "• _'تقرير سنة 2022'_\n"
                "• _'تقرير شهر نيسان'_\n"
                "• _'تقرير الضريبة لسنة 2022'_\n"
                "• _/report 2022-04_\n\n"
                "📥 *4. إدخال العمليات:* أرسل صورة أو صوت أو PDF مباشرة!"
            )
            await self.send_message(chat_id, guide, reply_markup=self.get_main_keyboard())
            return

        # 3. فحص تنبيهات التدقيق
        if text_clean in ["/audit", "تنبيهات", "تنبيهات التدقيق", "⚠️ تنبيهات التدقيق", "فحص"]:
            db = SessionLocal()
            try:
                org = db.query(Organization).first()
                if org:
                    flags = db.query(AuditFlag).filter(AuditFlag.organization_id == org.id, AuditFlag.resolved == False).all()
                    if not flags:
                        await self.send_message(chat_id, "✅ *سجل التدقيق نظيف تماماً!*\nلا توجد أي ملاحظات أو فروقات حسابية غير محلولة.", reply_markup=self.get_main_keyboard())
                    else:
                        lines = [f"⚠️ *تنبيهات التدقيق المعلقة ({len(flags)}):*", "───────────────────"]
                        for f in flags[:8]:
                            lines.append(f"• [{f.severity}] {f.message}")
                        lines.append("\n🖥️ _يمكنك حل هذه التنبيهات من لوحة التحكم بنقرة واحدة._")
                        await self.send_message(chat_id, "\n".join(lines), reply_markup=self.get_main_keyboard())
                else:
                    await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة.")
            finally:
                db.close()
            return

        # 4. فحص ما إذا كانت الرسالة طلباً لتقرير مخصص (شهر/سنة/يوم/ضريبة/كافة العمليات)
        parsed_report = self._parse_report_request(text_clean)
        if parsed_report:
            await self._execute_custom_report(chat_id, parsed_report)
            return

        # 5. إذا لم تكن طلباً لتقرير، يتم تحليلها كعملية مالية مسجلة عبر الذكاء الاصطناعي
        await self.send_message(chat_id, "⏳ جاري تحليل النص واستخراج الأرقام الحقيقية بدقة...")
        biz_ctx = self._get_business_context()
        extracted_data = await AIParserService.parse_document(
            text_content=text_clean,
            business_context=biz_ctx
        )
        await self._process_and_save_data(chat_id, extracted_data)

    async def _process_and_save_data(self, chat_id: int, extracted_data: ExtractedDocumentData):
        if extracted_data.notes == "API_TEMPORARY_ERROR":
            msg = (
                "⚠️ *تعذر قراءة الصورة حالياً:*\n"
                "حدث بطء أو ضغط مؤقت في الاتصال بنماذج الذكاء الاصطناعي.\n\n"
                "🔄 يرجى إعادة إرسال الصورة الآن وسيتم معالجتها وتفريغها بنجاح."
            )
            await self.send_message(chat_id, msg)
            return

        # منع تسجيل أي عمليات وهمية أو صفرية
        if extracted_data.total_amount <= 0 and len(extracted_data.items) == 0:
            msg = (
                "ℹ️ *لم يتم تسجيل العملية:*\n"
                "لم نتمكن من رصد أي مبالغ مالية أو أرقام واضحة في الرسالة.\n\n"
                "💡 *أمثلة للتسجيل:*\n"
                "• مبيعات: _'مبيعات فرع خلدا كاش 520 وبطاقات 400 وكليك 150'_\n"
                "• مصروف: _'مصروف خضار ومواد 180 دينار كاش'_\n"
                "• أو أرسل صورة واضحة لفاتورة أو كشف كاشير."
            )
            await self.send_message(chat_id, msg)
            return

        validation = FinancialValidator.validate(extracted_data)
        
        db: Session = SessionLocal()
        try:
            org = db.query(Organization).first()
            if not org:
                org = Organization(name="المؤسسة التجارية", currency="JOD")
                db.add(org)
                db.commit()
                db.refresh(org)

            doc = Document(
                organization_id=org.id,
                document_type=extracted_data.document_type.value,
                raw_ai_response=extracted_data.model_dump(),
                status=validation.status
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            tx_type = "SALE" if extracted_data.document_type in [DocumentTypeEnum.SALES_Z_REPORT, DocumentTypeEnum.SALES_RECEIPT] else "EXPENSE"
            tx = Transaction(
                organization_id=org.id,
                document_id=doc.id,
                transaction_type=tx_type,
                transaction_date=date.today(),
                invoice_number=extracted_data.invoice_number,
                merchant_or_supplier_name=extracted_data.merchant_or_branch_name,
                subtotal=extracted_data.subtotal,
                tax_amount=extracted_data.tax_amount,
                total_amount=extracted_data.total_amount,
                payment_breakdown=extracted_data.payment_breakdown.model_dump(),
                supplier_tax_id=extracted_data.supplier_tax_id,
                is_deductible_expense=validation.tax_deductible,
                notes=extracted_data.notes
            )
            db.add(tx)
            db.commit()

            for flag in validation.flags:
                a_flag = AuditFlag(
                    organization_id=org.id,
                    transaction_id=tx.id,
                    document_id=doc.id,
                    severity=flag.severity,
                    flag_type=flag.flag_type,
                    message=flag.message
                )
                db.add(a_flag)
            db.commit()

            pb = extracted_data.payment_breakdown
            status_icon = "✅" if validation.status == "PROCESSED" else "⚠️"
            status_text = "معتمد ومطابق" if validation.status == "PROCESSED" else "يحتاج مراجعة (فروقات)"

            type_labels = {
                "SALES_Z_REPORT": "كشف إغلاق كاشير (Z-Report)",
                "SALES_RECEIPT": "فاتورة مبيعات زبون (إيصال كاشير)",
                "EXPENSE_RECEIPT": "إيصال مصروف يومي ونثريات",
                "PURCHASE_INVOICE": "فاتورة مشتريات وتوريد مورد",
                "BANK_STATEMENT": "كشف بنكي / تحويل CliQ",
                "OTHER": "مستند تجاري عام"
            }
            doc_type_arabic = type_labels.get(extracted_data.document_type.value, extracted_data.document_type.value)

            lines = [
                f"{status_icon} *تم تدقيق وتفريغ العملية الحقيقية بنجاح!*",
                "───────────────────",
                f"🏷️ *نوع المستند:* {doc_type_arabic}",
                f"🏢 *الفرع/المورد:* {extracted_data.merchant_or_branch_name or 'الفرع الرئيسي'}",
                f"💰 *المبلغ الإجمالي:* {extracted_data.total_amount:,.3f} د.أ",
                f"🧾 *قيمة الضريبة:* {extracted_data.tax_amount:,.3f} د.أ",
                "",
                "📊 *طرق التحصيل المسجلة:*",
                f"  • كاش: {pb.cash:,.3f} د.أ",
                f"  • بطاقات (POS): {pb.card:,.3f} د.أ",
                f"  • كليك (CliQ): {pb.cliq:,.3f} د.أ"
            ]

            if pb.delivery_apps > 0:
                lines.append(f"  • تطبيقات التوصيل: {pb.delivery_apps:,.3f} د.أ")

            lines.append("")
            lines.append(f"📌 *حالة الاعتماد المحاسبي:* {status_text}")

            if validation.flags:
                lines.append("")
                lines.append("⚠️ *ملاحظات التدقيق الضريبي:*")
                for f in validation.flags:
                    lines.append(f"  - [{f.severity}] {f.message}")

            lines.append("")
            lines.append("🖥️ _تم تسجيل العملية وتحديث لوحة التحكم فورياً!_")

            formatted_reply = "\n".join(lines)
            await self.send_message(chat_id, formatted_reply)

        finally:
            db.close()

    async def _daily_scheduler_loop(self):
        print("[TelegramBot] Automated Daily Brief Scheduler active...", flush=True)
        last_sent_date = None
        while self.is_running:
            try:
                await asyncio.sleep(30)
                now = datetime.now()
                current_time_str = now.strftime("%H:%M")
                today_date = now.date()

                if last_sent_date == today_date:
                    continue

                db = SessionLocal()
                try:
                    org = db.query(Organization).first()
                    if not org or not org.telegram_chat_id or not org.auto_daily_brief_enabled:
                        continue

                    scheduled_time = org.daily_brief_time or "08:30"
                    if current_time_str == scheduled_time:
                        print(f"[Scheduler] Sending automated daily brief for {today_date} to chat {org.telegram_chat_id}...", flush=True)
                        tx_count = db.query(Transaction).filter(Transaction.organization_id == org.id).count()
                        if tx_count > 0:
                            brief = DailySummaryService.generate_morning_brief(db, org.id, today_date)
                            intro = "☀️ *صباح الخير! إليك ملخصك المالي اليومي المجدول تلقائياً:*\n\n"
                            await self.send_message(int(org.telegram_chat_id), intro + brief["whatsapp_formatted_text"])
                            last_sent_date = today_date
                finally:
                    db.close()
            except Exception as e:
                print(f"[Scheduler] Error in daily scheduler loop: {e}", flush=True)

    async def start_polling(self):
        if not self.token:
            print("[TelegramBot] Error: TELEGRAM_BOT_TOKEN is not set.")
            return

        print("[TelegramBot] Connected to Telegram. Single Polling active (Images + Text + Voice Notes)...")
        self.is_running = True
        
        # تسجيل قائمة الأوامر التلقائية في واجهة تيليجرام
        await self.set_bot_commands()

        scheduler_task = asyncio.create_task(self._daily_scheduler_loop())

        try:
            async with httpx.AsyncClient(timeout=35.0, verify=False) as client:
                while self.is_running:
                    try:
                        url = f"{self.base_url}/getUpdates?offset={self.offset}&timeout=20"
                        resp = await client.get(url, headers=self.headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            updates = data.get("result", [])
                            for update in updates:
                                self.offset = update["update_id"] + 1

                                # معالجة نقرات الأزرار التفاعلية (Inline Keyboard Buttons)
                                if "callback_query" in update:
                                    await self.handle_callback_query(update["callback_query"])
                                    continue

                                msg = update.get("message", {})
                                chat_id = msg.get("chat", {}).get("id")
                                if not chat_id:
                                    continue

                                # حفظ معرف المحادثة تلقائياً لإرسال التقارير الصباحية المجدولة
                                self._update_org_chat_id(chat_id)

                                if "voice" in msg:
                                    await self.handle_voice(chat_id, msg["voice"])
                                elif "audio" in msg:
                                    await self.handle_voice(chat_id, msg["audio"])
                                elif "photo" in msg:
                                    await self.handle_photo(chat_id, msg["photo"], msg.get("caption"))
                                elif "document" in msg:
                                    await self.handle_document(chat_id, msg["document"], msg.get("caption"))
                                elif "text" in msg:
                                    await self.handle_text(chat_id, msg["text"])
                        elif resp.status_code == 401:
                            print("[TelegramBot] Error: Invalid bot token.")
                            await asyncio.sleep(10)
                        else:
                            await asyncio.sleep(2)
                    except Exception as e:
                        await asyncio.sleep(2)
        finally:
            scheduler_task.cancel()

    def stop(self):
        self.is_running = False

async def main():
    init_db()
    runner = TelegramBotRunner()
    await runner.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
