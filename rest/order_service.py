"""Order REST service that verifies stock through the Inventory Service."""

import os
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

app = FastAPI(title="Order Service")

INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL", "http://127.0.0.1:8001"
).rstrip("/")
INVENTORY_TIMEOUT_SECONDS = float(os.getenv("INVENTORY_TIMEOUT_SECONDS", "2.0"))


class OrderRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class OrderResponse(BaseModel):
    order_id: str
    item_id: str
    quantity: int
    status: str


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(request: OrderRequest) -> OrderResponse:
    """Create an order only when Inventory confirms sufficient stock."""
    try:
        inventory_response = httpx.post(
            f"{INVENTORY_SERVICE_URL}/inventory/check",
            json={"item_id": request.item_id, "quantity": request.quantity},
            timeout=INVENTORY_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Inventory Service request timed out",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory Service is unavailable",
        ) from exc

    if inventory_response.status_code in (404, 409):
        try:
            detail = inventory_response.json().get("detail", "Inventory check failed")
        except ValueError:
            detail = "Inventory check failed"
        raise HTTPException(status_code=inventory_response.status_code, detail=detail)

    if not inventory_response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected response from Inventory Service",
        )

    return OrderResponse(
        order_id=str(uuid4()),
        item_id=request.item_id,
        quantity=request.quantity,
        status="accepted",
    )
