"""Legacy Shop API: the "old system" in the ParityLens demo.

Written the way a long-lived internal API tends to look: request bodies are
plain dicts checked by hand, responses are assembled field by field, and a
few quirks have become part of the contract because clients depend on them.

The quirks that matter for the demo are marked with "Legacy behaviour".
demo/README.md lists how each one differs from the modern API.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

JST = timezone(timedelta(hours=9))
TAX_RATE_PERCENT = 10

CATALOG: dict[str, tuple[str, int]] = {
    "A-100": ("Notebook", 105),
    "B-200": ("Ballpoint pen", 198),
    "C-300": ("Desk lamp", 2980),
}


@dataclass
class OrderLine:
    sku: str
    quantity: int


@dataclass
class Order:
    id: str
    customer_name: str
    lines: list[OrderLine]
    status: str
    created_at: datetime


class ValidationError(Exception):
    pass


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def _parse_lines(raw_items: Any) -> list[OrderLine]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("items must be a non-empty array")

    lines: list[OrderLine] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValidationError("each item must be an object")
        sku = raw.get("sku")
        quantity = raw.get("quantity")
        if sku not in CATALOG:
            raise ValidationError(f"unknown sku: {sku}")
        # bool is a subclass of int in Python, so it has to be excluded by hand.
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValidationError("quantity must be a positive integer")
        lines.append(OrderLine(sku=sku, quantity=quantity))
    return lines


def _render(order: Order) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    subtotal = 0
    tax = 0
    # Legacy behaviour: lines are always returned in SKU order.
    for line in sorted(order.lines, key=lambda item: item.sku):
        name, unit_price = CATALOG[line.sku]
        line_total = unit_price * line.quantity
        subtotal += line_total
        # Legacy behaviour: tax is rounded down per line, then summed.
        tax += line_total * TAX_RATE_PERCENT // 100
        items.append(
            {
                "sku": line.sku,
                "name": name,
                "unit_price": unit_price,
                # Legacy behaviour: quantity has always gone out as a string.
                "quantity": str(line.quantity),
                "line_total": line_total,
            }
        )
    return {
        "id": order.id,
        "customer_name": order.customer_name,
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total": subtotal + tax,
        "status": order.status,
        # Legacy behaviour: timestamps are local time (JST) with an offset.
        "created_at": order.created_at.astimezone(JST).isoformat(timespec="seconds"),
    }


def create_app() -> FastAPI:
    """Build an app with its own in-memory store, so each test starts clean."""
    app = FastAPI(title="Legacy Shop API", version="1.0.0")

    orders: dict[str, Order] = {
        "ORD-000001": Order(
            id="ORD-000001",
            customer_name="Taro Yamada",
            lines=[OrderLine(sku="C-300", quantity=1)],
            status="accepted",
            created_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=JST),
        )
    }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/orders")
    async def create_order(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "INVALID_JSON", "request body must be JSON")
        if not isinstance(body, dict):
            return _error(400, "VALIDATION_ERROR", "request body must be an object")

        customer_name = body.get("customer_name")
        # Legacy behaviour: customer_name is required.
        if not isinstance(customer_name, str) or not customer_name.strip():
            return _error(400, "VALIDATION_ERROR", "customer_name is required")
        try:
            lines = _parse_lines(body.get("items"))
        except ValidationError as exc:
            return _error(400, "VALIDATION_ERROR", str(exc))

        order = Order(
            id=f"ORD-{len(orders) + 1:06d}",
            customer_name=customer_name,
            lines=lines,
            status="accepted",
            created_at=datetime.now(JST),
        )
        orders[order.id] = order
        return JSONResponse(status_code=201, content=_render(order))

    @app.get("/orders/{order_id}")
    async def get_order(order_id: str) -> JSONResponse:
        order = orders.get(order_id)
        if order is None:
            return _error(404, "NOT_FOUND", f"order {order_id} not found")
        return JSONResponse(content=_render(order))

    @app.delete("/orders/{order_id}")
    async def cancel_order(order_id: str) -> JSONResponse:
        order = orders.get(order_id)
        if order is None:
            return _error(404, "NOT_FOUND", f"order {order_id} not found")
        order.status = "cancelled"
        # Legacy behaviour: cancelling answers 200 with a small body.
        return JSONResponse(content={"id": order.id, "status": order.status})

    return app


app = create_app()
