from concurrent import futures
import os
from uuid import uuid4

import grpc

import inventory_pb2
import inventory_pb2_grpc


class OrderService(inventory_pb2_grpc.OrderServiceServicer):

    def __init__(self, inventory_target: str, deadline_seconds: float) -> None:
        self.inventory_channel = grpc.insecure_channel(inventory_target)
        self.inventory_stub = inventory_pb2_grpc.InventoryServiceStub(
            self.inventory_channel
        )
        self.deadline_seconds = deadline_seconds

    def CreateOrder(self, request, context):
        if not request.item_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "item_id is required")
        if request.quantity <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be positive")

        try:
            self.inventory_stub.CheckInventory(
                inventory_pb2.InventoryCheckRequest(
                    item_id=request.item_id,
                    quantity=request.quantity,
                ),
                timeout=self.deadline_seconds,
            )
        except grpc.RpcError as exc:
            context.abort(
                exc.code() or grpc.StatusCode.UNKNOWN,
                exc.details() or "Inventory Service request failed",
            )

        return inventory_pb2.OrderResponse(
            order_id=str(uuid4()),
            item_id=request.item_id,
            quantity=request.quantity,
            status="accepted",
        )


def serve() -> None:
    order_port = int(os.getenv("ORDER_GRPC_PORT", "50052"))
    inventory_target = os.getenv("INVENTORY_GRPC_TARGET", "127.0.0.1:50051")
    deadline_seconds = float(os.getenv("INVENTORY_GRPC_DEADLINE_SECONDS", "2.0"))
    if deadline_seconds <= 0:
        raise ValueError("INVENTORY_GRPC_DEADLINE_SECONDS must be positive")

    service = OrderService(inventory_target, deadline_seconds)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inventory_pb2_grpc.add_OrderServiceServicer_to_server(service, server)
    bound_port = server.add_insecure_port(f"[::]:{order_port}")
    if not bound_port:
        service.inventory_channel.close()
        raise RuntimeError(f"Could not bind Order Service to port {order_port}")
    server.start()
    print(
        f"Order gRPC service listening on port {bound_port}; "
        f"inventory deadline is {deadline_seconds}s"
    )
    try:
        server.wait_for_termination()
    finally:
        service.inventory_channel.close()


if __name__ == "__main__":
    serve()
