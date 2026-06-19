"""Order creation, stock mutation atomicity, status transitions, cancellation
restock, and listing filters."""
from decimal import Decimal

from httpx import AsyncClient


async def _make_customer(admin_client: AsyncClient, email="orders-cust@example.com") -> dict:
    resp = await admin_client.post(
        "/customers", json={"name": "Order Customer", "email": email, "phone": None}
    )
    return resp.json()


async def _make_product(admin_client: AsyncClient, sku, price, stock) -> dict:
    resp = await admin_client.post(
        "/products",
        json={"sku": sku, "name": f"Product {sku}", "price": str(price), "stock_quantity": stock},
    )
    return resp.json()


async def _create_order(staff_client: AsyncClient, customer_id: int, items: list[dict]):
    """items: list of {"product_id": int, "quantity": int}."""
    return await staff_client.post(
        "/orders", json={"customer_id": customer_id, "items": items}
    )


async def _create_single_item_order(
    staff_client: AsyncClient, customer_id: int, product_id: int, quantity: int = 1
):
    return await _create_order(
        staff_client, customer_id, [{"product_id": product_id, "quantity": quantity}]
    )


async def test_order_creation_decrements_stock_and_computes_total(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client)
    p1 = await _make_product(admin_client, "ORD-P1", "10.00", 10)
    p2 = await _make_product(admin_client, "ORD-P2", "5.50", 20)

    resp = await _create_order(
        staff_client,
        customer["id"],
        [
            {"product_id": p1["id"], "quantity": 2},
            {"product_id": p2["id"], "quantity": 3},
        ],
    )
    assert resp.status_code == 201
    order = resp.json()
    assert order["status"] == "pending"
    # 2 * 10.00 + 3 * 5.50 = 20.00 + 16.50 = 36.50
    assert Decimal(str(order["total_amount"])) == Decimal("36.50")

    for item in order["items"]:
        if item["product_id"] == p1["id"]:
            assert Decimal(str(item["unit_price"])) == Decimal("10.00")
            assert item["quantity"] == 2
        else:
            assert Decimal(str(item["unit_price"])) == Decimal("5.50")
            assert item["quantity"] == 3

    p1_after = (await admin_client.get(f"/products/{p1['id']}")).json()
    p2_after = (await admin_client.get(f"/products/{p2['id']}")).json()
    assert p1_after["stock_quantity"] == 8
    assert p2_after["stock_quantity"] == 17


async def test_unit_price_snapshot_unaffected_by_later_price_change(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="snapshot@example.com")
    product = await _make_product(admin_client, "SNAP-1", "20.00", 10)

    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"])
    ).json()
    assert Decimal(str(order["items"][0]["unit_price"])) == Decimal("20.00")

    await admin_client.patch(f"/products/{product['id']}", json={"price": "999.00"})

    refetched = (await staff_client.get(f"/orders/{order['id']}")).json()
    assert Decimal(str(refetched["items"][0]["unit_price"])) == Decimal("20.00")
    assert Decimal(str(refetched["total_amount"])) == Decimal("20.00")


async def test_insufficient_stock_returns_409_and_no_partial_decrement(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="insufficient@example.com")
    plentiful = await _make_product(admin_client, "STOCK-OK", "1.00", 100)
    scarce = await _make_product(admin_client, "STOCK-LOW", "1.00", 1)

    resp = await _create_order(
        staff_client,
        customer["id"],
        [
            {"product_id": plentiful["id"], "quantity": 5},
            {"product_id": scarce["id"], "quantity": 5},
        ],
    )
    assert resp.status_code == 409

    # Neither item's stock should have moved -- not even the one with
    # sufficient stock -- since validation happens before any mutation.
    plentiful_after = (await admin_client.get(f"/products/{plentiful['id']}")).json()
    scarce_after = (await admin_client.get(f"/products/{scarce['id']}")).json()
    assert plentiful_after["stock_quantity"] == 100
    assert scarce_after["stock_quantity"] == 1


