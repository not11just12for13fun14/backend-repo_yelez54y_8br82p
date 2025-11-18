Coupon Management System (FastAPI)

Overview
- A production-ready Coupon Management API for an e-commerce use case.
- Supports creating coupons (in-memory), listing coupons, computing the best applicable coupon for a user/cart with deterministic tie-breakers, and a demo login route.
- In-memory storage by design (no database), as required.

Features
- POST /coupons: Create coupons with validation; rejects duplicate codes.
- GET /coupons: Retrieve all coupons currently stored (in-memory).
- POST /best-coupon: Given user and cart, filters valid/eligible coupons, computes discount, and selects the best with deterministic tie-breakers.
- POST /login: Validates the demo account and returns a fake token and userId.
- Helper: POST /use-coupon/{code}: Increment usage for a user to test usage limits (not part of formal spec, but helpful during testing).

Deterministic Best-Coupon Logic
1) Highest computed discount wins.
2) If tied, the coupon with the earliest endDate wins.
3) If still tied, the lexicographically smaller code wins.

Eligibility Rules Implemented
- User tier allowlist
- Country allowlist
- First order only
- Minimum orders placed
- Minimum lifetime spend
- Minimum cart value
- Minimum items count
- Applicable categories allowlist
- Excluded categories blocklist

Tech Stack
- Backend: FastAPI (Python 3.10+)
- Server: Uvicorn
- Validation: Pydantic v2

How to Run
1) Ensure Python 3.10+ is available.
2) Install dependencies:
   pip install -r requirements.txt
3) Start the server:
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
4) API base URL:
   http://localhost:8000
5) Interactive docs:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

Data Model Summary
Coupon
- code (string, required)
- description (string)
- discountType ("FLAT" | "PERCENT")
- discountValue (number > 0)
- maxDiscountAmount (number > 0, optional; used as cap for PERCENT)
- startDate (ISO 8601 datetime)
- endDate (ISO 8601 datetime; must be after startDate)
- usageLimitPerUser (integer >= 1)
- eligibility (object):
  - allowedUserTiers (string[])
  - minLifetimeSpend (number >= 0)
  - minOrdersPlaced (integer >= 0)
  - firstOrderOnly (boolean)
  - allowedCountries (string[])
  - minCartValue (number >= 0)
  - applicableCategories (string[])
  - excludedCategories (string[])
  - minItemsCount (integer >= 0)

Request/Response Contracts
- POST /coupons (201)
  Body: Coupon object as described.
  Errors: 400 Duplicate coupon code, 422 validation.

- GET /coupons (200)
  Response: Coupon[]

- POST /best-coupon (200)
  Body:
  {
    "user": { "userId": "u1", "userTier": "GOLD", "country": "US", "lifetimeSpend": 500, "ordersPlaced": 10 },
    "cart": { "items": [ { "productId": "p1", "category": "ELECTRONICS", "unitPrice": 200, "quantity": 1 } ] },
    "evaluateUsageImpact": true
  }
  Response:
  - If a best coupon exists:
    { "bestCoupon": { ...coupon }, "computedDiscount": 25.0, "projectedUsageForUser": 1, "usageLimitPerUser": 2 }
  - If none:
    { "bestCoupon": null }

- POST /login (200)
  Body:
  { "email": "hire-me@anshumat.org", "password": "HireMe@2025!" }
  Response:
  { "token": "fake-token-...", "userId": "user-..." }
  Errors: 401 Invalid credentials

- POST /use-coupon/{code} (helper)
  Body:
  { "userId": "u1", "userTier": "GOLD", "country": "US", "lifetimeSpend": 500, "ordersPlaced": 10 }
  Response:
  { "code": "SAVE10", "userId": "u1", "newUsage": 1, "limit": 2 }

Sample curl Commands
# Create a FLAT coupon (SAVE10)
curl -X POST http://localhost:8000/coupons \
  -H "Content-Type: application/json" \
  -d '{
    "code":"SAVE10",
    "description":"Flat 10 off",
    "discountType":"FLAT",
    "discountValue":10,
    "startDate":"2025-01-01T00:00:00Z",
    "endDate":"2026-01-01T00:00:00Z",
    "usageLimitPerUser":2,
    "eligibility":{
      "allowedUserTiers":["GOLD","SILVER"],
      "minCartValue":50,
      "applicableCategories":["ELECTRONICS"]
    }
  }'

# Create a PERCENT coupon (SAVE25)
curl -X POST http://localhost:8000/coupons \
  -H "Content-Type: application/json" \
  -d '{
    "code":"SAVE25",
    "description":"25% off up to $40",
    "discountType":"PERCENT",
    "discountValue":25,
    "maxDiscountAmount":40,
    "startDate":"2025-01-01T00:00:00Z",
    "endDate":"2026-01-01T00:00:00Z",
    "usageLimitPerUser":1,
    "eligibility":{
      "minCartValue":100
    }
  }'

# List coupons
curl http://localhost:8000/coupons

# Compute best coupon
curl -X POST http://localhost:8000/best-coupon \
  -H "Content-Type: application/json" \
  -d '{
    "user":{ "userId":"u123", "userTier":"GOLD", "country":"US", "lifetimeSpend":1000, "ordersPlaced":5 },
    "cart":{ "items":[ { "productId":"p1", "category":"ELECTRONICS", "unitPrice":200, "quantity":1 } ] },
    "evaluateUsageImpact": true
  }'

# Demo login
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"email":"hire-me@anshumat.org","password":"HireMe@2025!"}'

# Simulate using a coupon (increment usage for the user)
curl -X POST http://localhost:8000/use-coupon/SAVE25 \
  -H "Content-Type: application/json" \
  -d '{"userId":"u123","userTier":"GOLD","country":"US","lifetimeSpend":1000,"ordersPlaced":5}'

Testing Tips
- Use the /use-coupon/{code} helper to reach usage limits and verify that /best-coupon excludes coupons once the user hits their per-user limit.
- Adjust dates so coupons are currently valid (ensure now is between startDate and endDate in UTC).
- Category checks:
  - If applicableCategories is set, at least one cart item category must match.
  - If excludedCategories is set, no cart item category may be in that list.

Folder Structure
- main.py (FastAPI app and all routes)
- requirements.txt (dependencies)
- README.md (this file)

AI Usage Note
This project was generated with assistance from an AI coding agent to accelerate development. All logic, constraints, and contracts were implemented to match the provided specification exactly, with additional helper endpoints and examples added to improve testing and developer experience.

Prompts Used
- "Build a complete, production-ready Coupon Management System" with detailed requirements provided in the assignment specification.
