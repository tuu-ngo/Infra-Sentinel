# tools/cart_tool.py
"""Cart tools — add, view, check items. All return normalized JSON.
Cart policy: only add (with confirmation) and view are allowed. No remove/update/checkout."""

import json
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.guardrails.confirmation import request_confirmation

from src.tools.service_config import CART_ADDR, CATALOG_ADDR

CATALOG_TIMEOUT_SECONDS = 1.5
CART_TIMEOUT_SECONDS = 3.0


@tool
def check_cart_item_tool(user_id: str, product_id: str) -> str:
    """
    Hữu ích khi người dùng muốn kiểm tra xem một sản phẩm có đang có trong giỏ hàng hay không.
    Trả về kết quả rõ ràng để agent có thể dùng trực tiếp mà không cần suy đoán.
    Returns JSON: {"status", "found", "product_id", "quantity"}
    """
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    try:
        request = demo_pb2.GetCartRequest(user_id=user_id)
        response = stub.GetCart(request)

        for item in getattr(response, "items", []) or []:
            if getattr(item, "product_id", "") == product_id:
                return json.dumps({
                    "status": "success",
                    "found": True,
                    "product_id": product_id,
                    "quantity": item.quantity,
                })

        return json.dumps({
            "status": "success",
            "found": False,
            "product_id": product_id,
            "quantity": 0,
        })
    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "error": f"gRPC error: {e.details()}",
            "found": False,
            "product_id": product_id,
            "quantity": 0,
        })
    finally:
        channel.close()


@tool
def add_to_cart_tool(user_id: str, product_id: str, quantity: int) -> str:
    """
    Hữu ích khi người dùng yêu cầu thêm sản phẩm vào giỏ hàng của họ.
    Yêu cầu đầu vào: user_id, product_id, và quantity (số lượng).
    Returns JSON: {"status": "pending"|"success"|"error", ...}
    """
    if int(quantity) <= 0:
        return json.dumps({
            "status": "error",
            "error": "Quantity must be greater than 0.",
        })

    confirmation = request_confirmation(
        user_id=user_id,
        action="AddItem",
        action_params={"product_id": product_id, "quantity": quantity},
    )

    if confirmation.status == "DENIED":
        return json.dumps({
            "status": "error",
            "error": "Add to cart action was denied by policy.",
        })

    if confirmation.status == "PENDING":
        product_name = product_id
        try:
            cat_channel = grpc.insecure_channel(CATALOG_ADDR)
            cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_channel)
            p_req = demo_pb2.GetProductRequest(id=product_id)
            p_res = cat_stub.GetProduct(p_req, timeout=CATALOG_TIMEOUT_SECONDS)
            if p_res.name:
                product_name = p_res.name
            cat_channel.close()
        except Exception:
            pass

        if product_name == product_id:
            try:
                from src.tools.search_product.flow1.sql_executor import SQLQueryExecutor
                executor = SQLQueryExecutor()
                rows = executor.execute(f"SELECT name FROM products WHERE id = '{product_id}'")
                if rows and rows[0].get("name"):
                    product_name = rows[0]["name"]
            except Exception:
                pass

        return json.dumps({
            "status": "pending",
            # FIX #6: Use Vietnamese-friendly confirmation message
            "message": f"Bạn có muốn thêm {quantity} '{product_name}' vào giỏ hàng không?",
            "token": confirmation.confirmation_token,
            "action_data": {
                "user_id": user_id,
                "action": "AddItem",
                "params": {"product_id": product_id, "quantity": quantity},
            },
        })

    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    try:
        cart_item = demo_pb2.CartItem(product_id=product_id, quantity=int(quantity))
        request = demo_pb2.AddItemRequest(user_id=user_id, item=cart_item)
        stub.AddItem(request, timeout=CART_TIMEOUT_SECONDS)
        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "quantity": quantity,
            "message": f"Successfully added {quantity} of '{product_id}' to cart.",
        })
    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "error": f"gRPC error: {e.details()}",
        })
    finally:
        channel.close()


def _price(units: int, nanos: int) -> float:
    """
    Convert price_units + price_nanos to USD with cent precision.
    price_nanos is billionths of a dollar: 80_000_000 nanos = $0.08
    Uses integer arithmetic to avoid float rounding.
    """
    u = int(units or 0)
    n = int(nanos or 0)
    cents_total = u * 100 + round(n / 10_000_000)
    return cents_total / 100


@tool
def get_cart_tool(user_id: str) -> str:
    """
    Hữu ích khi người dùng muốn xem danh sách các sản phẩm đang có trong giỏ hàng của họ.
    Đầu vào cần thiết: user_id.
    Returns JSON: {"status", "user_id", "items": [{"product_id","product_name","quantity","price"}], "total_items"}
    """
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)

    try:
        request = demo_pb2.GetCartRequest(user_id=user_id)
        response = stub.GetCart(request)

        if not response.items:
            return json.dumps({
                "status": "empty",
                "user_id": user_id,
                "items": [],
                "total_items": 0,
            })

        items = []
        product_metadata = {}
        
        # Try to resolve product names and prices via Catalog Service
        if response.items:
            cat_channel = grpc.insecure_channel(CATALOG_ADDR)
            try:
                cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_channel)
                for item in response.items:
                    try:
                        p_req = demo_pb2.GetProductRequest(id=item.product_id)
                        p_res = cat_stub.GetProduct(p_req)
                        product_metadata[item.product_id] = {
                            "name": p_res.name,
                            "price_units": getattr(p_res, "price_units", 0) or 0,
                            "price_nanos": getattr(p_res, "price_nanos", 0) or 0,
                        }
                    except Exception as e:
                        pass
            finally:
                cat_channel.close()

        # Fallback to database if gRPC failed
        if not product_metadata or not all(product_metadata.get(item.product_id) for item in response.items):
            try:
                from src.tools.search_product.flow1.sql_executor import SQLQueryExecutor
                executor = SQLQueryExecutor()
                product_ids = [item.product_id for item in response.items]
                if product_ids:
                    ids_str = ",".join([f"'{pid}'" for pid in product_ids])
                    rows = executor.execute(
                        f"SELECT id, name, price_units, price_nanos FROM products WHERE id IN ({ids_str})"
                    )
                    for row in rows:
                        product_metadata[row["id"]] = {
                            "name": row["name"],
                            "price_units": row.get("price_units", 0) or 0,
                            "price_nanos": row.get("price_nanos", 0) or 0,
                        }
            except Exception:
                pass

        for item in response.items:
            metadata = product_metadata.get(item.product_id, {})
            items.append({
                "product_id": item.product_id,
                "product_name": metadata.get("name", "Unknown Product"),
                "quantity": item.quantity,
                "price": _price(metadata.get("price_units", 0), metadata.get("price_nanos", 0)),
            })

        return json.dumps({
            "status": "success",
            "user_id": user_id,
            "items": items,
            "total_items": len(items),
        })

    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "user_id": user_id,
            "error": f"gRPC error: {e.details()}",
            "items": [],
            "total_items": 0,
        })
    finally:
        channel.close()
