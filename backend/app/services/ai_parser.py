import os
import re
import json
import base64
from typing import Optional, List, Dict, Any
import httpx
from app.core.config import settings
from app.models.extraction_schemas import ExtractedDocumentData, DocumentTypeEnum, ExtractedPaymentBreakdown, ExtractedItem

PARSING_SYSTEM_PROMPT = """
أنت مدقق مالي ومحاسبي ذكي وخبير متخصص في محاسبة المطاعم والتجزئة والأنظمة الضريبية في الأردن والشرق الأوسط.
مهمتك استخراج وتصنيف المعاملات المالية الحقيقية بدقة متناهية.

قواعد التمييز الجوهري بين المبيعات (SALES) ومشتريات الموردين (PURCHASES) والمصروفات (EXPENSES):

1. فواتير مبيعات الزبائن والكاشير (SALES_RECEIPT أو SALES_Z_REPORT) ⬅️ [مبيعات / إيراد صندوق]:
   - العلامات الدالة:
     * شيكات حساب طاولات المطاعم والمقاهي (Guest Check / Table Check / Dine-In / Takeaway / شيك طاولة رقم X).
     * فواتير نقاط البيع (POS) المطبوعة على ورق حراري ضيق ومروسة باسم المطعم أو الفرع.
     * أصناف جاهزة للأكل والشرب الفردي بأسعار البيع للزبائن (وجبات، برغر، بيتزا، حلويات، قهوة، عصائر).
     * كشوفات إغلاق الكاشير اليومية (Z-Report / X-Report / Daily Sales Summary).
     * تفاصيل التحصيل: كاش، شبكة/فيزا، كليك، الباقي للزبون، أو عبارات شكر للعملاء.

2. فواتير مشتريات وتوريد البضاعة من الموزعين (PURCHASE_INVOICE) ⬅️ [مشتريات موردين / تكلفة بضاعة]:
   - العلامات الدالة:
     * الترويسة العليا باسم شركة توزيع، مصنع، مستودع، أو مورد تجاري (مثل: شركة توزيع ألبان ولحوم، تجارة خضار وفواكه جملة، مواد تغليف وكراتين، توريد زيوت ومواد غذائية خام).
     * العميل الموجه إليه الفاتورة (Billed To / السادة) هو المطعم أو الفرع.
     * الأصناف عبارة عن مواد خام ومواد أولية بكميات جملة أو أوزان تجارية (كراتين، شوالات، صناديق، أطنان، كيلوغرامات بالجملة مثل: "شوال أرز 25كغ", "كرتون دجاج مبرد", "صندوق زيت 16 لتر").
     * مستندات توريد B2B: "فاتورة ضريبية رسمية للمورد"، "إشعار تسليم/بوليصة شحن Delivery Note"، "أمر شراء PO"، دفع آجل/شيكات.

3. إيصالات المصروفات التشغيلية والنثريات (EXPENSE_RECEIPT) ⬅️ [مصروفات تشغيلية]:
   - فواتير الخدمات العامة (كهرباء، مياه، غاز مركزي، إنترنت)، إيصالات محطات وقود وصيانة، مستلزمات نظافة، سندات صرف داخلي للمصاريف النثرية.

قواعد أساسية لا استثناء فيها:
1. استخرج الأرقام الحقيقية المكتوبة في المستند فقط (المبلغ الإجمالي total_amount، المجموع قبل الضريبة subtotal، قيمة الضريبة tax_amount).
2. إذا كان المستند مبيعات كاشير أو فاتورة طاولة زبون، استخرج تفاصيل الدفع المقبوضة (كاش، بطاقات POS، كليك CliQ، تطبيقات توصيل).
3. إذا كان المستند إيصال مصروف أو فاتورة مشتريات نقدية، ضع قيمة المبلغ الإجمالي في خانة cash ضمن payment_breakdown.
4. استخرج اسم الفرع أو المتجر أو المورد في merchant_or_branch_name، والرقم الضريبي في supplier_tax_id، ورقم الفاتورة في invoice_number.

أرجع حصرياً كائن JSON بالهيكل التالي:
{
  "document_type": "SALES_Z_REPORT" | "SALES_RECEIPT" | "EXPENSE_RECEIPT" | "PURCHASE_INVOICE" | "BANK_STATEMENT" | "OTHER",
  "merchant_or_branch_name": "اسم الفرع أو المتجر أو المورد أو null",
  "supplier_tax_id": "الرقم الضريبي للمورد إن وجد أو null",
  "invoice_number": "رقم الفاتورة إن وجد أو null",
  "date": "YYYY-MM-DD",
  "items": [
    {"description": "اسم الصنف", "quantity": 1.0, "unit_price": 0.0, "total_price": 0.0, "tax_rate": 0.16, "tax_amount": 0.0}
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
  "notes": "أي ملاحظات مدونة على الفاتورة",
  "confidence_score": 1.0
}
"""

