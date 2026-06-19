"""Product catalog endpoints. Admin manages products; staff has read-only access."""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models import Product, User, UserRole
from app.schemas import ProductCreate, ProductListResponse, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])

MAX_LIMIT = 100
_SORT_COLUMNS = {
    "name": Product.name,
    "price": Product.price,
    "stock_quantity": Product.stock_quantity,
    "created_at": Product.created_at,
}


@router.get("", response_model=ProductListResponse)
async def list_products(
    skip: int = 0,
    limit: int = 20,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    in_stock: bool | None = None,
    search: str | None = None,
    sort_by: Literal["name", "price", "stock_quantity", "created_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductListResponse:
    limit = min(max(limit, 1), MAX_LIMIT)
    skip = max(skip, 0)

    filters = [Product.is_active.is_(True)]
    if min_price is not None:
        filters.append(Product.price >= min_price)
    if max_price is not None:
        filters.append(Product.price <= max_price)
    if in_stock is True:
        filters.append(Product.stock_quantity > 0)
    elif in_stock is False:
        filters.append(Product.stock_quantity == 0)
    if search:
        filters.append(Product.name.ilike(f"%{search}%"))

    column = _SORT_COLUMNS[sort_by]
    order_clause = column.asc() if order == "asc" else column.desc()

    count_stmt = select(func.count()).select_from(Product).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Product).where(*filters).order_by(order_clause).offset(skip).limit(limit)
    items = (await db.execute(stmt)).scalars().all()

    return ProductListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Product:
    product = await db.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> Product:
    existing = await db.execute(select(Product).where(Product.sku == payload.sku))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SKU already exists")

    product = Product(**payload.model_dump())
    db.add(product)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="SKU already exists"
        ) from None
    await db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    updates = payload.model_dump(exclude_unset=True)
    if "sku" in updates and updates["sku"] != product.sku:
        existing = await db.execute(select(Product).where(Product.sku == updates["sku"]))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SKU already exists")

    for field, value in updates.items():
        setattr(product, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="SKU already exists"
        ) from None
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> None:
    """Soft-delete: historical OrderItems still reference this product."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    product.is_active = False
    await db.commit()
