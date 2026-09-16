import io
import base64
import datetime
from typing import Dict, Any, Optional, Tuple
import qrcode
from qrcode.constants import ERROR_CORRECT_M


class JoFotaraService:
    """
    محرك الامتثال لنظام الفوترة الإلكترونية الوطني الأردني (JoFotara / ISTD 2025).
    يتولى:
    1. تشفير وفك تشفير حقول الفاتورة بهيكل TLV (Tag-Length-Value) المعتمد رسمياً في الأردن.
    2. توليد صور QR Code بدقة عالية وصيغ Base64 جاهزة للعرض أو الطباعة.
    3. بناء حزم الفواتير الرقمية الرسمية (e-Invoice JSON Payloads) المتوافقة مع مواصفات الربط الإلكتروني لـ JoFotara.
    """

    TAG_NAMES = {
        1: "seller_name",
        2: "tax_id",
        3: "timestamp",
        4: "total_amount",
        5: "tax_amount"
    }

    TAG_ARABIC_LABELS = {
        1: "اسم البائع / المنشأة",
        2: "الرقم الضريبي للمنشأة (TIN)",
        3: "تاريخ ووقت إصدار الفاتورة",
        4: "إجمالي الفاتورة شاملاً الضريبة والخدمة",
        5: "مبلغ ضريبة المبيعات 16%"
    }

    @classmethod
    def encode_tlv(
        cls,
        seller_name: str,
        tax_id: str,
        timestamp: str,
        total_amount: float,
        tax_amount: float
    ) -> str:
        """
        تشفير الحقول الخمسة الإلزامية وفق معيار TLV الأردني:
        Tag 1: Seller's Name
        Tag 2: Seller's Tax ID (الرقم الضريبي)
        Tag 3: Invoice Timestamp (ISO 8601: YYYY-MM-DDTHH:MM:SS)
        Tag 4: Invoice Total (with VAT & Service) - 3 decimal places
        Tag 5: Tax Amount (16%) - 3 decimal places
        
        يرجع نصاً مرمزاً بـ Base64 صالحاً للقراءة المباشرة من قوارئ الفوترة الإلكترونية.
        """
        fields = [
            (1, str(seller_name or "").strip()),
            (2, str(tax_id or "").strip()),
            (3, str(timestamp or "").strip()),
            (4, f"{float(total_amount):.3f}"),
            (5, f"{float(tax_amount):.3f}")
        ]

        tlv_bytes = bytearray()
        for tag, val in fields:
            val_bytes = val.encode("utf-8")
            length = len(val_bytes)
            tlv_bytes.append(tag)
            tlv_bytes.append(length)
            tlv_bytes.extend(val_bytes)

        return base64.b64encode(tlv_bytes).decode("ascii")

    @classmethod
    def decode_tlv(cls, base64_str: str) -> Dict[str, Any]:
        """
        فك تشفير رمز TLV Base64 واستخراج الحقول الخمسة والتحقق من صحتها.
        """
        try:
            raw_bytes = base64.b64decode(base64_str.strip())
        except Exception as e:
            return {
                "valid": False,
                "error": f"فشل فك ترميز Base64: {str(e)}",
                "tags": {}
            }

        tags: Dict[int, str] = {}
        idx = 0
        total_len = len(raw_bytes)

        try:
            while idx < total_len:
                tag = raw_bytes[idx]
                length = raw_bytes[idx + 1]
                val_bytes = raw_bytes[idx + 2 : idx + 2 + length]
                tags[tag] = val_bytes.decode("utf-8", errors="replace")
                idx += 2 + length
        except Exception as e:
            return {
                "valid": False,
                "error": f"خطأ أثناء قراءة حقول TLV: {str(e)}",
                "tags": tags
            }

        decoded_tags = {}
        for tag_num, name in cls.TAG_NAMES.items():
            val = tags.get(tag_num, "")
            decoded_tags[name] = {
                "tag_number": tag_num,
                "label_ar": cls.TAG_ARABIC_LABELS.get(tag_num, ""),
                "value": val
            }

        is_valid = bool(
            tags.get(1) and tags.get(2) and tags.get(3) and (4 in tags) and (5 in tags)
        )

        return {
            "valid": is_valid,
            "raw_tags": tags,
            "decoded": decoded_tags
        }

    @classmethod
    def generate_qr_png_bytes(cls, content: str, box_size: int = 6, border: int = 2) -> bytes:
        """
        توليد صورة QR Code نقية كبايتات PNG بدقة عالية.
        """
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @classmethod
    def generate_qr_data_uri(cls, content: str, box_size: int = 6, border: int = 2) -> str:
        """
        توليد رابط مباشر لعرض صورة الـ QR في المتصفح بصيغة data:image/png;base64,...
        """
        png_bytes = cls.generate_qr_png_bytes(content, box_size=box_size, border=border)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    @classmethod
    def format_timestamp(cls, tx_date: Any, tx_created_at: Any = None) -> str:
        """
        تنسيق التوقيت بالصيغة القياسية ISO 8601 المطلوبة من نظام الفوترة الأردني.
        """
        if isinstance(tx_created_at, datetime.datetime):
            return tx_created_at.strftime("%Y-%m-%dT%H:%M:%S")
        elif isinstance(tx_date, datetime.date):
            return f"{tx_date.strftime('%Y-%m-%d')}T12:00:00"
        elif isinstance(tx_date, str):
            if "T" in tx_date:
                return tx_date[:19]
            return f"{tx_date}T12:00:00"
        return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    @classmethod
    def build_transaction_qr(cls, transaction: Any, org: Any) -> Dict[str, Any]:
        """
        بناء رمز الـ QR وتشفير TLV لفاتورة أو عملية مسجلة.
        """
        seller_name = getattr(org, "name", "المنشأة التجارية")
        tax_id = getattr(org, "tax_number", None) or "000000000"
        timestamp = cls.format_timestamp(
            getattr(transaction, "transaction_date", None),
            getattr(transaction, "created_at", None)
        )
        total_amount = float(getattr(transaction, "total_amount", 0.0) or 0.0)
        tax_amount = float(getattr(transaction, "tax_amount", 0.0) or 0.0)

        tlv_b64 = cls.encode_tlv(
            seller_name=seller_name,
            tax_id=tax_id,
            timestamp=timestamp,
            total_amount=total_amount,
            tax_amount=tax_amount
        )

        qr_data_uri = cls.generate_qr_data_uri(tlv_b64, box_size=6, border=2)
        decoded = cls.decode_tlv(tlv_b64)

        return {
            "transaction_id": str(getattr(transaction, "id", "")),
            "seller_name": seller_name,
            "tax_id": tax_id,
            "timestamp": timestamp,
            "total_amount": total_amount,
            "tax_amount": tax_amount,
            "tlv_base64": tlv_b64,
            "qr_data_uri": qr_data_uri,
            "decoded_info": decoded.get("decoded", {}),
            "is_compliant": bool(getattr(org, "tax_number", None) and total_amount > 0)
        }

    @classmethod
    def generate_einvoice_payload(cls, transaction: Any, org: Any, branch: Any = None) -> Dict[str, Any]:
        """
        صياغة حزمة الفاتورة الإلكترونية الكاملة (JoFotara e-Invoice API Payload)
        مطابقة لمواصفات التكامل والربط مع دائرة ضريبة الدخل والمبيعات الأردنية (ISTD).
        """
        qr_info = cls.build_transaction_qr(transaction, org)
        
        tx_type = getattr(transaction, "transaction_type", "SALE")
        is_sale = tx_type == "SALE"
        
        # 388: Commercial Tax Invoice, 381: Credit Note, 383: Debit Note
        invoice_type_code = "388" if is_sale else "383"
        invoice_type_name = "فاتورة ضريبية عامة (Tax Invoice)" if is_sale else "إيصال توريد / مشتريات (Purchase Invoice)"

        total = float(getattr(transaction, "total_amount", 0.0) or 0.0)
        tax = float(getattr(transaction, "tax_amount", 0.0) or 0.0)
        service = float(getattr(transaction, "service_charge", 0.0) or 0.0)
        subtotal = float(getattr(transaction, "subtotal", 0.0) or 0.0)
        
        if subtotal <= 0:
            subtotal = max(0.0, round(total - tax - service, 3))

        inv_num = getattr(transaction, "invoice_number", None) or f"JO-{str(getattr(transaction, 'id', ''))[:8].upper()}"

        branch_name = getattr(branch, "name", "الفرع الرئيسي") if branch else "الفرع الرئيسي"

        # تفصيل طرق الدفع
        pb = getattr(transaction, "payment_breakdown", {}) or {}
        payment_means = []
        if pb.get("cash"):
            payment_means.append({"code": "10", "name": "Cash (نقد)", "amount": pb["cash"]})
        if pb.get("card"):
            payment_means.append({"code": "48", "name": "Bank Card / POS (بطاقة دفع)", "amount": pb["card"]})
        if pb.get("cliq"):
            payment_means.append({"code": "42", "name": "Payment to Bank Account / CliQ (كليك)", "amount": pb["cliq"]})
        if pb.get("delivery_apps"):
            payment_means.append({"code": "57", "name": "Delivery Application (تطبيق توصيل)", "amount": pb["delivery_apps"]})
        if not payment_means:
            payment_means.append({"code": "10", "name": "Cash (نقد)", "amount": total})

        buyer_name = "مستهلك نهائي (End Consumer - B2C)" if is_sale else (getattr(transaction, "merchant_or_supplier_name", "المورد") or "غير محدد")
        buyer_tin = getattr(transaction, "supplier_tax_id", None) if not is_sale else None

        payload = {
            "jofotara_schema_version": "2025.1",
            "invoice_uuid": str(getattr(transaction, "id", "")),
            "invoice_number": inv_num,
            "issue_date": str(getattr(transaction, "transaction_date", datetime.date.today())),
            "issue_time": qr_info["timestamp"][11:19] if "T" in qr_info["timestamp"] else "12:00:00",
            "invoice_type": {
                "code": invoice_type_code,
                "name": invoice_type_name
            },
            "document_currency_code": "JOD",
            "tax_currency_code": "JOD",
            "seller_supplier_party": {
                "party_name": getattr(org, "name", "المنشأة التجارية"),
                "tax_identification_number": getattr(org, "tax_number", None) or "غير مسجل ضريبياً",
                "is_tax_registered": bool(getattr(org, "tax_number", None)),
                "branch_name": branch_name,
                "country_code": "JO"
            },
            "buyer_customer_party": {
                "party_name": buyer_name,
                "tax_identification_number": buyer_tin,
                "is_tax_registered": bool(buyer_tin),
                "party_type": "B2C" if is_sale else "B2B"
            },
            "payment_means": payment_means,
            "tax_category_subtotals": [
                {
                    "tax_category_code": "S",
                    "tax_category_name": "Standard Rate (خاضع للضريبة بالنسبة العامة 16%)",
                    "tax_percentage": 16.0,
                    "taxable_amount": round(subtotal + service, 3),
                    "tax_amount": round(tax, 3)
                }
            ],
            "legal_monetary_total": {
                "line_extension_amount": round(subtotal, 3),
                "service_charge_amount": round(service, 3),
                "tax_exclusive_amount": round(subtotal + service, 3),
                "tax_amount": round(tax, 3),
                "tax_inclusive_amount": round(total, 3),
                "payable_amount": round(total, 3)
            },
            "qr_code_tlv_base64": qr_info["tlv_base64"],
            "compliance_status": {
                "is_tin_valid": bool(getattr(org, "tax_number", None)),
                "is_amounts_balanced": abs((subtotal + service + tax) - total) < 0.05,
                "is_ready_for_istd_transmission": bool(getattr(org, "tax_number", None) and total > 0)
            }
        }

        return payload
