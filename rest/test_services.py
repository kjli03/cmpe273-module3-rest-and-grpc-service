"""Tests for the Order and Inventory REST services."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

import rest.inventory_service as inventory_service
import rest.order_service as order_service


@pytest.fixture(autouse=True)
def reset_inventory():
    original = inventory_service.INVENTORY.copy()
    inventory_service.INVENTORY.clear()
    inventory_service.INVENTORY.update({"item-1": 10, "item-2": 5})
    yield
    inventory_service.INVENTORY.clear()
    inventory_service.INVENTORY.update(original)


def test_inventory_check_returns_json_for_available_quantity():
    client = TestClient(inventory_service.app)

    response = client.post(
        "/inventory/check", json={"item_id": "item-1", "quantity": 3}
    )

    assert response.status_code == 200
    assert response.json() == {
        "item_id": "item-1",
        "requested_quantity": 3,
        "available_quantity": 10,
        "available": True,
    }


def test_inventory_check_returns_404_for_unknown_item():
    client = TestClient(inventory_service.app)

    response = client.post(
        "/inventory/check", json={"item_id": "missing", "quantity": 1}
    )

    assert response.status_code == 404


def test_inventory_check_returns_409_for_insufficient_quantity():
    client = TestClient(inventory_service.app)

    response = client.post(
        "/inventory/check", json={"item_id": "item-1", "quantity": 11}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["available_quantity"] == 10


def test_inventory_check_applies_configured_delay(monkeypatch):
    client = TestClient(inventory_service.app)
    delays = []
    monkeypatch.setattr(inventory_service, "INVENTORY_DELAY_SECONDS", 3.0)
    monkeypatch.setattr(inventory_service.time, "sleep", delays.append)

    response = client.post(
        "/inventory/check", json={"item_id": "item-1", "quantity": 1}
    )

    assert response.status_code == 200
    assert delays == [3.0]


def test_order_is_created_after_inventory_confirmation(monkeypatch):
    client = TestClient(order_service.app)
    captured = {}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return httpx.Response(200, json={"available": True})

    monkeypatch.setattr(order_service.httpx, "post", fake_post)
    response = client.post(
        "/orders", json={"item_id": "item-1", "quantity": 2}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert captured["url"].endswith("/inventory/check")
    assert captured["json"] == {"item_id": "item-1", "quantity": 2}
    assert captured["timeout"] == order_service.INVENTORY_TIMEOUT_SECONDS


def test_order_returns_504_when_inventory_request_times_out(monkeypatch):
    client = TestClient(order_service.app)
    monkeypatch.setattr(order_service, "INVENTORY_TIMEOUT_SECONDS", 0.01)
    calls = 0

    def delayed_then_available(url, *, json, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert timeout == 0.01
            time.sleep(timeout + 0.01)
            raise httpx.ReadTimeout("inventory timed out")
        return httpx.Response(200, json={"available": True})

    monkeypatch.setattr(order_service.httpx, "post", delayed_then_available)
    response = client.post(
        "/orders", json={"item_id": "item-1", "quantity": 2}
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "Inventory Service request timed out"

    recovered_response = client.post(
        "/orders", json={"item_id": "item-1", "quantity": 2}
    )
    assert recovered_response.status_code == 201
    assert recovered_response.json()["status"] == "accepted"


def test_order_propagates_insufficient_inventory_conflict(monkeypatch):
    client = TestClient(order_service.app)

    def conflict_post(*args, **kwargs):
        return httpx.Response(409, json={"detail": "Insufficient inventory"})

    monkeypatch.setattr(order_service.httpx, "post", conflict_post)
    response = client.post(
        "/orders", json={"item_id": "item-1", "quantity": 20}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Insufficient inventory"
