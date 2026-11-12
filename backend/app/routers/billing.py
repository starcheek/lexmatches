"""Stripe billing (port of check-subscription / create-checkout / customer-portal).

OFF unless STRIPE_SECRET_KEY is set: then every user is reported as subscribed/unlimited.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, db
from app.config import settings

router = APIRouter(prefix="/api", tags=["billing"])


def _stripe():
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _customer_id(stripe, email: str) -> str | None:
    customers = stripe.Customer.list(email=email, limit=1)
    return customers.data[0].id if customers.data else None


@router.get("/subscription")
def subscription(user: dict = Depends(auth.current_user)):
    if not settings.billing_enabled:
        return {"billing_enabled": False, "subscribed": True, "unlimited": True, "freePages": 0}
    row = db.fetch_one("SELECT pages_translated_free FROM users WHERE id = %s", (user["id"],))
    free_pages = row["pages_translated_free"] if row else 0
    stripe = _stripe()
    customer = _customer_id(stripe, user["email"])
    if customer is None:
        return {"billing_enabled": True, "subscribed": False, "unlimited": False, "freePages": free_pages}
    subs = stripe.Subscription.list(customer=customer, status="active", limit=1)
    product_id = subscription_end = None
    if subs.data:
        sub = subs.data[0]
        item = sub["items"]["data"][0] if sub["items"]["data"] else None
        if item is not None:
            product_id = item["price"]["product"]
            period_end = item.get("current_period_end") or sub.get("current_period_end")
            if period_end:
                subscription_end = datetime.fromtimestamp(period_end, timezone.utc).isoformat()
    return {
        "billing_enabled": True,
        "subscribed": bool(subs.data),
        "unlimited": bool(subs.data),
        "product_id": product_id,
        "subscription_end": subscription_end,
        "freePages": free_pages,
    }


def _origin(request: Request) -> str:
    return request.headers.get("origin") or str(request.base_url).rstrip("/")


@router.post("/billing/checkout")
def checkout(request: Request, user: dict = Depends(auth.current_user)):
    if not settings.billing_enabled:
        raise HTTPException(404, "Billing is disabled")
    stripe = _stripe()
    customer = _customer_id(stripe, user["email"])
    origin = _origin(request)
    session = stripe.checkout.Session.create(
        customer=customer,
        customer_email=None if customer else user["email"],
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{origin}/dashboard?success=true",
        cancel_url=f"{origin}/dashboard?canceled=true",
    )
    return {"url": session.url}


@router.post("/billing/portal")
def portal(request: Request, user: dict = Depends(auth.current_user)):
    if not settings.billing_enabled:
        raise HTTPException(404, "Billing is disabled")
    stripe = _stripe()
    customer = _customer_id(stripe, user["email"])
    if customer is None:
        raise HTTPException(404, "No Stripe customer found for this user")
    session = stripe.billing_portal.Session.create(customer=customer, return_url=f"{_origin(request)}/dashboard")
    return {"url": session.url}
