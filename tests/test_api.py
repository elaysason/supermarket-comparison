from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api import main as api

SHUFERSAL = "7290027600007"
RAMI_LEVI = "7290058140886"


class FakeRepository:
    def get_product_names(self, barcodes):
        return {barcode: f"Product {barcode}" for barcode in barcodes}

    def get_compare_chain_statuses(self):
        updated_at = datetime.now(timezone.utc)
        return {
            SHUFERSAL: {
                "chain_name": "Shufersal",
                "source_file_date": updated_at,
            },
            RAMI_LEVI: {
                "chain_name": "Rami Levi",
                "source_file_date": updated_at,
            },
        }

    def resolve_barcodes_by_names(self, source_chain_code, item_names):
        return {}

    def get_competitor_prices(self, source_chain_code, barcodes, chain_codes):
        assert source_chain_code == SHUFERSAL
        assert chain_codes == [RAMI_LEVI]
        prices = {"111": 10.0, "222": 3.85}
        return {
            RAMI_LEVI: {
                "chain_name": "Rami Levi",
                "items": {
                    barcode: {
                        "product_name": f"Product {barcode}",
                        "price": prices[barcode],
                    }
                    for barcode in barcodes
                },
            }
        }

    def get_source_prices(self, source_chain_code, barcodes):
        assert source_chain_code == SHUFERSAL
        prices = {"111": 13.9, "222": 3.1}
        return {
            SHUFERSAL: {
                "chain_name": "Shufersal",
                "items": {
                    barcode: {
                        "product_name": f"Product {barcode}",
                        "price": prices[barcode],
                    }
                    for barcode in barcodes
                },
            }
        }

    def get_shipping_costs(self, chain_codes):
        costs = {
            SHUFERSAL: [
                {
                    "option_type": "delivery",
                    "fee": 35.9,
                    "notes": "Delivery",
                    "min_order": None,
                    "free_above": None,
                }
            ],
            RAMI_LEVI: [
                {
                    "option_type": "delivery",
                    "fee": 35.9,
                    "notes": "Delivery",
                    "min_order": None,
                    "free_above": None,
                }
            ],
        }
        return {chain_code: costs[chain_code] for chain_code in chain_codes}


def client(monkeypatch):
    monkeypatch.setattr(api, "SupabaseRepository", FakeRepository)
    monkeypatch.setattr(api, "ALLOWED_EXTENSION_ORIGINS", {"chrome-extension://test"})
    return TestClient(api.app)


def test_compare_includes_quantities_and_delivery_fees(monkeypatch):
    response = client(monkeypatch).post(
        "/api/compare",
        headers={"Origin": "chrome-extension://test"},
        json={
            "source_chain_code": SHUFERSAL,
            "barcodes": ["111", "222"],
            "quantities": {"111": 1, "222": 2},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation_status"] == "available"
    assert body["coverage_status"] == "full"
    assert body["comparison_option_type"] == "delivery"
    assert body["source_chain"]["items_total"] == 20.1
    assert body["source_chain"]["order_total"] == 56.0
    assert body["cheapest_chain"] == {
        "chain_code": RAMI_LEVI,
        "chain_name": "Rami Levi",
        "items_total": 17.7,
        "total_price": 53.6,
    }
    assert [item["quantity"] for item in body["items"]] == [1, 2]
    assert [item["competitor_price"] for item in body["items"]] == [10.0, 7.7]


def test_compare_rejects_unrecognised_origin(monkeypatch):
    response = client(monkeypatch).post(
        "/api/compare",
        headers={"Origin": "https://example.com"},
        json={"source_chain_code": SHUFERSAL, "barcodes": []},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden: unrecognised origin."


def test_compare_rejects_excessive_quantity(monkeypatch):
    response = client(monkeypatch).post(
        "/api/compare",
        headers={"Origin": "chrome-extension://test"},
        json={
            "source_chain_code": SHUFERSAL,
            "barcodes": ["111"],
            "quantities": {"111": api.MAX_ITEM_QUANTITY + 1},
        },
    )

    assert response.status_code == 422
    assert "Item quantity" in response.json()["detail"]


def test_ready_returns_503_when_database_is_unavailable(monkeypatch):
    class UnavailableRepository:
        def ping(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(api, "SupabaseRepository", UnavailableRepository)
    monkeypatch.setattr(api, "_last_ready_at", 0.0)

    response = TestClient(api.app, raise_server_exceptions=False).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not ready."
