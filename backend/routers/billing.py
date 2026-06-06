"""
Billing router — PayPal-only upgrade flow.
Stripe removed; all payments handled via PayPal.me link.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/billing")
