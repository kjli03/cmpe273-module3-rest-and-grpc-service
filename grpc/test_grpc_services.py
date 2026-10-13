"""Integration tests for the gRPC Inventory and Order services."""

import sys
import threading
import time
from pathlib import Path

import grpc
import pytest
from concurrent import futures

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory_pb2
import inventory_pb2_grpc
import inventory_server
from inventory_server import INVENTORY, InventoryService
from order_server import OrderService


def start_server(servicer, register, max_workers=4):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    register(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, f"127.0.0.1:{port}"


@pytest.fixture
def grpc_services():
    INVENTORY.clear()
    INVENTORY.update({"item-1": 10, "item-2": 5})

    inventory_server, inventory_target = start_server(
        InventoryService(),
        inventory_pb2_grpc.add_InventoryServiceServicer_to_server,
    )
    order_service = OrderService(inventory_target, deadline_seconds=0.5)
    order_server, order_target = start_server(
        order_service,
        inventory_pb2_grpc.add_OrderServiceServicer_to_server,
    )
    order_channel = grpc.insecure_channel(order_target)
    inventory_channel = grpc.insecure_channel(inventory_target)
    inventory_stub = inventory_pb2_grpc.InventoryServiceStub(
        inventory_channel
    )
    order_stub = inventory_pb2_grpc.OrderServiceStub(order_channel)

    yield inventory_stub, order_stub

    order_channel.close()
    inventory_channel.close()
    order_service.inventory_channel.close()
    order_server.stop(grace=0).wait()
    inventory_server.stop(grace=0).wait()


def test_inventory_returns_availability(grpc_services):
    inventory_stub, _ = grpc_services

    response = inventory_stub.CheckInventory(
        inventory_pb2.InventoryCheckRequest(item_id="item-1", quantity=3)
    )

    assert response.available is True
    assert response.available_quantity == 10
    assert response.requested_quantity == 3


def test_inventory_reports_unknown_item_with_not_found(grpc_services):
    inventory_stub, _ = grpc_services

    with pytest.raises(grpc.RpcError) as error:
        inventory_stub.CheckInventory(
            inventory_pb2.InventoryCheckRequest(item_id="missing", quantity=1)
        )

    assert error.value.code() == grpc.StatusCode.NOT_FOUND


def test_inventory_reports_shortage_with_resource_exhausted(grpc_services):
    inventory_stub, _ = grpc_services

    with pytest.raises(grpc.RpcError) as error:
        inventory_stub.CheckInventory(
            inventory_pb2.InventoryCheckRequest(item_id="item-1", quantity=11)
        )

    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_inventory_check_applies_configured_delay(monkeypatch):
    delays = []
    monkeypatch.setattr(inventory_server, "INVENTORY_DELAY_SECONDS", 3.0)
    monkeypatch.setattr(inventory_server.time, "sleep", delays.append)

    response = InventoryService().CheckInventory(
        inventory_pb2.InventoryCheckRequest(item_id="item-1", quantity=1),
        context=None,
    )

    assert response.available is True
    assert delays == [3.0]


def test_order_is_created_when_inventory_is_available(grpc_services):
    _, order_stub = grpc_services

    response = order_stub.CreateOrder(
        inventory_pb2.OrderRequest(item_id="item-1", quantity=2)
    )

    assert response.status == "accepted"
    assert response.item_id == "item-1"
    assert response.quantity == 2
    assert response.order_id


def test_order_propagates_inventory_unavailable_status(grpc_services):
    _, order_stub = grpc_services

    with pytest.raises(grpc.RpcError) as error:
        order_stub.CreateOrder(
            inventory_pb2.OrderRequest(item_id="item-1", quantity=20)
        )

    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_order_deadline_returns_deadline_exceeded():
    delay_finished = threading.Event()

    class SlowInventory(InventoryService):
        delayed = False

        def CheckInventory(self, request, context):
            if not self.delayed:
                self.delayed = True
                time.sleep(0.15)
                delay_finished.set()
            return super().CheckInventory(request, context)

    inventory_server, inventory_target = start_server(
        SlowInventory(),
        inventory_pb2_grpc.add_InventoryServiceServicer_to_server,
    )
    order_service = OrderService(inventory_target, deadline_seconds=0.02)
    order_server, order_target = start_server(
        order_service,
        inventory_pb2_grpc.add_OrderServiceServicer_to_server,
    )
    channel = grpc.insecure_channel(order_target)
    order_stub = inventory_pb2_grpc.OrderServiceStub(channel)

    try:
        with pytest.raises(grpc.RpcError) as error:
            order_stub.CreateOrder(
                inventory_pb2.OrderRequest(item_id="item-1", quantity=1),
                timeout=1.0,
            )
        assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        assert delay_finished.wait(timeout=1.0)

        recovered_response = order_stub.CreateOrder(
            inventory_pb2.OrderRequest(item_id="item-1", quantity=1),
            timeout=1.0,
        )
        assert recovered_response.status == "accepted"
    finally:
        channel.close()
        order_service.inventory_channel.close()
        order_server.stop(grace=0).wait()
        inventory_server.stop(grace=0).wait()
