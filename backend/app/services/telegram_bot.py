import asyncio
from datetime import date, datetime
from typing import Optional, Dict, Any
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

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://149.154.166.110/bot{self.token}"
        self.file_base_url = f"https://149.154.166.110/file/bot{self.token}"
        self.headers = {"Host": "api.telegram.org"}
        self.offset = 0
        self.is_running = False

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown"):
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            try:
                res = await client.post(url, json=payload, headers=self.headers)
                if res.status_code != 200:
                    payload.pop("parse_mode", None)
                    await client.post(url, json=payload, headers=self.headers)
            except Exception as e:
                print(f"[TelegramBot] send_message error: {e}")

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

    async def handle_text(self, chat_id: int, text: str):
        text_clean = text.strip()

        if text_clean in ["/start", "ابدأ"]:
            msg = (
                "👋 *أهلاً بك في المساعد المالي والتنفيذي والضريبي الذكي!*\n\n"
                "هذا البوت مرتبط مباشرة بلوحة التحكم والمحرك الضريبي الأردني (JoFotara):\n\n"
                "📄 *لمعالجة ملفات PDF مجمعة:*\n"
                "أرسل ملف PDF يحتوي على صفحات وفواتير متعددة وسيقوم النظام بتفكيكها واستخراج كل فاتورة على حدى وإعطائك تقريراً إحصائياً شاملاً!\n\n"
                "📸 *لتسجيل فواتير ومبيعات بالصور:*\n"
                "صوّر بكاميرا هاتفك إغلاق الكاشير (Z-Report) أو أي فاتورة شراء أو إيصال مصروف وأرسلها هنا فوراً.\n\n"
                "🎙️ *لتسجيل فويس نوت صوتي:*\n"
                "سجل رسالة صوتية سريعة بصوتك (مثلاً: _'مبيعات فرع خلدا اليوم 520 كاش و400 فيزا ودفعنا للموزع 80'_) وسيقوم الذكاء الاصطناعي بتفريغها وتدقيقها فورياً!\n\n"
                "✍️ *للتسجيل السريع بالكتابة:*\n"
                "اكتب نصاً مثل: _'مبيعات فرع خلدا اليوم كاش 520 وبطاقات 400 وكليك 150'_\n\n"
                "📊 *لطلب تقرير فوري:*\n"
                "أرسل كلمة *تقرير* أو أمر /brief للحصول على الملخص التنفيذي الحقيقي للعمليات."
            )
            await self.send_message(chat_id, msg)
            return

        if text_clean in ["/brief", "/report", "تقرير", "ملخص"]:
            db = SessionLocal()
            try:
                org = db.query(Organization).first()
                if org:
                    tx_count = db.query(Transaction).filter(Transaction.organization_id == org.id).count()
                    if tx_count == 0:
                        await self.send_message(
                            chat_id, 
                            "📊 *لا توجد أي عمليات مسجلة حتى الآن.*\nسجل أول عملية لديك بكتابتها أو تصوير فاتورة وسيتم تحديث التقرير فوراً!"
                        )
                        return

                    brief = DailySummaryService.generate_morning_brief(db, org.id, date.today())
                    await self.send_message(chat_id, brief["whatsapp_formatted_text"])
                else:
                    await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة بعد.")
            finally:
                db.close()
            return

        # تحليل النص واستخراج البيانات الحسابية
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
