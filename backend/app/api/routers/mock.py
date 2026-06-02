"""Mock IKEA / payments endpoints — deterministic stand-ins for the external APIs the IKEA "Riya"
cart-recovery tools call (cart, customer, pincode, stock, EMI, payment link, reminder, escalation).

Demo-only: canned responses, no real IKEA/Razorpay. This router is mounted by the STANDALONE mock
server (app/mock_api.py) on its own port, so the orchestrator's HTTP tools hit a genuinely external
service. Each route sets an explicit `operation_id` so importing this server's /openapi.json via
POST /api/tools/import produces cleanly-named tools (get_cart, generate_payment_link, …)."""
from fastapi import APIRouter, Body, Query

router = APIRouter(prefix="/mock", tags=["mock"])

_TOP_ITEM = "STRANDMON wing chair"
_CART = {
    "customer_id": "C-1024",
    "first_name": "Aarav",
    "city": "Bengaluru",
    "items": [
        {"name": _TOP_ITEM, "variant": "Nordvalla dark grey", "price": 14999},
        {"name": "POÄNG footstool", "variant": "beige", "price": 4999},
    ],
    "total": 19998,
    "currency": "INR",
    "top_item": _TOP_ITEM,
}


@router.get("/cart", operation_id="get_cart", summary="Fetch the customer's saved cart")
def mock_cart(customer_id: str = Query("C-1024")):
    return {**_CART, "customer_id": customer_id}


@router.get("/customer", operation_id="get_customer", summary="Look up the customer profile")
def mock_customer(customer_id: str = Query("C-1024")):
    return {"customer_id": customer_id, "first_name": "Aarav", "city": "Bengaluru",
            "ikea_family": True, "past_orders": 3, "marketing_opt_in": True, "active_complaint": False}


@router.get("/pincode", operation_id="check_pincode", summary="Check delivery serviceability + ETA")
def mock_pincode(pincode: str = Query("560001")):
    return {"pincode": pincode, "serviceable": True, "delivery_days": 4,
            "eta": "in 4 business days", "click_and_collect": "IKEA Nagasandra (free)"}


@router.get("/stock", operation_id="check_stock", summary="Check stock level for a product in a city")
def mock_stock(product: str = Query(_TOP_ITEM), city: str = Query("Bengaluru")):
    return {"product": product, "city": city, "in_stock": True, "units_left": 7, "restock_weeks": 3}


@router.get("/emi", operation_id="calculate_emi", summary="Compute the No-Cost EMI monthly amount")
def mock_emi(amount: float = Query(19998)):
    tenure = 12
    return {"amount": amount, "tenure_months": tenure, "monthly": round(amount / tenure),
            "no_cost": True, "currency": "INR"}


@router.post("/payment-link", operation_id="generate_payment_link", summary="Create a secure 24h checkout link")
def mock_payment_link(body: dict = Body(default={})):
    cid = body.get("customer_id", "C-1024")
    return {"url": f"https://pay.ikea.in/checkout/{cid}", "expires_in_hours": 24,
            "methods": ["UPI", "Cards", "Net Banking", "No-Cost EMI"], "secure": True,
            "provider": "Razorpay"}


@router.post("/reminder", operation_id="set_reminder", summary="Schedule a follow-up reminder")
def mock_reminder(body: dict = Body(default={})):
    return {"scheduled": True, "when": body.get("when", "in 2 days"), "note": body.get("note", "")}


@router.post("/escalate", operation_id="escalate_to_human", summary="Hand off to a human agent")
def mock_escalate(body: dict = Body(default={})):
    return {"ticket_id": "ESC-4471", "queued": True, "channel": "human agent",
            "reason": body.get("reason", "")}
