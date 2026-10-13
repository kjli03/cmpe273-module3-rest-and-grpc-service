# cmpe273-module3-rest-and-grpc-service

## Python REST services

This example contains two FastAPI services. Both APIs exchange JSON. The Order
Service checks inventory before accepting an order and applies a 2-second
timeout to its request to the Inventory Service.

### Setup

Install the dependencies:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r rest/requirements.txt
```

Start each service in a separate terminal from the project directory:

```sh
uvicorn rest.inventory_service:app --host 127.0.0.1 --port 8001
```

```sh
uvicorn rest.order_service:app --host 127.0.0.1 --port 8000
```

The Order Service defaults to `http://127.0.0.1:8001` for Inventory. Configure
the target with `INVENTORY_SERVICE_URL`; configure the request timeout in
seconds with `INVENTORY_TIMEOUT_SECONDS` (default: `2.0`). Set
`INVENTORY_DELAY_SECONDS` on the Inventory process to delay each check for
timeout demonstrations (default: `0`).

### Endpoints

#### Check inventory

`POST /inventory/check` on port `8001`

Request JSON:

```json
{"item_id": "item-1", "quantity": 3}
```

Returns `200 OK` with the requested and available quantities when stock is
sufficient. Returns `404 Not Found` for an unknown item and `409 Conflict` for
insufficient stock. Invalid or missing fields return `422 Unprocessable
Entity`.

#### Create an order

`POST /orders` on port `8000`

Request JSON:

```json
{"item_id": "item-1", "quantity": 3}
```

Returns `201 Created` with a generated `order_id` when inventory is sufficient.
The Inventory Service's `404` and `409` responses are propagated. If the
Inventory Service times out, Order returns `504 Gateway Timeout`; if it cannot
be reached, Order returns `503 Service Unavailable`; unexpected upstream
responses return `502 Bad Gateway`. Invalid input returns `422`.

The demo inventory starts with 10 units of `item-1` and 5 units of `item-2`.
It is held in memory and is not decremented when an order is accepted.

### Successful REST request and response

With both REST services running and the Inventory delay disabled, create an
order:

```sh
curl -i -X POST http://127.0.0.1:8000/orders -H 'Content-Type: application/json' -d '{"item_id":"item-1","quantity":3}'
```

Example response (`order_id` is generated per request):

```http
HTTP/1.1 201 Created
content-type: application/json

{"order_id":"<generated-uuid>","item_id":"item-1","quantity":3,"status":"accepted"}
```

### Tests

Run the tests with:

```sh
pytest
```

## Python gRPC services

The `grpc/` directory provides gRPC versions of the Inventory and Order
services. Their request/response messages and RPC methods are defined in
`grpc/inventory.proto`. The Order Service calls `CheckInventory` with a
configurable gRPC deadline (default: 2 seconds). Unknown items return
`NOT_FOUND`; insufficient stock returns `RESOURCE_EXHAUSTED`; invalid fields
return `INVALID_ARGUMENT`. The Order Service forwards Inventory's gRPC status,
including `DEADLINE_EXCEEDED` when its inventory call misses the deadline.

Install the gRPC dependencies and generate the Python bindings from the proto
file:

```sh
python -m pip install -r grpc/requirements.txt
python -m grpc_tools.protoc -I grpc --python_out=grpc --grpc_python_out=grpc grpc/inventory.proto
```

Start Inventory first, then Order, in separate terminals from the project root:

```sh
python grpc/inventory_server.py
```

```sh
python grpc/order_server.py
```

The defaults are Inventory on `127.0.0.1:50051` and Order on port `50052`.
Configure them with `INVENTORY_GRPC_PORT`, `ORDER_GRPC_PORT`,
`INVENTORY_GRPC_TARGET`, and `INVENTORY_GRPC_DEADLINE_SECONDS` respectively.
Set `INVENTORY_DELAY_SECONDS` on either Inventory process to add a temporary
delay before each inventory check; it defaults to `0`.

### Successful gRPC request and response

With the gRPC services running and the Inventory delay disabled, call Order's
`CreateOrder` RPC. `grpcurl` is an optional command-line client; its proto
descriptor is provided locally, so server reflection is not required:

```sh
grpcurl -plaintext -import-path grpc -proto inventory.proto -d '{"item_id":"item-1","quantity":3}' 127.0.0.1:50052 order_inventory.OrderService/CreateOrder
```

Example response (`orderId` is generated per request):

```json
{
	"orderId": "<generated-uuid>",
	"itemId": "item-1",
	"quantity": 3,
	"status": "accepted"
}
```

Run the gRPC integration tests from the project root with:

```sh
pytest grpc/test_grpc_services.py
```

### Timeout/deadline evidence and Order recovery

For a live REST timeout, start Inventory with a 3-second artificial delay and
Order with a 1-second upstream timeout (in separate terminals):

```sh
INVENTORY_DELAY_SECONDS=3 uvicorn rest.inventory_service:app --host 127.0.0.1 --port 8001
```

```sh
INVENTORY_TIMEOUT_SECONDS=1 uvicorn rest.order_service:app --host 127.0.0.1 --port 8000
```

While those processes are running, submit this REST order:

```sh
curl -i -X POST http://127.0.0.1:8000/orders -H 'Content-Type: application/json' -d '{"item_id":"item-1","quantity":1}'
```

Evidence of REST timeout handling is an HTTP `504 Gateway Timeout` response
with `{"detail":"Inventory Service request timed out"}`. Order catches the
HTTP client's timeout instead of terminating. For gRPC, start Inventory with
`INVENTORY_DELAY_SECONDS=3` and Order with
`INVENTORY_GRPC_DEADLINE_SECONDS=1` (in separate terminals):

```sh
INVENTORY_DELAY_SECONDS=3 python grpc/inventory_server.py
```

```sh
INVENTORY_GRPC_DEADLINE_SECONDS=1 python grpc/order_server.py
```

Repeat the `grpcurl` request above. The gRPC evidence is the status
`DEADLINE_EXCEEDED` (grpcurl reports `Code: DeadlineExceeded`); Order maps the
Inventory RPC deadline failure to the client response instead of terminating.

To verify that Order remains running, stop and restart **only Inventory** in
each example without `INVENTORY_DELAY_SECONDS`, leaving the Order process
untouched. Retry the exact REST `curl` or gRPC `grpcurl` request: it should
succeed with `201 Created` or an accepted `OrderResponse`. This demonstrates
that Order was still serving requests after the earlier failure. The automated
checks provide additional evidence: `rest/test_services.py` asserts a timeout
response followed by a successful order request, and
`grpc/test_grpc_services.py` causes a real delayed Inventory RPC to exceed its
deadline and then asserts a successful order on the same Order server. Run
them with `pytest rest/test_services.py grpc/test_grpc_services.py` after
installing both dependency sets and generating the gRPC bindings.

### REST and gRPC comparison

REST used a URL and an HTTP `POST` carrying JSON, so requests and responses were easy to inspect with `curl`. gRPC used a `.proto` contract and generated typed request/response messages, with the method invoked over HTTP/2. REST reported timeout as an HTTP `504` response, while gRPC reported the standard `DEADLINE_EXCEEDED` status. Both methods handled timeouts with an error message. Both methods also handled partial failure, demonstrated when the Order service continued to function after the Inventory service failed and restarted. 