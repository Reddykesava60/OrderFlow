import base64
import hmac
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlencode, urlparse

import qrcode


def signed_metadata(order_id, payment_id, amount, secret):
    message = f"{order_id}:{payment_id}:{Decimal(amount):.2f}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, sha256).hexdigest()


def build_upi_uri(vpa, merchant_name, amount, transaction_ref, note, metadata_signature=""):
    if not vpa:
        return ""
    params = {
        "pa": vpa,
        "pn": merchant_name[:80],
        "am": f"{Decimal(amount):.2f}",
        "cu": "INR",
        "tr": transaction_ref.replace("-", "")[:35],
        "tn": note[:70],
    }
    if metadata_signature:
        params["mc"] = metadata_signature[:20]
    return f"upi://pay?{urlencode(params)}"


def build_app_intent_urls(upi_uri):
    if not upi_uri:
        return {}
    query = urlparse(upi_uri).query
    return {
        "gpay": f"tez://upi/pay?{query}",
        "phonepe": f"phonepe://upi/pay?{query}",
        "paytm": f"paytmmp://upi/pay?{query}",
        "generic": f"upi://pay?{query}",
    }


def qr_data_uri(payload):
    if not payload:
        return ""
    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
