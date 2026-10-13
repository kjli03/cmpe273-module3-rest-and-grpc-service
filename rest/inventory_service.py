"""Inventory REST service for checking item availability."""

import os
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Inventory Service")

# Demo inventory. Replace with a database or inventory provider in production.
INVENTORY: dict[str, int] = {
    "item-1": 10,
    "item-2": 5,
}
INVENTORY_DELAY_SECONDS = float(os.getenv("INVENTORY_DELAY_SECONDS", "0"))


class InventoryCheckRequest(BaseModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class InventoryCheckResponse(BaseModel):
    item_id: str
    requested_quantity: int
    available_quantity: int
    available: bool


@app.post("/inventory/check", response_model=InventoryCheckResponse)
def check_inventory(request: InventoryCheckRequest) -> InventoryCheckResponse:
    """Check stock for an item and requested quantity."""
    if INVENTORY_DELAY_SECONDS < 0:
        raise RuntimeError("INVENTORY_DELAY_SECONDS cannot be negative")
    if INVENTORY_DELAY_SECONDS:
        time.sleep(INVENTORY_DELAY_SECONDS)

    if request.item_id not in INVENTORY:
        raise HTTPException(status_code=404, detail="Item not found")

    available_quantity = INVENTORY[request.item_id]
    if available_quantity < request.quantity:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Insufficient inventory",
                "item_id": request.item_id,
                "requested_quantity": request.quantity,
                "available_quantity": available_quantity,
            },
        )

    return InventoryCheckResponse(
        item_id=request.item_id,
        requested_quantity=request.quantity,
        available_quantity=available_quantity,
        available=True,
    )
