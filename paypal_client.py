import os, uuid, requests

BASE = "https://api-m.sandbox.paypal.com"

def _check(r):
    if not r.ok:
        raise RuntimeError(f"PayPal error {r.status_code}: {r.text}")
    return r.json() if r.text else {}

def _token():
    r = requests.post(
        f"{BASE}/v1/oauth2/token",
        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_SECRET"]),
        data={"grant_type": "client_credentials"}, timeout=30)
    return _check(r)["access_token"]

def _headers():
    return {"Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": str(uuid.uuid4())}

def create_escrow_order(amount: float, return_url: str):
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "description": "AuraLock escrow deposit",
            "amount": {"currency_code": "USD", "value": f"{amount:.2f}"}}],
        "payment_source": {"paypal": {"experience_context": {
            "return_url": return_url, "cancel_url": return_url,
            "user_action": "PAY_NOW"}}},
    }
    return _check(requests.post(f"{BASE}/v2/checkout/orders",
                                json=body, headers=_headers(), timeout=30))

def approval_link(order: dict) -> str:
    for l in order["links"]:
        if l["rel"] in ("payer-action", "approve"):
            return l["href"]
    raise RuntimeError("No approval link in order response")

def capture_order(order_id: str) -> str:
    r = requests.post(f"{BASE}/v2/checkout/orders/{order_id}/capture",
                      json={}, headers=_headers(), timeout=30)
    data = _check(r)
    return data["purchase_units"][0]["payments"]["captures"][0]["id"]

def send_payout(email: str, amount: float, note: str, batch_id: str) -> str:
    body = {
        "sender_batch_header": {"sender_batch_id": batch_id,
                                "email_subject": "AuraLock payout"},
        "items": [{"recipient_type": "EMAIL",
                   "amount": {"value": f"{amount:.2f}", "currency": "USD"},
                   "receiver": email, "note": note,
                   "sender_item_id": batch_id}],
    }
    r = requests.post(f"{BASE}/v1/payments/payouts",
                      json=body, headers=_headers(), timeout=30)
    return _check(r)["batch_header"]["payout_batch_id"]

def refund_capture(capture_id: str, amount: float) -> str:
    body = {"amount": {"value": f"{amount:.2f}", "currency_code": "USD"}}
    r = requests.post(f"{BASE}/v2/payments/captures/{capture_id}/refund",
                      json=body, headers=_headers(), timeout=30)
    return _check(r)["id"]
