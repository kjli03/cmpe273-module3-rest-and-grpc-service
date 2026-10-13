from concurrent import futures
import os
import time

import grpc

import inventory_pb2
import inventory_pb2_grpc

INVENTORY: dict[str, int] = {"item-1": 10, "item-2": 5}
INVENTORY_DELAY_SECONDS = float(os.getenv("INVENTORY_DELAY_SECONDS", "0"))


class InventoryService(inventory_pb2_grpc.InventoryServiceServicer):

    def CheckInventory(self, request, context):
        if INVENTORY_DELAY_SECONDS < 0:
            context.abort(
                grpc.StatusCode.INTERNAL,
                "INVENTORY_DELAY_SECONDS cannot be negative",
            )
        if INVENTORY_DELAY_SECONDS:
            time.sleep(INVENTORY_DELAY_SECONDS)

        if not request.item_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "item_id is required")
        if request.quantity <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be positive")
        if request.item_id not in INVENTORY:
            context.abort(grpc.StatusCode.NOT_FOUND, "item not found")

        available_quantity = INVENTORY[request.item_id]
        if available_quantity < request.quantity:
            context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                f"Insufficient inventory: requested {request.quantity}, "
                f"available {available_quantity}",
            )

        return inventory_pb2.InventoryCheckResponse(
            item_id=request.item_id,
            requested_quantity=request.quantity,
            available_quantity=available_quantity,
            available=True,
        )


def serve() -> None:
    port = int(os.getenv("INVENTORY_GRPC_PORT", "50051"))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(
        InventoryService(), server
    )
    bound_port = server.add_insecure_port(f"[::]:{port}")
    if not bound_port:
        raise RuntimeError(f"Could not bind Inventory Service to port {port}")
    server.start()
    print(f"Inventory gRPC service listening on port {bound_port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
