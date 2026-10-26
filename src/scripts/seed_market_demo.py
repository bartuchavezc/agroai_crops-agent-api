"""Red Km 0 demo data, through the real API: the six farms around City Bell from the design, each with a lot or
two published, a few buyer orders and today's pickup route. For local development only: it signs accounts up,
so the API must run with ALLOW_PUBLIC_SIGNUP=true, and the admin email must be in PLATFORM_ADMIN_EMAILS.

    uv run python -m src.scripts.seed_market_demo --api http://localhost:8000/api/v1 --admin-email admin@example.com

Every producer logs in with <id>@redkm0.example.com / demo-pass-1 (Marta of Los Aromos: aromos@redkm0.example.com)."""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

PASSWORD = "demo-pass-1"
FARMS = [
    ("aromos", "Los Aromos", "Villa Elisa", -34.8530, -58.0790, "Marta"),
    ("ceibo", "El Ceibo", "Villa Elisa", -34.8462, -58.0660, "Julián"),
    ("mancha", "La Mancha Verde", "Gonnet", -34.8865, -58.0165, "Rocío"),
    ("rosa", "Quinta Doña Rosa", "Arturo Seguí", -34.8975, -58.1060, "Rosa"),
    ("arroyo", "Huerta del Arroyo", "Villa Castells", -34.8610, -58.0020, "Tomás"),
    ("nandu", "Patio Ñandú", "City Bell", -34.8990, -58.0300, "Lucía"),
]
# (farm, crop search, title, category, price, stock, capacity, weeks, available in days or None)
LISTINGS = [
    ("aromos", "Rúcula", "Rúcula", "hojas", 6.5, 18, 25, 10, None),
    ("aromos", "albahaca", "Albahaca", "aromaticas", 14, 4, 6, 8, None),
    ("ceibo", "tomate", "Tomate cherry", "frutos", 8, 22, 30, 12, 6),
    ("mancha", "lechuga", "Lechuga mantecosa", "hojas", 4.2, 40, 60, 16, None),
    ("mancha", "remolacha", "Remolacha", "raices", 4.5, 15, 25, 10, 8),
    ("rosa", "acelga", "Acelga", "hojas", 3.5, 35, 50, 20, None),
    ("arroyo", "zanahoria", "Zanahoria baby", "raices", 5.8, 0, 20, 6, 15),
    ("arroyo", "Rúcula", "Rúcula", "hojas", 6.5, 12, 20, 10, None),
    ("nandu", "perejil", "Perejil", "aromaticas", 12, 3, 5, 8, None),
]
STOPS = [("ceibo", "09:50"), ("aromos", "10:15"), ("rosa", "10:40")]


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None, token: str | None = None, ok=(200, 201, 204)):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code in ok:
                return None
            raise SystemExit(f"{method} {path} -> {error.code}: {error.read().decode()}") from None

    def session(self, email: str, first_name: str) -> str:
        try:
            return self.call("POST", "/auth/login", {"email": email, "password": PASSWORD})["access_token"]
        except SystemExit:
            body = {"email": email, "password": PASSWORD, "first_name": first_name, "country": "AR"}
            token = self.call("POST", "/auth/signup", body)["access_token"]
            # the onboarding questionnaire, so the demo login lands straight in the app
            self.call("POST", "/auth/enroll", {"form": {f"q{i}": "B" for i in range(1, 11)}}, token)
            return token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--admin-email", required=True)
    args = parser.parse_args()
    api = Api(args.api)
    today = date.today()

    producers, tokens = {}, {}
    for key, name, barrio, lat, lng, person in FARMS:
        token = api.session(f"{key}@redkm0.example.com", person)
        tokens[key] = token
        me = api.call("GET", "/market/me", token=token)
        if me is None:
            field = api.call("POST", "/farm-management/fields", {
                "name": name, "city": barrio, "latitude": lat, "longitude": lng,
            }, token)
            me = api.call("PUT", "/market/me", {"field_id": field["id"], "display_name": name, "barrio": barrio}, token)
        producers[key] = me
        print(f"producer {name}: {key}@redkm0.example.com")

    for key, crop_q, title, category, price, stock, capacity, weeks, in_days in LISTINGS:
        token = tokens[key]
        if any(item["title"] == title for item in api.call("GET", "/market/listings", token=token)):
            continue
        crops = api.call("GET", f"/farm-management/crop-masters?q={urllib.parse.quote(crop_q)}", token=token)
        lot = api.call("POST", "/farm-management/lots", {
            "field_id": producers[key]["field_id"], "crop_master_id": crops[0]["id"],
            "status": "growing" if in_days else "harvesting", "planting_date": str(today - timedelta(days=50)),
            "expected_price": price, "expected_yield_kg": capacity * weeks,
        }, token)
        api.call("POST", "/market/listings", {
            "lot_id": lot["id"], "title": title, "category": category, "price_per_kg": price,
            "weekly_capacity_kg": capacity, "weeks": weeks, "stock_kg": stock,
            "available_from": str(today + timedelta(days=in_days)) if in_days else None,
        }, token)
        # what keeps the traceability up: something in the bitácora lately
        api.call("POST", "/farm-management/events", {
            "field_id": producers[key]["field_id"], "lot_ids": [lot["id"]], "type": "irrigation",
        }, token)
    api.call("PUT", "/market/me/plan", {"plan": "free"}, tokens["aromos"])

    catalog = api.call("GET", "/market/public/catalog")
    by_title = {}
    for item in catalog["listings"]:
        by_title.setdefault((item["producer_id"], item["title"]), item["id"])
    aromos = producers["aromos"]["id"]
    rucula, albahaca = by_title[(aromos, "Rúcula")], by_title[(aromos, "Albahaca")]
    buyers = [
        ("Bodegón La Esquina", "restaurante", [(rucula, 5), (albahaca, 1)]),
        ("Verdulería Raíz", "verduleria", [(rucula, 5), (albahaca, 2)]),
        ("Hotel Gonnet", "hotel", [(rucula, 5)]),
    ]
    for name, kind, items in buyers:
        api.call("POST", "/market/public/orders", {
            "buyer": {"name": name, "email": f"{kind}@redkm0.example.com", "kind": kind, "address": "City Bell"},
            "items": [{"listing_id": i, "kg": kg} for i, kg in items],
        })
    orders = api.call("GET", "/market/orders?scope=active", token=tokens["aromos"])
    if len(orders) >= 2:
        api.call("POST", f"/market/orders/{orders[1]['id']}/accept", token=tokens["aromos"], ok=(400,))
        api.call("PUT", f"/market/orders/{orders[1]['id']}/packed",
                 {"packed": [orders[1]["boxes"][0]["code"]]}, tokens["aromos"], ok=(400,))

    admin = api.session(args.admin_email, "Admin")
    pickup = orders[0]["pickup_date"] if orders else str(today)
    if not api.call("GET", f"/market/admin/routes?since={pickup}", token=admin):
        api.call("POST", "/market/admin/routes", {
            "route_date": pickup, "name": "Ruta norte", "driver_name": "Lucas", "hub_name": "Hub Villa Elisa",
            "hub_eta": "11:20", "deliveries_from": "12:00",
            "stops": [{"producer_id": producers[k]["id"], "eta": eta} for k, eta in STOPS],
        }, admin)
    api.call("PUT", f"/market/admin/producers/{aromos}/seal", {"seal_until": str(today + timedelta(days=180))}, admin)
    print(f"catalog: {len(catalog['producers'])} producers, {len(catalog['listings'])} listings")


if __name__ == "__main__":
    main()
