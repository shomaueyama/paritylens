"""Modern Shop API: the "new system" in the ParityLens demo.

A rewrite of the legacy API in idiomatic FastAPI: Pydantic models for input
and output, framework-default error responses. Every difference from the
legacy API is the kind that slips in during a rewrite without anyone
deciding it, and each is marked with "Differs from legacy".
demo/README.md lists them all.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

TAX_RATE_PERCENT = 10

CATALOG: dict[str, tuple[str, int]] = {
    "A-100": ("Notebook", 105),
    "B-200": ("Ballpoint pen", 198),
    "C-300": ("Desk lamp", 2980),
}


class OrderItemRequest(BaseModel):
    sku: str
    # Differs from legacy: a rejected quantity answers 422 (FastAPI's default
    # for validation errors), where legacy answers 400.
    quantity: int = Field(ge=1)


class CreateOrderRequest(BaseModel):
    # Differs from legacy: customer_name became optional, so an order
    # without one is accepted instead of rejected.
    customer_name: str | None = None
    items: list[OrderItemRequest] = Field(min_length=1)


class OrderItem(BaseModel):
    sku: str
    name: str
    unit_price: int
    # Differs from legacy: quantity is a number, legacy sends a string.
    quantity: int
    line_total: int


class Order(BaseModel):
    id: str
    customer_name: str | None
    items: list[OrderItem]
    subtotal: int
    tax: int
    total: int
    # Differs from legacy: new field.
    currency: str = "JPY"
    status: str
    # Differs from legacy: UTC, where legacy sends JST with an offset.
    created_at: datetime


def _build_order(
    *, order_id: str, customer_name: str | None, lines: list[OrderItemRequest], created_at: datetime
) -> Order:
    # Differs from legacy: lines keep the order they were requested in.
    items = [
        OrderItem(
            sku=line.sku,
            name=CATALOG[line.sku][0],
            unit_price=CATALOG[line.sku][1],
            quantity=line.quantity,
            line_total=CATALOG[line.sku][1] * line.quantity,
        )
        for line in lines
    ]
    subtotal = sum(item.line_total for item in items)
    # Differs from legacy: tax is rounded down once, on the order subtotal.
    tax = subtotal * TAX_RATE_PERCENT // 100
    return Order(
        id=order_id,
        customer_name=customer_name,
        items=items,
        subtotal=subtotal,
        tax=tax,
        total=subtotal + tax,
        status="accepted",
        created_at=created_at,
    )


def create_app() -> FastAPI:
    """Build an app with its own in-memory store, so each test starts clean."""
    app = FastAPI(title="Modern Shop API", version="2.0.0")

    orders: dict[str, Order] = {
        # Migrated from the legacy system, so it keeps its legacy id.
        "ORD-000001": _build_order(
            order_id="ORD-000001",
            customer_name="Taro Yamada",
            lines=[OrderItemRequest(sku="C-300", quantity=1)],
            # Differs from legacy: the migration read the JST wall-clock time
            # as if it were UTC, so this is nine hours off.
            created_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        )
    }

    def find_order(order_id: str) -> Order:
        order = orders.get(order_id)
        if order is None:
            # Differs from legacy: FastAPI's default error body ({"detail": ...}).
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/orders", status_code=201)
    async def create_order(payload: CreateOrderRequest) -> Order:
        for line in payload.items:
            if line.sku not in CATALOG:
                raise HTTPException(status_code=422, detail=f"Unknown sku: {line.sku}")
        order = _build_order(
            # Differs from legacy: UUIDs instead of sequential ORD- numbers.
            order_id=str(uuid4()),
            customer_name=payload.customer_name,
            lines=payload.items,
            created_at=datetime.now(UTC),
        )
        orders[order.id] = order
        return order

    @app.get("/orders/{order_id}")
    async def get_order(order_id: str) -> Order:
        return find_order(order_id)

    @app.delete("/orders/{order_id}", status_code=204)
    async def cancel_order(order_id: str) -> Response:
        # Differs from legacy: 204 with no body, where legacy answers 200.
        find_order(order_id).status = "cancelled"
        return Response(status_code=204)

    return app


app = create_app()
