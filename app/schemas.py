"""Pydantic v2 request/response models."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import OrderStatus, UserRole

# ---------------------------------------------------------------------------
# Auth / User
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        # bcrypt only uses the first 72 bytes of input and silently truncates
        # the rest rather than erroring, so a UTF-8 password near the 128-char
        # limit could be weakened invisibly. Reject it cleanly instead.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes when UTF-8 encoded")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    phone: str | None
    created_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerRead]
    total: int
    skip: int
    limit: int


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    stock_quantity: int = Field(ge=0)


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    stock_quantity: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str | None
    price: Decimal
    stock_quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    items: list[ProductRead]
    total: int
    skip: int
    limit: int


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    customer_id: int
    items: list[OrderItemCreate] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def no_duplicate_products(cls, items: list[OrderItemCreate]) -> list[OrderItemCreate]:
        seen = set()
        for item in items:
            if item.product_id in seen:
                raise ValueError(
                    f"Duplicate product_id {item.product_id} in order items; "
                    "combine quantities into a single line item instead."
                )
            seen.add(item.product_id)
        return items


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class OrderListResponse(BaseModel):
    items: list[OrderRead]
    total: int
    skip: int
    limit: int


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: int
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
