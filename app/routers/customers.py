"""Customer management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models import Customer, Order, User, UserRole
from app.schemas import CustomerCreate, CustomerListResponse, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])

MAX_LIMIT = 100


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    skip: int = 0,
    limit: int = 20,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomerListResponse:
    limit = min(max(limit, 1), MAX_LIMIT)
    skip = max(skip, 0)

    filters = []
    if search:
        pattern = f"%{search}%"
        filters.append(or_(Customer.name.ilike(pattern), Customer.email.ilike(pattern)))

    count_stmt = select(func.count()).select_from(Customer).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Customer).where(*filters).order_by(Customer.id).offset(skip).limit(limit)
    items = (await db.execute(stmt)).scalars().all()

    return CustomerListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.STAFF)),
) -> Customer:
    existing = await db.execute(select(Customer).where(Customer.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    customer = Customer(**payload.model_dump())
    db.add(customer)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        ) from None
    await db.refresh(customer)
    return customer


@router.patch("/{customer_id}", response_model=CustomerRead)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.STAFF)),
) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] != customer.email:
        existing = await db.execute(select(Customer).where(Customer.email == updates["email"]))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    for field, value in updates.items():
        setattr(customer, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        ) from None
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> None:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    has_orders = (
        await db.execute(
            select(func.count()).select_from(Order).where(Order.customer_id == customer_id)
        )
    ).scalar_one()
    if has_orders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a customer that has existing orders",
        )

    await db.delete(customer)
    await db.commit()
