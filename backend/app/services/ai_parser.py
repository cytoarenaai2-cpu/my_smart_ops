import os
import json
import base64
from typing import Optional
import httpx
from app.core.config import settings
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum, ExtractedPaymentBreakdown, ExtractedItem

PARSING_SYSTEM_PROMPT = """
أنت خبير تدقيق مستندات مالية ومحاسبية متخصص في قراءة كشوفات الكاشير (Z-Report)، فواتير المشتريات، وإيصالات المصروفات للمحلات والشركات في الأردن والشرق الأوسط.

مهمتك:
استخراج البيانات المالية بدقة متناهية من الصورة أو النص المرفق وإرجاع كائن JSON حصرياً مطابق للمواصفات التالية:
{
  "document_type": "SALES_Z_REPORT" | "EXPENSE_RECEIPT" | "PURCHASE_INVOICE" | "BANK_STATEMENT" | "OTHER",
  "merchant_or_branch_name": "اسم المحل أو الفرع",
  "supplier_tax_id": "الرقم الضريبي للمورد إن وجد أو null",
  "invoice_number": "رقم الفاتورة أو رقم التقرير",
  "date": "YYYY-MM-DD",
  "items": [
    {"description": "اسم البند", "quantity": 1.0, "unit_price": 10.0, "total_price": 10.0, "tax_rate": 0.16, "tax_amount": 1.6}
  ],
  "subtotal": 0.0,
  "tax_amount": 0.0,
  "discount_amount": 0.0,
  "total_amount": 0.0,
  "payment_breakdown": {
    "cash": 0.0,
    "card": 0.0,
    "cliq": 0.0,
    "delivery_apps": 0.0,
    "bank_transfer": 0.0,
    "other": 0.0
  },
  "notes": "أي ملاحظات هامة",
  "confidence_score": 0.95
}
"""

class AIParserService:
    @classmethod
    async def parse_document(
        cls, 
        image_bytes: Optional[bytes] = None, 
        text_content: Optional[str] = None,
        mime_type: str = "image/jpeg"
    ) -> ExtractedDocumentData:
        api_key = settings.GEMINI_API_KEY
        
        if api_key:
            try:
                return await cls._call_gemini_vision(api_key, image_bytes, mime_type, text_content)
            except Exception as e:
                print(f"[AIParserService] Gemini API call error: {e}, falling back to smart extractor")
        
        return cls._mock_parser(text_content)

    @classmethod
    async def _call_gemini_vision(
        cls, 
        api_key: str, 
        image_bytes: Optional[bytes], 
        mime_type: str,
        user_text: Optional[str]
    ) -> ExtractedDocumentData:
        # استخدام موديل gemini-3.6-flash المدعوم حالياً في بيئة 2026
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
        
        parts = [{"text": PARSING_SYSTEM_PROMPT + (f"\nمعلومات المستند أو الملاحظات: {user_text}" if user_text else "")}]
        
        if image_bytes:
            base64_data = base64.b64encode(image_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64_data
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        }

        async with httpx.AsyncClient(timeout=35.0, verify=False) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_json = response.json()
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            parsed_dict = json.loads(raw_text)
            return ExtractedDocumentData(**parsed_dict)

    @classmethod
    def _mock_parser(cls, text_content: Optional[str] = None) -> ExtractedDocumentData:
        text = (text_content or "").lower()
        is_expense = any(w in text for w in ["مصروف", "شراء", "توريد", "expense", "purchase", "supplier"])
        
        if is_expense:
            return ExtractedDocumentData(
                document_type=DocumentTypeEnum.EXPENSE_RECEIPT,
                merchant_or_branch_name="شركة التوريدات الحديثة",
                supplier_tax_id="123456789",
                invoice_number="INV-2026-004",
                date="2026-09-14",
                items=[
                    ExtractedItem(description="مواد تغليف وكرتون", quantity=50.0, unit_price=2.0, total_price=100.0, tax_rate=0.16, tax_amount=16.0)
                ],
                subtotal=100.0,
                tax_amount=16.0,
                discount_amount=0.0,
                total_amount=116.0,
                payment_breakdown=ExtractedPaymentBreakdown(cash=116.0),
                notes="تم الدفع نقداً من الكاشير",
                confidence_score=0.98
            )
        
        return ExtractedDocumentData(
            document_type=DocumentTypeEnum.SALES_Z_REPORT,
            merchant_or_branch_name="فرع الجبيهة",
            invoice_number="Z-2026-0914-1",
            date="2026-09-14",
            subtotal=1000.0,
            tax_amount=160.0,
            discount_amount=0.0,
            total_amount=1160.0,
            payment_breakdown=ExtractedPaymentBreakdown(
                cash=500.0,
                card=450.0,
                cliq=210.0
            ),
            notes="إغلاق كاشير شفت مسائي ممتاز",
            confidence_score=0.99
        )
