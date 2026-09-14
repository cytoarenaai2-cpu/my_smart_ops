from enum import Enum
from typing import List, Optional, Dict, Any
import re
from pydantic import BaseModel, Field, model_validator

class DocumentTypeEnum(str, Enum):
    SALES_Z_REPORT = "SALES_Z_REPORT"       # كشف مبيعات كاشير يومي Z-Report
    SALES_RECEIPT = "SALES_RECEIPT"         # فاتورة مبيعات زبون / شيك طاولة مطعم / كاشير POS
    EXPENSE_RECEIPT = "EXPENSE_RECEIPT"     # إيصال مصروف يومي ونثريات
    PURCHASE_INVOICE = "PURCHASE_INVOICE"   # فاتورة شراء وتوريد من مورد
    BANK_STATEMENT = "BANK_STATEMENT"       # كشف بنكي أو إيصال CliQ
    OTHER = "OTHER"

class ExtractedPaymentBreakdown(BaseModel):
    cash: float = Field(0.0, description="المدفوعات النقدية")
    card: float = Field(0.0, description="البطاقات المصرفية POS / Visa / Mastercard")
    cliq: float = Field(0.0, description="المدفوعات عبر نظام CliQ")
    delivery_apps: float = Field(0.0, description="مبيعات شركات التوصيل مثل طلبات وغيرها")
    bank_transfer: float = Field(0.0, description="حوالات بنكية مباشرة")
    other: float = Field(0.0, description="أي وسيلة دفع أخرى")

    @property
    def total_payments(self) -> float:
        return round(self.cash + self.card + self.cliq + self.delivery_apps + self.bank_transfer + self.other, 3)

class ExtractedItem(BaseModel):
    description: str = Field("بند", description="اسم البند أو وصف الخدمة")
    quantity: float = Field(1.0, description="الكمية")
    unit_price: float = Field(0.0, description="سعر الوحدة")
    total_price: float = Field(0.0, description="القيمة الإجمالية للبند")
    tax_rate: Optional[float] = Field(0.16, description="نسبة الضريبة")
    tax_amount: Optional[float] = Field(0.0, description="قيمة الضريبة للبند")

    @model_validator(mode='before')
    @classmethod
    def normalize_item_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # مرونة في أسماء الحقول الشائعة من الذكاء الاصطناعي
            if "total_price" not in data or data["total_price"] is None:
                for alt_key in ["amount", "price", "total", "subtotal", "cost", "value"]:
                    if alt_key in data and data[alt_key] is not None:
                        try:
                            clean_val = str(data[alt_key]).replace(",", "").replace("JOD", "").strip()
                            data["total_price"] = float(clean_val)
                            break
                        except (ValueError, TypeError):
                            pass
            if "description" not in data or not data["description"]:
                for alt_key in ["name", "item", "title", "details"]:
                    if alt_key in data and data[alt_key]:
                        data["description"] = str(data[alt_key])
                        break
        return data

def _clean_number(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace("JOD", "").replace("د.أ", "").replace("دينار", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return default

class ExtractedDocumentData(BaseModel):
    document_type: DocumentTypeEnum = Field(DocumentTypeEnum.OTHER, description="نوع المستند والعملية")
    merchant_or_branch_name: Optional[str] = Field(None, description="اسم المتجر أو فرع المؤسسة/المورد")
    supplier_tax_id: Optional[str] = Field(None, description="الرقم الضريبي أو الرقم الوطني إن وجد")
    invoice_number: Optional[str] = Field(None, description="رقم الفاتورة أو رقم التقرير كود Z")
    date: Optional[str] = Field(None, description="تاريخ الفاتورة بصيغة YYYY-MM-DD")
    
    # Financials
    items: List[ExtractedItem] = Field(default_factory=list, description="تفاصيل البنود")
    subtotal: float = Field(0.0, description="المجموع قبل الضريبة")
    tax_amount: float = Field(0.0, description="إجمالي قيمة الضريبة")
    discount_amount: float = Field(0.0, description="قيمة الخصم إن وجد")
    total_amount: float = Field(0.0, description="المجموع الإجمالي النهائي")
    
    # Payments breakdown
    payment_breakdown: ExtractedPaymentBreakdown = Field(
        default_factory=ExtractedPaymentBreakdown, 
        description="تفصيل وسائل الدفع المقبوضة"
    )
    
    notes: Optional[str] = Field(None, description="ملاحظات إضافية أو أي تحذيرات ظهرت على الفاتورة")
    confidence_score: float = Field(1.0, description="درجة الثقة في الاستخراج من 0 إلى 1")

    @model_validator(mode='before')
    @classmethod
    def sanitize_raw_data(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
            
        # 1. تنظيف نوع المستند
        raw_type = str(data.get("document_type", "")).upper()
        if "SALES_RECEIPT" in raw_type or "RECEIPT_SALE" in raw_type:
            data["document_type"] = DocumentTypeEnum.SALES_RECEIPT
        elif any(w in raw_type for w in ["SALES", "Z_REPORT", "Z REPORT", "CLOSING"]):
            data["document_type"] = DocumentTypeEnum.SALES_Z_REPORT
        elif any(w in raw_type for w in ["PURCHASE", "SUPPLIER"]):
            data["document_type"] = DocumentTypeEnum.PURCHASE_INVOICE
        elif any(w in raw_type for w in ["EXPENSE", "VOUCHER", "COST"]):
            data["document_type"] = DocumentTypeEnum.EXPENSE_RECEIPT
        elif any(w in raw_type for w in ["INVOICE", "BILL"]):
            data["document_type"] = DocumentTypeEnum.PURCHASE_INVOICE
        elif any(w in raw_type for w in ["RECEIPT"]):
            data["document_type"] = DocumentTypeEnum.EXPENSE_RECEIPT
        elif any(w in raw_type for w in ["BANK", "CLIQ", "STATEMENT"]):
            data["document_type"] = DocumentTypeEnum.BANK_STATEMENT
        elif raw_type not in [e.value for e in DocumentTypeEnum]:
            data["document_type"] = DocumentTypeEnum.OTHER

        # 2. تنظيف الأرقام المالية
        for f in ["subtotal", "tax_amount", "discount_amount", "total_amount", "confidence_score"]:
            if f in data:
                data[f] = _clean_number(data[f], 0.0)

        # 3. تنظيف وسائل الدفع
        pb = data.get("payment_breakdown")
        if isinstance(pb, dict):
            for k in ["cash", "card", "cliq", "delivery_apps", "bank_transfer", "other"]:
                if k in pb:
                    pb[k] = _clean_number(pb[k], 0.0)
        elif not pb:
            data["payment_breakdown"] = {}

        # 4. تنظيف قائمة البنود
        raw_items = data.get("items")
        if isinstance(raw_items, list):
            cleaned_items = []
            for item in raw_items:
                if isinstance(item, dict):
                    cleaned_items.append(item)
                elif isinstance(item, str):
                    cleaned_items.append({"description": item, "total_price": 0.0})
            data["items"] = cleaned_items
        else:
            data["items"] = []

        return data

