import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.models import (
    ChainResult,
    CheapestChain,
    CompareRequest,
    CompareResponse,
    ItemResult,
    ShippingOption,
)
from app.db.repository import SupabaseRepository

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("API_KEY", "")

app = FastAPI(
    title="Cart Sniper API",
    description="Compares a supermarket cart against competitor chains using exact barcode matching.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "chrome-extension://"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def _verify_api_key(x_api_key: str) -> None:
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY is not configured on the server.",
        )
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )


def _calc_shipping_fee(option: dict, cart_total: float) -> tuple[float, bool]:
    """
    Returns (fee, unavailable) for this shipping option given the cart total.

    unavailable=True means the cart doesn't meet the minimum order — the option
    is still returned so the widget can display it with a warning.

    Special case — Shufersal pickup two-tier pricing:
      fee=15 when cart < ₪750, fee=10 when cart >= ₪750.
    Encoded as: fee=15, notes contains "₪750".
    """
    min_order = option.get("min_order")
    if min_order is not None and cart_total < min_order:
        return option["fee"], True  # unavailable — show with warning

    free_above = option.get("free_above")
    if free_above is not None and cart_total >= free_above:
        return 0.0, False

    base_fee = option["fee"]

    # Shufersal pickup two-tier: ₪15 → ₪10 at ₪750
    if "₪750" in (option.get("notes") or "") and cart_total >= 750:
        return 10.0, False

    return base_fee, False


@app.post("/api/compare", response_model=CompareResponse)
def compare_cart(
    request: CompareRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> CompareResponse:
    _verify_api_key(x_api_key)

    if not request.barcodes:
        return CompareResponse(
            cheapest_chain=None, matched_count=0, total_count=0, chains=[], items=[]
        )

    logger.info(
        "Comparing %d barcodes for source chain %s",
        len(request.barcodes),
        request.source_chain_code,
    )

    def qty(barcode: str) -> int:
        return max(1, request.quantities.get(barcode, 1))

    repo = SupabaseRepository()
    product_names = repo.get_product_names(request.barcodes)
    competitor_data = repo.get_competitor_prices(
        source_chain_code=request.source_chain_code,
        barcodes=request.barcodes,
    )
    source_data = repo.get_source_prices(
        source_chain_code=request.source_chain_code,
        barcodes=request.barcodes,
    )

    # Build the common barcode set: barcodes the SOURCE has AND at least one
    # competitor has. Items only the source carries cannot be compared, so they
    # are excluded from every chain total to keep the comparison apples-to-apples.
    src = source_data.get(request.source_chain_code)
    src_barcodes_raw = set(src["items"].keys()) if src else set()

    all_competitor_barcodes: set[str] = set()
    for chain in competitor_data.values():
        all_competitor_barcodes |= set(chain["items"].keys())

    source_barcodes = src_barcodes_raw & all_competitor_barcodes  # intersection

    def chain_items_total(chain_items: dict) -> float:
        """Sum price × qty for barcodes in the common comparable set only."""
        return round(
            sum(item["price"] * qty(b) for b, item in chain_items.items()
                if b in source_barcodes),
            2,
        )

    if not competitor_data:
        src_total = round(
            sum(item["price"] * qty(b) for b, item in src["items"].items()), 2
        ) if src else 0.0

        source_chain_result: ChainResult | None = None
        if src:
            src_shipping_raw = repo.get_shipping_costs([request.source_chain_code])
            src_shipping: list[ShippingOption] = []
            for opt in src_shipping_raw.get(request.source_chain_code, []):
                fee, unavailable = _calc_shipping_fee(opt, src_total)
                src_shipping.append(ShippingOption(
                    option_type=opt["option_type"], fee=fee,
                    notes=opt["notes"], unavailable=unavailable,
                ))
            source_chain_result = ChainResult(
                chain_code=request.source_chain_code,
                chain_name=src["chain_name"],
                items_total=src_total,
                matched_count=len(source_barcodes),
                shipping=src_shipping,
            )

        return CompareResponse(
            cheapest_chain=None,
            source_chain=source_chain_result,
            matched_count=0,
            total_count=len(request.barcodes),
            chains=[],
            items=[
                ItemResult(
                    barcode=b,
                    product_name=product_names.get(b),
                    quantity=qty(b),
                    unit_price=None,
                    competitor_price=None,
                    matched=False,
                )
                for b in request.barcodes
            ],
        )

    # Fetch shipping costs for all chains in one query
    all_chain_codes = list(competitor_data.keys()) + [request.source_chain_code]
    all_shipping_data = repo.get_shipping_costs(all_chain_codes)

    def make_shipping(chain_code: str, cart_total: float) -> list[ShippingOption]:
        opts: list[ShippingOption] = []
        for opt in all_shipping_data.get(chain_code, []):
            fee, unavailable = _calc_shipping_fee(opt, cart_total)
            opts.append(ShippingOption(
                option_type=opt["option_type"], fee=fee,
                notes=opt["notes"], unavailable=unavailable,
            ))
        return opts

    # Build competitor ChainResults — totals restricted to source_barcodes
    chain_results: list[ChainResult] = []
    for chain_code, chain in competitor_data.items():
        cart_total = chain_items_total(chain["items"])
        matched_in_common = sum(1 for b in source_barcodes if b in chain["items"])
        chain_results.append(ChainResult(
            chain_code=chain_code,
            chain_name=chain["chain_name"],
            items_total=cart_total,
            matched_count=matched_in_common,
            shipping=make_shipping(chain_code, cart_total),
        ))

    # Build source ChainResult — total restricted to the common comparable set
    src_total = round(
        sum(src["items"][b]["price"] * qty(b) for b in source_barcodes), 2
    ) if src else 0.0
    source_chain_result = ChainResult(
        chain_code=request.source_chain_code,
        chain_name=src["chain_name"],
        items_total=src_total,
        matched_count=len(source_barcodes),
        shipping=make_shipping(request.source_chain_code, src_total),
    ) if src else None

    # Cheapest competitor = lowest items-only total (shipping shown separately)
    cheapest = min(chain_results, key=lambda c: c.items_total)

    # Per-item breakdown against the cheapest competitor chain
    cheapest_items = competitor_data[cheapest.chain_code]["items"]
    items: list[ItemResult] = []
    for barcode in request.barcodes:
        q = qty(barcode)
        if barcode in cheapest_items:
            entry = cheapest_items[barcode]
            unit = entry["price"]
            items.append(ItemResult(
                barcode=barcode,
                product_name=entry["product_name"] or product_names.get(barcode),
                quantity=q,
                unit_price=unit,
                competitor_price=round(unit * q, 2),
                matched=True,
            ))
        else:
            items.append(ItemResult(
                barcode=barcode,
                product_name=product_names.get(barcode),
                quantity=q,
                unit_price=None,
                competitor_price=None,
                matched=False,
            ))

    return CompareResponse(
        cheapest_chain=CheapestChain(
            chain_code=cheapest.chain_code,
            chain_name=cheapest.chain_name,
            total_price=cheapest.items_total,
        ),
        source_chain=source_chain_result,
        matched_count=cheapest.matched_count,
        total_count=len(request.barcodes),
        chains=chain_results,
        items=items,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
