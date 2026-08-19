"""Mandate #19 — profile tải canonical, chạy NGOÀI cluster.

Vì sao phải chạy ngoài cluster
------------------------------
Generator đặt trong cluster thì chính nó tranh CPU với hệ đang được đo, và ở tải cao
nó còn kích Karpenter cấp thêm node — cả hai đều phá claim requests-per-node. Đã đo
được: `load-generator` (limit 1 core) tiêu 654-706m ở 300 user, và một lần bắn tải
làm node count trôi 7 -> 10.

Đặt generator ngoài cluster loại hẳn hai vấn đề đó. Độ trễ mạng thêm vào KHÔNG làm
sai kết quả SLO, vì cả 4 cổng SLO đều đo bằng span **server-side** trong Prometheus
(xem sli_queries.json), không dùng số client-side của Locust. Số của Locust chỉ dùng
để ghi nhận offered load.

CloudFront không cache nên mọi request đều tới Envoy (kiểm chứng 30/07:
`/` trả `cache-control: private, no-cache, no-store`, `/api/products` và `/api/cart`
đều `x-cache: Miss from cloudfront`).

Quan hệ với locustfile trong cluster
------------------------------------
Trọng số task giữ ĐÚNG như
`phase3 - information/techx-corp-platform/src/load-generator/locustfile.py`
(tổng weight 32) để hai profile so sánh được:

    index 1 · browse_product 10 · get_recommendations 3 · get_product_reviews 2
    ask_product_ai_assistant 1 · get_ads 3 · view_cart 3 · add_to_cart 2
    checkout 1 · checkout_multi 1 · flood_home 5

Khác biệt duy nhất, có chủ đích:

1. Bỏ instrumentation OpenTelemetry/OpenFeature. Bên ngoài không tới được `flagd`
   (nó là service nội bộ), và span của *client* không phải nguồn SLI. **Không đụng
   flagd theo bất kỳ nghĩa nào** — chỉ là generator không tự ghi span.

2. `flood_home` là no-op. Trong cluster nó gọi
   `get_flagd_value("loadGeneratorFloodHomepage")` rồi lặp `GET /` đúng số lần đó.
   Đo trực tiếp trên flagd ngày 30/07: **giá trị = 0**, nên task này đang là no-op
   trong production. Giữ nguyên weight 5 để phân phối task không lệch.
   GIỚI HẠN ĐÃ BIẾT: nếu BTC bật flag này giữa run thì profile ngoài sẽ lệch khỏi
   trong cluster. Phải kiểm lại giá trị flag trước mỗi arm.
"""

import json
import os
import random
import uuid
from pathlib import Path

from locust import HttpUser, between, task

# Cùng danh sách với locustfile trong cluster.
categories = [
    "binoculars",
    "telescopes",
    "accessories",
    "assembly",
    "travel",
    "books",
    None,
]

products = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
    "HQTGWGPNH4",
]

# people.json lấy nguyên từ cây nguồn load-generator để payload checkout khớp.
# Tính fallback LAZY: `os.environ.get(k, default)` sẽ dựng default ngay cả khi env
# đã có, và `parents[2]` không tồn tại khi file nằm ở /bench trong container.
_people_env = os.environ.get("PEOPLE_JSON")
if _people_env:
    _PEOPLE_PATH = Path(_people_env)
else:
    _PEOPLE_PATH = (
        Path(__file__).resolve().parents[2]
        / "phase3 - information/techx-corp-platform/src/load-generator/people.json"
    )
people = json.loads(_PEOPLE_PATH.read_text(encoding="utf-8"))


class WebsiteUser(HttpUser):
    wait_time = between(1, 10)

    @task(1)
    def index(self):
        self.client.get("/", name="/")

    @task(10)
    def browse_product(self):
        product = random.choice(products)
        # name= gộp theo route để percentile không bị tách theo từng product id.
        self.client.get(f"/api/products/{product}", name="/api/products/[id]")

    @task(3)
    def get_recommendations(self):
        product = random.choice(products)
        self.client.get(
            "/api/recommendations",
            params={"productIds": [product]},
            name="/api/recommendations",
        )

    @task(2)
    def get_product_reviews(self):
        product = random.choice(products)
        self.client.get(
            f"/api/product-reviews/{product}", name="/api/product-reviews/[id]"
        )

    @task(1)
    def ask_product_ai_assistant(self):
        # Đường này gọi Bedrock thật -> có chi phí. Xem README mục chi phí.
        product = random.choice(products)
        self.client.post(
            f"/api/product-ask-ai-assistant/{product}",
            json={"question": "Can you summarize the product reviews?"},
            name="/api/product-ask-ai-assistant/[id]",
        )

    @task(3)
    def get_ads(self):
        category = random.choice(categories)
        self.client.get(
            "/api/data/", params={"contextKeys": [category]}, name="/api/data/"
        )

    @task(3)
    def view_cart(self):
        self.client.get("/api/cart", name="/api/cart")

    @task(2)
    def add_to_cart(self, user=""):
        if user == "":
            user = str(uuid.uuid1())
        product = random.choice(products)
        quantity = random.choice([1, 2, 3, 4, 5, 10])
        self.client.get(f"/api/products/{product}", name="/api/products/[id]")
        self.client.post(
            "/api/cart",
            json={
                "item": {"productId": product, "quantity": quantity},
                "userId": user,
            },
            name="/api/cart",
        )

    @task(1)
    def checkout(self):
        # Tạo ĐƠN THẬT trong RDS + MSK. Xem README mục tác dụng phụ.
        user = str(uuid.uuid1())
        self.add_to_cart(user=user)
        checkout_person = dict(random.choice(people))
        checkout_person["userId"] = user
        self.client.post("/api/checkout", json=checkout_person, name="/api/checkout")

    @task(1)
    def checkout_multi(self):
        user = str(uuid.uuid1())
        for _ in range(random.choice([2, 3, 4])):
            self.add_to_cart(user=user)
        checkout_person = dict(random.choice(people))
        checkout_person["userId"] = user
        self.client.post("/api/checkout", json=checkout_person, name="/api/checkout")

    @task(5)
    def flood_home(self):
        """No-op: flag flagd `loadGeneratorFloodHomepage` = 0 (đo 30/07/2026).

        Giữ weight 5 để phân phối task khớp locustfile trong cluster. Không đọc
        flagd từ ngoài vì flagd là service nội bộ — và không được đụng flagd.
        """
        return
