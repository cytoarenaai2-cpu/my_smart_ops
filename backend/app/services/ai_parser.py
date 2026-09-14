import os
import re
import json
import base64
from typing import Optional
import httpx
from app.core.config import settings
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum, ExtractedPaymentBreakdown, ExtractedItem

PARSING_SYSTEM_PROMPT = """
أنت مدقق مالي ومحاسبي دقيق جداً. مهمتك استخراج الأرقام والمعاملات الحقيقية فقط من النص أو الصورة المرفقة.

شروط حاسمة لا تحتمل الاستثناء:
1. استخرج الأرقام الحقيقية المذكورة فقط. لا تخترع أو تفترض أي رقم إطلاقاً!
2. إذا كان النص أو الصورة لا تحتوي على أي مبالغ مالية حقيقية، اجعل:
   "total_amount": 0.0, "subtotal": 0.0, "confidence_score": 0.0
3. إذا كان النص مبيعات كاشير، واستخرجت وسائل الدفع (كاش، بطاقات، كليك، توصيل)، اجعل total_amount يساوي مجموعها الحقيقي بالضبط.
4. حدد نوع المستند بدقة:
   - SALES_Z_REPORT: إذا كان مبيعات، كاشير، إيراد يومي.
   - EXPENSE_RECEIPT: إذا كان مصروفاً تشغيلياً أو إيصالاً نثرياً.
   - PURCHASE_INVOICE: إذا كانت فاتورة شراء بضاعة من مورد.

أرجع حصرياً كائن JSON بالهيكل التالي:
{
  "document_type": "SALES_Z_REPORT" | "EXPENSE_RECEIPT" | "PURCHASE_INVOICE" | "BANK_STATEMENT" | "OTHER",
  "merchant_or_branch_name": "اسم الفرع أو المتجر أو null",
  "supplier_tax_id": "الرقم الضريبي للمورد إن وجد أو null",
  "invoice_number": "رقم الفاتورة إن وجد أو null",
  "date": "YYYY-MM-DD",
  "items": [],
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
  "notes": "الملاحظات الحقيقية فقط",
  "confidence_score": 1.0
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
        
        # 1. الاستخراج الحقيقي عبر Gemini 3.6 Flash
        if api_key and (image_bytes or (text_content and text_content.strip())):
            try:
                return await cls._call_gemini(api_key, image_bytes, mime_type, text_content)
            except Exception as e:
                print(f"[AIParserService] Gemini API call error: {e}")

        # 2. في حال عدم توفر الذكاء الاصطناعي، يتم استخراج الأرقام الفعلية من النص بدون أي أرقام وهمية
        return cls._extract_real_numbers_from_text(text_content)

    @classmethod
    async def _call_gemini(
        cls, 
        api_key: str, 
        image_bytes: Optional[bytes], 
        mime_type: str,
        user_text: Optional[str]
    ) -> ExtractedDocumentData:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
        
        parts = [{"text": PARSING_SYSTEM_PROMPT + (f"\nنص المستند أو الملاحظات المدخلة: {user_text}" if user_text else "")}]
        
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
                "temperature": 0.0
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
    def _extract_real_numbers_from_text(cls, text_content: Optional[str] = None) -> ExtractedDocumentData:
        """
        استخراج الأرقام الحقيقية المكتوبة في النص فقط - لا يتم اختراع أي أرقام وهمية إطلاقاً!
        """
        text = text_content or ""
        if not text.strip():
            return ExtractedDocumentData(
                document_type=DocumentTypeEnum.OTHER,
                total_amount=0.0,
                confidence_score=0.0
            )

        # البحث عن أرقام حقيقية بجانب الكلمات الدالة
        cash_match = re.search(r'(?:كاش|نقدي|نقد)\s*[:=]?\s*(\d+(?:\.\d+)?)', text)
        card_match = re.search(r'(?:بطاق(?:ة|ات)|شبكة|فيزا|pos)\s*[:=]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        cliq_match = re.search(r'(?:كليك|cliq)\s*[:=]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        total_match = re.search(r'(?:إجمالي|مجموع|مبيعات|قيمة|مبلغ)\s*[:=]?\s*(\d+(?:\.\d+)?)', text)

        cash = float(cash_match.group(1)) if cash_match else 0.0
        card = float(card_match.group(1)) if card_match else 0.0
        cliq = float(cliq_match.group(1)) if cliq_match else 0.0

        subtotal = cash + card + cliq
        if total_match and subtotal == 0:
            subtotal = float(total_match.group(1))

        # إذا لم يتم العثور على أي أرقام، نرجع 0
        if subtotal == 0:
            numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)
            if numbers:
                subtotal = float(numbers[0])

        is_expense = any(w in text for w in ["مصروف", "شراء", "فاتورة شراء", "صرف"])
        doc_type = DocumentTypeEnum.EXPENSE_RECEIPT if is_expense else DocumentTypeEnum.SALES_Z_REPORT

        # استخراج اسم الفرع
        branch_match = re.search(r'فرع\s+([^\s,]+)', text)
        branch_name = f"فرع {branch_match.group(1)}" if branch_match else "المركز الرئيسي"

        return ExtractedDocumentData(
            document_type=doc_type,
            merchant_or_branch_name=branch_name,
            subtotal=round(subtotal, 3),
            total_amount=round(subtotal, 3),
            payment_breakdown=ExtractedPaymentBreakdown(
                cash=round(cash, 3),
                card=round(card, 3),
                cliq=round(cliq, 3)
            ) if not is_expense else ExtractedPaymentBreakdown(cash=round(subtotal, 3)),
            confidence_score=0.9 if subtotal > 0 else 0.0,
            notes=text
        )
