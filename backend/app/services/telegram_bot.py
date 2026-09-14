import asyncio
from datetime import date
from typing import Optional
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Document, Transaction, AuditFlag
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum
from app.services.ai_parser import AIParserService
from app.services.validator import FinancialValidator
from app.services.daily_summary import DailySummaryService

class TelegramBotRunner:
    """
    مشغل بوت تيليجرام بنظام الاستطلاع الفردي (Single Instance Long Polling).
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        # الاتصال بـ IP تيليجرام الرسمي مباشرة لتفادي حجب الجدران النارية
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
                    # إعادة المحاولة كنص عادي إذا فشل الماركداون
                    payload.pop("parse_mode", None)
                    await client.post(url, json=payload, headers=self.headers)
            except Exception as e:
                print(f"[TelegramBot] send_message error: {e}")

    async def handle_photo(self, chat_id: int, photo_list: list, caption: Optional[str] = None):
        best_photo = photo_list[-1]
        file_id = best_photo.get("file_id")

        await self.send_message(
            chat_id, 
            "⏳ *تم استلام الصورة بنجاح!*\nجاري قراءة وتفريغ الفاتورة بنموذج Gemini Vision وتدقيق الحسابات..."
        )

        async with httpx.AsyncClient(timeout=35.0, verify=False) as client:
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

        extracted_data = await AIParserService.parse_document(
            image_bytes=image_bytes,
            text_content=caption,
            mime_type="image/jpeg"
        )

        await self._process_and_save_data(chat_id, extracted_data)

    async def handle_text(self, chat_id: int, text: str):
        text_clean = text.strip()

        if text_clean in ["/start", "ابدأ"]:
            msg = (
                "👋 *أهلاً بك في المساعد المالي والتنفيذي والضريبي الذكي!*\n\n"
                "هذا البوت مرتبط مباشرة بلوحة التحكم والمحرك الضريبي الأردني (JoFotara):\n\n"
                "📸 *لتسجيل فواتير ومبيعات:*\n"
                "صوّر بكاميرا هاتفك إغلاق الكاشير (Z-Report) أو أي فاتورة شراء أو إيصال مصروف وأرسلها هنا فوراً.\n\n"
                "✍️ *للتسجيل السريع بالكتابة:*\n"
                "اكتب مثلاً: _'مبيعات فرع خلدا اليوم كاش 520 وبطاقات 400 وكليك 150'_\n\n"
                "📊 *لطلب تقرير فوري:*\n"
                "أرسل كلمة *تقرير* أو أمر /brief للحصول على الملخص التنفيذي لحظياً."
            )
            await self.send_message(chat_id, msg)
            return

        if text_clean in ["/brief", "/report", "تقرير", "ملخص"]:
            db = SessionLocal()
            try:
                org = db.query(Organization).first()
                if org:
                    brief = DailySummaryService.generate_morning_brief(db, org.id, date.today())
                    await self.send_message(chat_id, brief["whatsapp_formatted_text"])
                else:
                    await self.send_message(chat_id, "⚠️ لم يتم العثور على منشأة مسجلة بعد.")
            finally:
                db.close()
            return

        # تحليل النص واستخراج البيانات الحسابية
        await self.send_message(chat_id, "⏳ جاري تحليل النص بالذكاء الاصطناعي وتدقيق الحسابات...")
        extracted_data = await AIParserService.parse_document(text_content=text_clean)
        await self._process_and_save_data(chat_id, extracted_data)

    async def _process_and_save_data(self, chat_id: int, extracted_data: ExtractedDocumentData):
        validation = FinancialValidator.validate(extracted_data)
        
        db: Session = SessionLocal()
        try:
            org = db.query(Organization).first()
            if not org:
                org = Organization(name="سلسلة مطاعم الأفق", currency="JOD")
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

            tx_type = "SALE" if extracted_data.document_type == DocumentTypeEnum.SALES_Z_REPORT else "EXPENSE"
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
                "SALES_Z_REPORT": "كشف إغلاق كاشير (مبيعات)",
                "EXPENSE_RECEIPT": "إيصال مصروف يومي",
                "PURCHASE_INVOICE": "فاتورة مشتريات مورد",
                "BANK_STATEMENT": "كشف بنكي / CliQ"
            }
            doc_type_arabic = type_labels.get(extracted_data.document_type.value, extracted_data.document_type.value)

            lines = [
                f"{status_icon} *تم تدقيق وتفريغ العملية بنجاح!*",
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
            lines.append("🖥️ _تم تحديث لوحة التحكم المباشرة فورياً!_")

            formatted_reply = "\n".join(lines)
            await self.send_message(chat_id, formatted_reply)

        finally:
            db.close()

    async def start_polling(self):
        if not self.token:
            print("[TelegramBot] Error: TELEGRAM_BOT_TOKEN is not set.")
            return

        print("[TelegramBot] Connected to Telegram. Single Polling active...")
        self.is_running = True

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

                            if "photo" in msg:
                                await self.handle_photo(chat_id, msg["photo"], msg.get("caption"))
                            elif "text" in msg:
                                await self.handle_text(chat_id, msg["text"])
                    elif resp.status_code == 401:
                        print("[TelegramBot] Error: Invalid bot token.")
                        await asyncio.sleep(10)
                    else:
                        await asyncio.sleep(2)
                except Exception as e:
                    await asyncio.sleep(2)

    def stop(self):
        self.is_running = False

async def main():
    init_db()
    runner = TelegramBotRunner()
    await runner.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