async def test_nonexistent_customer_returns_404(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    product = await _make_product(admin_client, "NOCUST-1", "1.00", 10)
    resp = await _create_order(staff_client, 999999, [{"product_id": product["id"], "quantity": 1}])
    assert resp.status_code == 404


async def test_nonexistent_product_returns_404(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="nocust2@example.com")
    resp = await _create_single_item_order(staff_client, customer["id"], 999999)
    assert resp.status_code == 404


async def test_inactive_product_returns_404(admin_client: AsyncClient, staff_client: AsyncClient):
    customer = await _make_customer(admin_client, email="inactive@example.com")
    product = await _make_product(admin_client, "INACTIVE-1", "1.00", 10)
    await admin_client.delete(f"/products/{product['id']}")

    resp = await _create_order(
        staff_client, customer["id"], [{"product_id": product["id"], "quantity": 1}]
    )
    assert resp.status_code == 404


async def test_duplicate_product_id_in_one_request_returns_422(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="dupeitem@example.com")
    product = await _make_product(admin_client, "DUPE-1", "1.00", 10)

    resp = await _create_order(
        staff_client,
        customer["id"],
        [
            {"product_id": product["id"], "quantity": 1},
            {"product_id": product["id"], "quantity": 2},
        ],
    )
    assert resp.status_code == 422


async def test_valid_status_transitions_pending_paid_shipped(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="transitions@example.com")
    product = await _make_product(admin_client, "TRANS-1", "1.00", 10)
    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"])
    ).json()

    to_paid = await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "paid"})
    assert to_paid.status_code == 200
    assert to_paid.json()["status"] == "paid"

    to_shipped = await staff_client.patch(
        f"/orders/{order['id']}/status", json={"status": "shipped"}
    )
    assert to_shipped.status_code == 200
    assert to_shipped.json()["status"] == "shipped"


async def test_invalid_transition_pending_to_shipped_returns_409(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="badtransition@example.com")
    product = await _make_product(admin_client, "BADTRANS-1", "1.00", 10)
    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"])
    ).json()

    resp = await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "shipped"})
    assert resp.status_code == 409


async def test_no_transition_out_of_shipped_or_cancelled(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="terminal@example.com")
    product = await _make_product(admin_client, "TERMINAL-1", "1.00", 10)
    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"])
    ).json()
    await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "paid"})
    await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "shipped"})

    resp = await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "cancelled"})
    assert resp.status_code == 409

    # And separately: a cancelled order can't transition anywhere either.
    customer2 = await _make_customer(admin_client, email="terminal2@example.com")
    product2 = await _make_product(admin_client, "TERMINAL-2", "1.00", 10)
    order2 = (
        await _create_order(
            staff_client, customer2["id"], [{"product_id": product2["id"], "quantity": 1}]
        )
    ).json()
    await staff_client.patch(f"/orders/{order2['id']}/status", json={"status": "cancelled"})
    resp2 = await staff_client.patch(f"/orders/{order2['id']}/status", json={"status": "paid"})
    assert resp2.status_code == 409


async def test_cancel_pending_order_restocks_items(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="restock-pending@example.com")
    product = await _make_product(admin_client, "RESTOCK-1", "1.00", 10)
    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"], quantity=4)
    ).json()

    after_order = (await admin_client.get(f"/products/{product['id']}")).json()
    assert after_order["stock_quantity"] == 6

    cancel = await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "cancelled"})
    assert cancel.status_code == 200

    after_cancel = (await admin_client.get(f"/products/{product['id']}")).json()
    assert after_cancel["stock_quantity"] == 10


async def test_cancel_paid_order_restocks_items(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = await _make_customer(admin_client, email="restock-paid@example.com")
    product = await _make_product(admin_client, "RESTOCK-2", "1.00", 10)
    order = (
        await _create_single_item_order(staff_client, customer["id"], product["id"], quantity=3)
    ).json()
    await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "paid"})

    cancel = await staff_client.patch(f"/orders/{order['id']}/status", json={"status": "cancelled"})
    assert cancel.status_code == 200

    after_cancel = (await admin_client.get(f"/products/{product['id']}")).json()
    assert after_cancel["stock_quantity"] == 10


async def test_list_orders_filter_by_status_and_customer_id(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer_a = await _make_customer(admin_client, email="filter-a@example.com")
    customer_b = await _make_customer(admin_client, email="filter-b@example.com")
    product = await _make_product(admin_client, "FILTER-1", "1.00", 100)

    order_a = (
        await _create_order(
            staff_client, customer_a["id"], [{"product_id": product["id"], "quantity": 1}]
        )
    ).json()
    await _create_order(
        staff_client, customer_b["id"], [{"product_id": product["id"], "quantity": 1}]
    )
    await staff_client.patch(f"/orders/{order_a['id']}/status", json={"status": "paid"})

    by_customer = await staff_client.get("/orders", params={"customer_id": customer_a["id"]})
    body = by_customer.json()
    assert all(o["customer_id"] == customer_a["id"] for o in body["items"])
    assert len(body["items"]) == 1

    by_status = await staff_client.get("/orders", params={"status_filter": "paid"})
    body = by_status.json()
    assert all(o["status"] == "paid" for o in body["items"])
    assert any(o["id"] == order_a["id"] for o in body["items"])


async def test_get_nonexistent_order_returns_404(staff_client: AsyncClient):
    resp = await staff_client.get("/orders/999999")
    assert resp.status_code == 404
