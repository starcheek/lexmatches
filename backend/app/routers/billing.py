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


def _customer_id(user: dict) -> str | None:
    """The Stripe customer created for this account at checkout. Never looked up by e-mail: addresses here are
    not verified, so anyone could sign up with a paying customer's address and reach their billing portal."""
    row = db.fetch_one("SELECT stripe_customer_id FROM users WHERE id = %s", (user["id"],))
    return row["stripe_customer_id"] if row else None


@router.get("/subscription")
def subscription(user: dict = Depends(auth.current_user)):
    if not settings.billing_enabled:
        return {"billing_enabled": False, "subscribed": True, "unlimited": True, "freePages": 0}
    row = db.fetch_one("SELECT pages_translated_free FROM users WHERE id = %s", (user["id"],))
    free_pages = row["pages_translated_free"] if row else 0
    customer = _customer_id(user)
    if customer is None:
        return {"billing_enabled": True, "subscribed": False, "unlimited": False, "freePages": free_pages}
    stripe = _stripe()
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
    """Where Stripe sends the user back: the configured site, never the request's Origin header (open redirect)."""
    return settings.public_origin or str(request.base_url).rstrip("/")


@router.post("/billing/checkout")
def checkout(request: Request, user: dict = Depends(auth.current_user)):
    if not settings.billing_enabled:
        raise HTTPException(404, "Billing is disabled")
    stripe = _stripe()
    customer = _customer_id(user)
    if customer is None:
        customer = stripe.Customer.create(email=user["email"], metadata={"user_id": str(user["id"])}).id
        db.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s", (customer, user["id"]))
    origin = _origin(request)
    session = stripe.checkout.Session.create(
        customer=customer,
        client_reference_id=str(user["id"]),
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
    customer = _customer_id(user)
    if customer is None:
        raise HTTPException(404, "No Stripe customer found for this user")
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(customer=customer, return_url=f"{_origin(request)}/dashboard")
    return {"url": session.url}