class AIParserService:
    FALLBACK_MODELS = [
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite"
    ]

    @classmethod
    async def parse_document(
        cls, 
        image_bytes: Optional[bytes] = None, 
        text_content: Optional[str] = None,
        mime_type: str = "image/jpeg",
        business_context: Optional[Dict[str, Any]] = None
    ) -> ExtractedDocumentData:
        api_key = settings.GEMINI_API_KEY
        
        # 1. الاستخراج الحقيقي عبر نماذج الذكاء الاصطناعي مع التبديل التلقائي عند أي ضغط
        if api_key and (image_bytes or (text_content and text_content.strip())):
            for model_name in cls.FALLBACK_MODELS:
                try:
                    result = await cls._call_gemini(
                        api_key, 
                        image_bytes, 
                        mime_type, 
                        text_content, 
                        model_name=model_name,
                        business_context=business_context
                    )
                    print(f"[AIParserService] Successfully extracted via model: {model_name} (total: {result.total_amount})", flush=True)
                    return result
                except Exception as e:
                    print(f"[AIParserService] Model {model_name} attempt failed: {e}", flush=True)
                    continue

        # 2. في حال إدخال نصي ولم يتوفر الذكاء الاصطناعي، يتم استخراج الأرقام الحقيقية المكتوبة في النص
        if text_content and text_content.strip():
            return cls._extract_real_numbers_from_text(text_content)

        # 3. إذا كان مستند صورة وفشلت النماذج مؤقتاً بسبب انقطاع الشبكة
        if image_bytes:
            return ExtractedDocumentData(
                document_type=DocumentTypeEnum.OTHER,
                total_amount=0.0,
                confidence_score=0.0,
                notes="API_TEMPORARY_ERROR"
            )

        return cls._extract_real_numbers_from_text(text_content)

    @classmethod
    async def _call_gemini(
        cls, 
        api_key: str, 
        image_bytes: Optional[bytes], 
        mime_type: str,
        user_text: Optional[str],
        model_name: str = "gemini-3.5-flash",
        business_context: Optional[Dict[str, Any]] = None
    ) -> ExtractedDocumentData:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        system_text = PARSING_SYSTEM_PROMPT
        if business_context and business_context.get("business_name"):
            b_name = business_context.get("business_name", "")
            b_type = business_context.get("industry_type", "عام")
            b_tax = business_context.get("tax_number") or "غير محدد"
            b_branches = business_context.get("branches") or []
            branches_str = "، ".join(b_branches) if b_branches else "الفرع الرئيسي"

            system_text += f"""

============================================================
سياق وهوية النشاط التجاري صاحب هذا النظام (حاسم جداً في التمييز والتصنيف):
- اسم النشاط التجاري / المنشأة: {b_name}
- طبيعة النشاط التجاري: {b_type}
- الفروع التابعة للنشاط: {branches_str}
- الرقم الضريبي للمنشأة: {b_tax}

قواعد التمييز القطعية بناءً على هوية النشاط التجاري أعلاه:
1. المبيعات (SALES_RECEIPT أو SALES_Z_REPORT):
   - إذا كانت الفاتورة أو الإيصال صادراً باسم المنشأة ({b_name}) أو أحد فروعها في الترويسة كبائع، أو شيك طاولة/كاشير زبائن للنشاط ({b_type}) ⬅️ اعتبرها حتماً مبيعات زبائن (SALES_RECEIPT أو SALES_Z_REPORT).
   - إذا طابق اسم الفرع في الفاتورة أحد الفروع ({branches_str})، ضعه في merchant_or_branch_name.
2. مشتريات وتوريدات الموردين (PURCHASE_INVOICE أو EXPENSE_RECEIPT):
   - إذا كانت الفاتورة صادرة من اسم تجاري آخر (موزع، مورد، مصنع، مستودع، تاجر جملة) وكانت منشأتك ({b_name}) هي المشتري أو المستلم، أو كانت تحتوي على مواد خام وتوريدات جملة ⬅️ اعتبرها حتماً مشتريات مورد (PURCHASE_INVOICE).
============================================================
"""

        if mime_type and mime_type.startswith("audio/"):
            system_text += """
============================================================
تنبيه خاص بالرسائل والتسجيلات الصوتية (Voice Note Audio Ingestion):
المستند المرفق هو تسجيل صوتي محكي باللغة العربية (باللهجة الأردنية أو الشامية أو العربية الفصحى) مرسل من صاحب المنشأة أو موظف الكاشير أو المسؤول المالي.
- استمع بدقة فائقة للأرقام والمبالغ المذكورة منطوقة بالصوت (مثلاً: خمسمية وعشرين دينار، أربعمية فيزا، ثمانين للموزع، مية وخمسين كليك، إلخ).
- استخرج مبالغ المبيعات أو المصروفات ووزعها في payment_breakdown (كاش، بطاقة، كليك، توصيل).
- إذا ذكر المتحدث اسم فرع (مثلاً: فرع خلدا، فرع عبدون)، ضعه في merchant_or_branch_name.
- حدد ما إذا كان يتحدث عن مبيعات يومية (SALES_RECEIPT أو SALES_Z_REPORT) أو دفعات لموردين ومصاريف (EXPENSE_RECEIPT أو PURCHASE_INVOICE).
============================================================
"""

        parts = [{"text": system_text + (f"\nنص المستند أو الملاحظات المدخلة: {user_text}" if user_text else "")}]
        
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

        async with httpx.AsyncClient(timeout=40.0, verify=False) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_json = response.json()
            
            # استخراج النص بمرونة من أي جزء يحتوي على نص
            candidate = res_json.get("candidates", [{}])[0]
            candidate_parts = candidate.get("content", {}).get("parts", [])
            raw_text = ""
            for p in candidate_parts:
                if "text" in p:
                    raw_text += p["text"]

            if not raw_text.strip():
                raise ValueError("Empty response text from Gemini API")

            # استخراج محتوى JSON الصافي حتى لو وجد markdown أو نصوص محيطة
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                parsed_dict = json.loads(json_match.group(0))
            else:
                parsed_dict = json.loads(raw_text)

            return ExtractedDocumentData(**parsed_dict)

    @classmethod
    async def parse_pdf_page(
        cls,
        pdf_page_bytes: bytes,
        page_number: int = 1,
        business_context: Optional[Dict[str, Any]] = None
    ) -> List[ExtractedDocumentData]:
        """
        استخراج الفواتير من صفحة PDF أحادية.
        تدعم وجود فاتورة واحدة، أو عدة فواتير في الصفحة الواحدة، أو صفحة بدون فواتير.
        """
        api_key = settings.GEMINI_API_KEY
        if not api_key or not pdf_page_bytes:
            return []

        for model_name in cls.FALLBACK_MODELS:
            try:
                results = await cls._call_gemini_pdf_page(
                    api_key=api_key,
                    pdf_bytes=pdf_page_bytes,
                    page_number=page_number,
                    model_name=model_name,
                    business_context=business_context
                )
                print(f"[AIParserService] Page {page_number}: successfully extracted {len(results)} invoice(s) via {model_name}", flush=True)
                return results
            except Exception as e:
                print(f"[AIParserService] Page {page_number}: model {model_name} attempt failed: {e}", flush=True)
                continue

        return []

    @classmethod
    async def _call_gemini_pdf_page(
        cls,
        api_key: str,
        pdf_bytes: bytes,
        page_number: int,
        model_name: str = "gemini-3.5-flash",
        business_context: Optional[Dict[str, Any]] = None
    ) -> List[ExtractedDocumentData]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

        system_text = PARSING_SYSTEM_PROMPT
        if business_context and business_context.get("business_name"):
            b_name = business_context.get("business_name", "")
            b_type = business_context.get("industry_type", "عام")
            b_tax = business_context.get("tax_number") or "غير محدد"
            b_branches = business_context.get("branches") or []
            branches_str = "، ".join(b_branches) if b_branches else "الفرع الرئيسي"

            system_text += f"""

============================================================
سياق وهوية النشاط التجاري صاحب هذا النظام (حاسم جداً في التمييز والتصنيف):
- اسم النشاط التجاري / المنشأة: {b_name}
- طبيعة النشاط التجاري: {b_type}
- الفروع التابعة للنشاط: {branches_str}
- الرقم الضريبي للمنشأة: {b_tax}

قواعد التمييز القطعية:
1. المبيعات (SALES_RECEIPT أو SALES_Z_REPORT):
   إذا كانت الفاتورة صادرة باسم المنشأة ({b_name}) أو أحد فروعها ({branches_str}) أو كاشير زبائن للنشاط ⬅️ مبيعات.
2. مشتريات وتوريدات الموردين (PURCHASE_INVOICE أو EXPENSE_RECEIPT):
   إذا كانت صادرة من مورد أو شركة توزيع أخرى ومنشأتك هي المشتري ⬅️ مشتريات موردين.
============================================================
"""

        system_text += f"""
============================================================
تنبيه خاص باستخراج الفواتير من صفحة PDF (صفحة رقم {page_number}):
أمامك صفحة مستند قد تحتوي على:
1. فاتورة واحدة مستقلة.
2. أكثر من فاتورة أو إيصال مستقل (مثلاً إيصالين أو أكثر ممسوحة ضوئياً على ورقة A4 واحدة).
3. لا تحتوي على أي فواتير (مثلاً صفحة غلاف، صفحة بيضاء، أو نصوص عامة لا علاقة لها بالمعاملات المالية).

المطلوب بدقة:
استخراج كل فاتورة مستقلة موجودة في الصفحة، وإرجاعها كعنصر داخل مصفوفة في كائن JSON باسم "invoices":
{{
  "invoices": [
    {{
      "document_type": "SALES_RECEIPT" | "SALES_Z_REPORT" | "PURCHASE_INVOICE" | "EXPENSE_RECEIPT" | "OTHER",
      "merchant_or_branch_name": "اسم الفرع أو المتجر أو المورد",
      "supplier_tax_id": "الرقم الضريبي للمورد إن وجد أو null",
      "invoice_number": "رقم الفاتورة إن وجد أو null",
      "date": "YYYY-MM-DD",
      "items": [
        {{"description": "اسم الصنف", "quantity": 1.0, "unit_price": 0.0, "total_price": 0.0, "tax_rate": 0.16, "tax_amount": 0.0}}
      ],
      "subtotal": 0.0,
      "tax_amount": 0.0,
      "discount_amount": 0.0,
      "total_amount": 0.0,
      "payment_breakdown": {{
        "cash": 0.0,
        "card": 0.0,
        "cliq": 0.0,
        "delivery_apps": 0.0,
        "bank_transfer": 0.0,
        "other": 0.0
      }},
      "notes": "صفحة {page_number}"
    }}
  ]
}}
إذا لم تكن الصفحة تحتوي على أي فاتورة، أرجع حصراً: {{"invoices": []}}
============================================================
"""

        base64_data = base64.b64encode(pdf_bytes).decode("utf-8")
        parts = [
            {"text": system_text},
            {
                "inline_data": {
                    "mime_type": "application/pdf",
                    "data": base64_data
                }
            }
        ]

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        }

        async with httpx.AsyncClient(timeout=50.0, verify=False) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_json = response.json()

            candidate = res_json.get("candidates", [{}])[0]
            candidate_parts = candidate.get("content", {}).get("parts", [])
            raw_text = ""
            for p in candidate_parts:
                if "text" in p:
                    raw_text += p["text"]

            if not raw_text.strip():
                return []

            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                parsed_data = json.loads(json_match.group(0))
            else:
                parsed_data = json.loads(raw_text)

            extracted_list: List[ExtractedDocumentData] = []

            # 1. إذا كان التنسيق المطلوب {"invoices": [...]}
            if isinstance(parsed_data, dict) and "invoices" in parsed_data:
                inv_list = parsed_data["invoices"]
                if isinstance(inv_list, list):
                    for item in inv_list:
                        if isinstance(item, dict):
                            try:
                                extracted_list.append(ExtractedDocumentData(**item))
                            except Exception as parse_err:
                                print(f"[AIParserService] Error parsing invoice item: {parse_err}")

            # 2. إذا أعاد النموذج كائن فاتورة فردي مباشرة بدلاً من مصفوفة
            elif isinstance(parsed_data, dict) and ("total_amount" in parsed_data or "document_type" in parsed_data):
                try:
                    extracted_list.append(ExtractedDocumentData(**parsed_data))
                except Exception as parse_err:
                    print(f"[AIParserService] Error parsing single invoice dict: {parse_err}")

            # 3. إذا أعاد مصفوفة فواتير مباشرة
            elif isinstance(parsed_data, list):
                for item in parsed_data:
                    if isinstance(item, dict):
                        try:
                            extracted_list.append(ExtractedDocumentData(**item))
                        except Exception as parse_err:
                            print(f"[AIParserService] Error parsing invoice list element: {parse_err}")

            return extracted_list

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
