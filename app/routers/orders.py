"""Order creation, listing, and status-transition endpoints.

Order creation and cancellation both mutate Product.stock_quantity; both are
written so that all validation happens before any mutation, and the whole
operation runs inside one DB transaction, so a failure partway through never
leaves stock decremented/incremented for only some of the items.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models import Customer, Order, OrderItem, OrderStatus, Product, User, UserRole
from app.schemas import OrderCreate, OrderListResponse, OrderRead, OrderStatusUpdate

router = APIRouter(prefix="/orders", tags=["orders"])

MAX_LIMIT = 100

# Allowed status transitions: current -> set of permitted next statuses.
_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: set(),
    OrderStatus.CANCELLED: set(),
}

_staff_or_admin = require_role(UserRole.ADMIN, UserRole.STAFF)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_staff_or_admin),
) -> Order:
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    product_ids = [item.product_id for item in payload.items]
    result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    products_by_id = {p.id: p for p in result.scalars().all()}

    for item in payload.items:
        product = products_by_id.get(item.product_id)
        if product is None or not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item.product_id} not found",
            )

    # Verify sufficient stock for every item BEFORE mutating anything.
    insufficient = [
        f"product {item.product_id} (requested {item.quantity}, available "
        f"{products_by_id[item.product_id].stock_quantity})"
        for item in payload.items
        if products_by_id[item.product_id].stock_quantity < item.quantity
    ]
    if insufficient:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock for: {', '.join(insufficient)}",
        )

    order = Order(customer_id=payload.customer_id, status=OrderStatus.PENDING, total_amount=0)
    total = 0
    for item in payload.items:
        product = products_by_id[item.product_id]
        product.stock_quantity -= item.quantity
        line_total = product.price * item.quantity
        total += line_total
        order.items.append(
            OrderItem(product_id=product.id, quantity=item.quantity, unit_price=product.price)
        )
    order.total_amount = total

    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.get("", response_model=OrderListResponse)
async def list_orders(
    skip: int = 0,
    limit: int = 20,
    status_filter: OrderStatus | None = None,
    customer_id: int | None = None,
    order: Literal["asc", "desc"] = "desc",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_staff_or_admin),
) -> OrderListResponse:
    limit = min(max(limit, 1), MAX_LIMIT)
    skip = max(skip, 0)

    filters = []
    if status_filter is not None:
        filters.append(Order.status == status_filter)
    if customer_id is not None:
        filters.append(Order.customer_id == customer_id)

    count_stmt = select(func.count()).select_from(Order).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    order_clause = Order.created_at.asc() if order == "asc" else Order.created_at.desc()
    stmt = select(Order).where(*filters).order_by(order_clause).offset(skip).limit(limit)
    items = (await db.execute(stmt)).scalars().all()

    return OrderListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_staff_or_admin),
) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_staff_or_admin),
) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if payload.status not in _ALLOWED_TRANSITIONS.get(order.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition order from {order.status.value} to {payload.status.value}",
        )

    if payload.status == OrderStatus.CANCELLED and order.status in (
        OrderStatus.PENDING,
        OrderStatus.PAID,
    ):
        result = await db.execute(
            select(Product).where(Product.id.in_([i.product_id for i in order.items]))
        )
        products_by_id = {p.id: p for p in result.scalars().all()}
        for item in order.items:
            product = products_by_id.get(item.product_id)
            if product is not None:
                product.stock_quantity += item.quantity

    order.status = payload.status
    await db.commit()
    await db.refresh(order)
    return order
