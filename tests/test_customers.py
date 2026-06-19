"""Customer management: create/update by admin+staff, admin-only delete,
delete-blocked-with-orders, and search."""
from httpx import AsyncClient


def _customer_payload(email="cust@example.com", **overrides):
    payload = {"name": "Acme Corp", "email": email, "phone": "555-1234"}
    payload.update(overrides)
    return payload


async def test_admin_and_staff_can_create_customer(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    admin_resp = await admin_client.post(
        "/customers", json=_customer_payload(email="admin-created@example.com")
    )
    assert admin_resp.status_code == 201

    staff_resp = await staff_client.post(
        "/customers", json=_customer_payload(email="staff-created@example.com")
    )
    assert staff_resp.status_code == 201


async def test_delete_blocked_with_orders_allowed_without(
    admin_client: AsyncClient, staff_client: AsyncClient
):
    customer = (
        await admin_client.post("/customers", json=_customer_payload(email="hasorders@example.com"))
    ).json()
    product = (
        await admin_client.post(
            "/products",
            json={"sku": "SKU-CUST-1", "name": "Thing", "price": "10.00", "stock_quantity": 5},
        )
    ).json()
    order_resp = await staff_client.post(
        "/orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert order_resp.status_code == 201

    blocked = await admin_client.delete(f"/customers/{customer['id']}")
    assert blocked.status_code == 409

    # A customer without orders can be deleted.
    no_orders = (
        await admin_client.post("/customers", json=_customer_payload(email="noorders@example.com"))
    ).json()
    allowed = await admin_client.delete(f"/customers/{no_orders['id']}")
    assert allowed.status_code == 204


async def test_delete_is_admin_only(admin_client: AsyncClient, staff_client: AsyncClient):
    customer = (
        await admin_client.post("/customers", json=_customer_payload(email="staffdel@example.com"))
    ).json()
    resp = await staff_client.delete(f"/customers/{customer['id']}")
    assert resp.status_code == 403


async def test_search_by_name_and_email(admin_client: AsyncClient):
    await admin_client.post(
        "/customers", json=_customer_payload(email="findme@example.com", name="Findable Inc")
    )
    await admin_client.post(
        "/customers", json=_customer_payload(email="other@example.com", name="Other Co")
    )

    by_name = await admin_client.get("/customers", params={"search": "findable"})
    emails = [c["email"] for c in by_name.json()["items"]]
    assert "findme@example.com" in emails
    assert "other@example.com" not in emails

    by_email = await admin_client.get("/customers", params={"search": "findme@"})
    emails = [c["email"] for c in by_email.json()["items"]]
    assert "findme@example.com" in emails
    assert "other@example.com" not in emails


async def test_update_customer_and_duplicate_email_conflict(admin_client: AsyncClient):
    c1 = (
        await admin_client.post("/customers", json=_customer_payload(email="c1@example.com"))
    ).json()
    c2 = (
        await admin_client.post("/customers", json=_customer_payload(email="c2@example.com"))
    ).json()

    ok = await admin_client.patch(f"/customers/{c1['id']}", json={"name": "Renamed Corp"})
    assert ok.status_code == 200
    assert ok.json()["name"] == "Renamed Corp"

    conflict = await admin_client.patch(f"/customers/{c2['id']}", json={"email": "c1@example.com"})
    assert conflict.status_code == 409


async def test_get_nonexistent_customer_404(admin_client: AsyncClient):
    resp = await admin_client.get("/customers/999999")
    assert resp.status_code == 404
