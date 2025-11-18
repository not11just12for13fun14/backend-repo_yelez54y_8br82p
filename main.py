import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr, validator
from enum import Enum

# ==========================
# Domain Models & Validation
# ==========================
class DiscountType(str, Enum):
    FLAT = "FLAT"
    PERCENT = "PERCENT"


class Eligibility(BaseModel):
    allowedUserTiers: Optional[List[str]] = Field(default=None, description="Allowed user tiers (e.g., BRONZE/SILVER/GOLD)")
    minLifetimeSpend: Optional[float] = Field(default=None, ge=0)
    minOrdersPlaced: Optional[int] = Field(default=None, ge=0)
    firstOrderOnly: Optional[bool] = False
    allowedCountries: Optional[List[str]] = None
    minCartValue: Optional[float] = Field(default=None, ge=0)
    applicableCategories: Optional[List[str]] = None
    excludedCategories: Optional[List[str]] = None
    minItemsCount: Optional[int] = Field(default=None, ge=0)


class Coupon(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None
    discountType: DiscountType
    discountValue: float = Field(..., gt=0)
    maxDiscountAmount: Optional[float] = Field(default=None, gt=0, description="Cap for percent discount")
    startDate: datetime
    endDate: datetime
    usageLimitPerUser: int = Field(..., ge=1)
    eligibility: Eligibility = Field(default_factory=Eligibility)

    @validator("endDate")
    def validate_date_range(cls, v, values):
        start = values.get("startDate")
        if start and v <= start:
            raise ValueError("endDate must be after startDate")
        return v

    @validator("maxDiscountAmount")
    def validate_cap_for_percent(cls, v, values):
        if values.get("discountType") == DiscountType.PERCENT and v is None:
            # it's allowed to be None (uncapped), keep as is
            return v
        return v


class CartItem(BaseModel):
    productId: str
    category: str
    unitPrice: float = Field(..., ge=0)
    quantity: int = Field(..., ge=1)


class Cart(BaseModel):
    items: List[CartItem]

    def total_value(self) -> float:
        return sum(item.unitPrice * item.quantity for item in self.items)

    def total_items_count(self) -> int:
        return sum(item.quantity for item in self.items)

    def categories(self) -> List[str]:
        return list({item.category for item in self.items})


class UserInfo(BaseModel):
    userId: str
    userTier: Optional[str] = None
    country: Optional[str] = None
    lifetimeSpend: float = Field(default=0, ge=0)
    ordersPlaced: int = Field(default=0, ge=0)


class BestCouponInput(BaseModel):
    user: UserInfo
    cart: Cart
    evaluateUsageImpact: Optional[bool] = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    token: str
    userId: str


# ==========================
# Application Setup
# ==========================
app = FastAPI(title="Coupon Management API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# In-memory Storage
# ==========================
# Coupons keyed by code (case-sensitive per spec)
COUPONS: Dict[str, Coupon] = {}
# Usage counts per coupon code -> userId -> count
USAGE: Dict[str, Dict[str, int]] = {}


# ==========================
# Utility Functions
# ==========================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_within_validity(coupon: Coupon, ref: Optional[datetime] = None) -> bool:
    t = ref or now_utc()
    return coupon.startDate <= t <= coupon.endDate


def user_usage_for_coupon(code: str, user_id: str) -> int:
    return USAGE.get(code, {}).get(user_id, 0)


def check_eligibility(coupon: Coupon, user: UserInfo, cart: Cart) -> bool:
    # User tier
    if coupon.eligibility.allowedUserTiers:
        if (user.userTier or "").upper() not in {t.upper() for t in coupon.eligibility.allowedUserTiers}:
            return False

    # Country
    if coupon.eligibility.allowedCountries:
        if (user.country or "").upper() not in {c.upper() for c in coupon.eligibility.allowedCountries}:
            return False

    # First order only
    if coupon.eligibility.firstOrderOnly and user.ordersPlaced != 0:
        return False

    # Orders placed minimum
    if coupon.eligibility.minOrdersPlaced is not None and user.ordersPlaced < coupon.eligibility.minOrdersPlaced:
        return False

    # Lifetime spend minimum
    if coupon.eligibility.minLifetimeSpend is not None and user.lifetimeSpend < coupon.eligibility.minLifetimeSpend:
        return False

    # Min cart value
    cart_total = cart.total_value()
    if coupon.eligibility.minCartValue is not None and cart_total < coupon.eligibility.minCartValue:
        return False

    # Min items count
    if coupon.eligibility.minItemsCount is not None and cart.total_items_count() < coupon.eligibility.minItemsCount:
        return False

    # Applicable/excluded categories
    cats = {c.upper() for c in cart.categories()}
    if coupon.eligibility.applicableCategories:
        allowed = {c.upper() for c in coupon.eligibility.applicableCategories}
        if cats.isdisjoint(allowed):
            return False
    if coupon.eligibility.excludedCategories:
        excluded = {c.upper() for c in coupon.eligibility.excludedCategories}
        if not cats.isdisjoint(excluded):
            return False

    return True


def calculate_discount(coupon: Coupon, cart: Cart) -> float:
    cart_value = cart.total_value()
    discount = 0.0
    if coupon.discountType == DiscountType.FLAT:
        discount = float(coupon.discountValue)
    elif coupon.discountType == DiscountType.PERCENT:
        discount = cart_value * (float(coupon.discountValue) / 100.0)
        if coupon.maxDiscountAmount is not None:
            discount = min(discount, float(coupon.maxDiscountAmount))
    # Discount cannot exceed cart total
    return max(0.0, min(discount, cart_value))


def best_coupon(user: UserInfo, cart: Cart, evaluate_usage_impact: bool = False) -> Optional[Dict[str, Any]]:
    """
    Returns a dict containing coupon and computed discount or None.
    Tie-breakers:
      1) Highest discount
      2) Earliest endDate
      3) Lexicographically smaller code
    """
    candidates = []
    reference_time = now_utc()
    for code, coupon in COUPONS.items():
        # Validity window
        if not is_within_validity(coupon, reference_time):
            continue
        # Usage limit per user
        if user_usage_for_coupon(code, user.userId) >= coupon.usageLimitPerUser:
            continue
        # Eligibility
        if not check_eligibility(coupon, user, cart):
            continue
        disc = calculate_discount(coupon, cart)
        if disc <= 0:
            continue
        candidates.append({
            "coupon": coupon,
            "discount": round(disc, 2),
        })

    if not candidates:
        return None

    # Deterministic selection with tie breakers
    # Sort by: -discount (desc), endDate (asc), code (asc)
    candidates.sort(key=lambda x: (
        -x["discount"],
        x["coupon"].endDate,
        x["coupon"].code
    ))

    top = candidates[0]
    result: Dict[str, Any] = {
        "coupon": top["coupon"],
        "computedDiscount": top["discount"],
    }
    if evaluate_usage_impact:
        # Projected usage if applied now
        current = user_usage_for_coupon(top["coupon"].code, user.userId)
        result["projectedUsageForUser"] = current + 1
        result["usageLimitPerUser"] = top["coupon"].usageLimitPerUser
    return result


# ==========================
# API Routes
# ==========================
@app.get("/")
def root():
    return {"service": "Coupon Management API", "status": "ok"}


@app.post("/coupons", response_model=Coupon, status_code=201)
def create_coupon(coupon: Coupon):
    code = coupon.code
    if code in COUPONS:
        raise HTTPException(status_code=400, detail="Duplicate coupon code")
    # Store
    COUPONS[code] = coupon
    # Initialize usage map
    if code not in USAGE:
        USAGE[code] = {}
    return coupon


@app.get("/coupons", response_model=List[Coupon])
def list_coupons():
    return list(COUPONS.values())


@app.post("/best-coupon")
def get_best_coupon(payload: BestCouponInput):
    result = best_coupon(payload.user, payload.cart, payload.evaluateUsageImpact or False)
    if not result:
        return {"bestCoupon": None}
    # Pydantic models are JSON serializable, but ensure format
    return {
        "bestCoupon": result["coupon"],
        "computedDiscount": result["computedDiscount"],
        **({
            "projectedUsageForUser": result.get("projectedUsageForUser"),
            "usageLimitPerUser": result.get("usageLimitPerUser"),
        } if payload.evaluateUsageImpact else {})
    }


DEMO_EMAIL = "hire-me@anshumat.org"
DEMO_PASSWORD = "HireMe@2025!"


@app.post("/login", response_model=LoginResponse)
def login(body: LoginRequest = Body(...)):
    if body.email.lower() != DEMO_EMAIL or body.password != DEMO_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Fake token & user id (derived for demo)
    token = "fake-token-" + str(hash(body.email))
    user_id = "user-" + str(abs(hash(body.email)) % 10_000)
    return LoginResponse(token=token, userId=user_id)


# Helper endpoint to simulate applying a coupon (increments usage)
# Not in original spec, but useful for testing usage limits deterministically.
@app.post("/use-coupon/{code}")
def use_coupon(code: str, body: UserInfo):
    if code not in COUPONS:
        raise HTTPException(status_code=404, detail="Coupon not found")
    # Increment usage for this user if still allowed
    current = user_usage_for_coupon(code, body.userId)
    limit = COUPONS[code].usageLimitPerUser
    if current >= limit:
        raise HTTPException(status_code=429, detail="Usage limit reached for this user")
    USAGE.setdefault(code, {})[body.userId] = current + 1
    return {"code": code, "userId": body.userId, "newUsage": current + 1, "limit": limit}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
