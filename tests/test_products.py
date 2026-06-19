"""Product catalog: CRUD, RBAC, pagination, filtering, sorting."""
from decimal import Decimal

from httpx import AsyncClient


def _product_payload(sku="SKU-1", **overrides):
    payload = {
        "sku": sku,
        "name": "Widget",
        "description": "A widget",
        "price": "9.99",
        "stock_quantity": 10,
    }
    payload.update(overrides)
    return payload


async def test_admin_can_create_update_soft_delete_product(admin_client: AsyncClient):
    create_resp = await admin_client.post("/products", json=_product_payload())
    assert create_resp.status_code == 201
    product = create_resp.json()
    assert Decimal(str(product["price"])) == Decimal("9.99")
    assert product["is_active"] is True

    update_resp = await admin_client.patch(
        f"/products/{product['id']}", json={"price": "12.50", "stock_quantity": 5}
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert Decimal(str(updated["price"])) == Decimal("12.50")
    assert updated["stock_quantity"] == 5

    delete_resp = await admin_client.delete(f"/products/{product['id']}")
    assert delete_resp.status_code == 204

    # Soft-deleted: now invisible via the normal get.
    get_resp = await admin_client.get(f"/products/{product['id']}")
    assert get_resp.status_code == 404


async def test_staff_forbidden_from_create_update_delete(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    create_resp = await staff_client.post("/products", json=_product_payload(sku="SKU-STAFF"))
    assert create_resp.status_code == 403

    # Seed a product as admin so staff has something to attempt to mutate.
    seeded = (await admin_client.post("/products", json=_product_payload(sku="SKU-2"))).json()

    update_resp = await staff_client.patch(f"/products/{seeded['id']}", json={"price": "1.00"})
    assert update_resp.status_code == 403

    delete_resp = await staff_client.delete(f"/products/{seeded['id']}")
    assert delete_resp.status_code == 403


async def test_staff_can_read_products(admin_client: AsyncClient, staff_client: AsyncClient):
    seeded = (await admin_client.post("/products", json=_product_payload(sku="SKU-READ"))).json()
    resp = await staff_client.get(f"/products/{seeded['id']}")
    assert resp.status_code == 200


async def test_list_pagination_and_limit_clamping(admin_client: AsyncClient):
    for i in range(5):
        await admin_client.post("/products", json=_product_payload(sku=f"SKU-PAGE-{i}"))

    resp = await admin_client.get("/products", params={"skip": 1, "limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skip"] == 1
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 5

    # limit above MAX_LIMIT (100) gets clamped down to 100, not rejected.
    clamped = await admin_client.get("/products", params={"limit": 9999})
    assert clamped.status_code == 200
    assert clamped.json()["limit"] == 100


async def test_filtering_by_price_and_stock_and_search(admin_client: AsyncClient):
    await admin_client.post(
        "/products",
        json=_product_payload(sku="SKU-CHEAP", name="Cheap Gadget", price="5.00", stock_quantity=0),
    )
    await admin_client.post(
        "/products",
        json=_product_payload(
            sku="SKU-PRICEY", name="Pricey Gadget", price="500.00", stock_quantity=20
        ),
    )

    by_min_price = await admin_client.get("/products", params={"min_price": "100"})
    names = [p["name"] for p in by_min_price.json()["items"]]
    assert "Pricey Gadget" in names
    assert "Cheap Gadget" not in names

    by_max_price = await admin_client.get("/products", params={"max_price": "10"})
    names = [p["name"] for p in by_max_price.json()["items"]]
    assert "Cheap Gadget" in names
    assert "Pricey Gadget" not in names

    in_stock = await admin_client.get("/products", params={"in_stock": True})
    names = [p["name"] for p in in_stock.json()["items"]]
    assert "Pricey Gadget" in names
    assert "Cheap Gadget" not in names

    out_of_stock = await admin_client.get("/products", params={"in_stock": False})
    names = [p["name"] for p in out_of_stock.json()["items"]]
    assert "Cheap Gadget" in names
    assert "Pricey Gadget" not in names

    searched = await admin_client.get("/products", params={"search": "pricey"})
    names = [p["name"] for p in searched.json()["items"]]
    assert "Pricey Gadget" in names
    assert "Cheap Gadget" not in names


async def test_sorting_valid_and_invalid_sort_by(admin_client: AsyncClient):
    await admin_client.post(
        "/products", json=_product_payload(sku="SKU-A", name="Aaa", price="1.00")
    )
    await admin_client.post(
        "/products", json=_product_payload(sku="SKU-B", name="Bbb", price="2.00")
    )

    asc = await admin_client.get("/products", params={"sort_by": "price", "order": "asc"})
    prices = [Decimal(str(p["price"])) for p in asc.json()["items"]]
    assert prices == sorted(prices)

    desc = await admin_client.get("/products", params={"sort_by": "price", "order": "desc"})
    prices = [Decimal(str(p["price"])) for p in desc.json()["items"]]
    assert prices == sorted(prices, reverse=True)

    invalid = await admin_client.get("/products", params={"sort_by": "not_a_column"})
    assert invalid.status_code == 422


async def test_get_nonexistent_or_soft_deleted_product_returns_404(admin_client: AsyncClient):
    missing = await admin_client.get("/products/999999")
    assert missing.status_code == 404

    seeded = (await admin_client.post("/products", json=_product_payload(sku="SKU-DEL"))).json()
    await admin_client.delete(f"/products/{seeded['id']}")
    after_delete = await admin_client.get(f"/products/{seeded['id']}")
    assert after_delete.status_code == 404


async def test_price_must_be_positive(admin_client: AsyncClient):
    resp = await admin_client.post(
        "/products", json=_product_payload(sku="SKU-ZERO", price="0")
    )
    assert resp.status_code == 422

    resp_negative = await admin_client.post(
        "/products", json=_product_payload(sku="SKU-NEG", price="-5.00")
    )
    assert resp_negative.status_code == 422
