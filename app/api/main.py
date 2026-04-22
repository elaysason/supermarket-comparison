import logging
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
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

# Allowed origins: Chrome extension origins and localhost for development.
# In production, replace the regex with your specific extension ID:
#   r"^chrome-extension://YOUR_EXTENSION_ID_HERE$"
ALLOWED_ORIGIN_RE = re.compile(
    r"^chrome-extension://[a-z]{32}$"
    r"|^https?://127\.0\.0\.1(:\d+)?$"
    r"|^https?://localhost(:\d+)?$"
)

app = FastAPI(
    title="Cart Sniper API",
    description="Compares a supermarket cart against competitor chains using exact barcode matching.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*|https?://127\.0\.0\.1(:\d+)?|https?://localhost(:\d+)?",
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _verify_origin(request: Request) -> None:
    """
    Validate that the request comes from a trusted origin.

    Chrome enforces the Origin header on extension requests — web pages
    cannot spoof a chrome-extension:// origin.  This replaces the static
    API key approach, which provided no real security in a client-side
    extension (the key was always extractable from the package).
    """
    origin = request.headers.get("origin") or request.headers.get("Origin") or ""
    if not ALLOWED_ORIGIN_RE.match(origin):
        logger.warning("Rejected request from origin: %s", origin)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: unrecognised origin.",
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


def _best_available_order_total(items_total: float, options: list[ShippingOption]) -> float | None:
    if not options:
        return items_total

    available_totals = [
        round(items_total + option.fee, 2)
        for option in options
        if not option.unavailable
    ]
    if not available_totals:
        return None
    return min(available_totals)


def _select_comparison_option_type(
    source_options: list[ShippingOption],
    competitor_results: list[dict],
) -> str | None:
    source_option_types = {option.option_type for option in source_options}
    if not source_option_types:
        return None

    supported_by_any_competitor = set()
    for chain in competitor_results:
        supported_by_any_competitor |= {option.option_type for option in chain["shipping"]}

    common_option_types = source_option_types & supported_by_any_competitor
    if not common_option_types:
        return None

    if "delivery" in common_option_types:
        return "delivery"
    if "pickup" in common_option_types:
        return "pickup"
    return None


def _order_total_for_option(
    items_total: float,
    options: list[ShippingOption],
    option_type: str | None,
) -> float | None:
    if option_type is None:
        return None

    for option in options:
        if option.option_type == option_type:
            return None if option.unavailable else round(items_total + option.fee, 2)
    return None


@app.post("/api/compare", response_model=CompareResponse)
def compare_cart(
    request: CompareRequest,
    raw_request: Request,
) -> CompareResponse:
    _verify_origin(raw_request)

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

    if not source_barcodes:
        src_total = (
            round(sum(item["price"] * qty(b) for b, item in src["items"].items()), 2)
            if src
            else 0.0
        )

        source_chain_result: ChainResult | None = None
        if src:
            src_shipping_raw = repo.get_shipping_costs([request.source_chain_code])
            src_shipping: list[ShippingOption] = []
            for opt in src_shipping_raw.get(request.source_chain_code, []):
                fee, unavailable = _calc_shipping_fee(opt, src_total)
                src_shipping.append(
                    ShippingOption(
                        option_type=opt["option_type"],
                        fee=fee,
                        notes=opt["notes"],
                        min_order=opt.get("min_order"),
                        unavailable=unavailable,
                    )
                )
            source_chain_result = ChainResult(
                chain_code=request.source_chain_code,
                chain_name=src["chain_name"],
                items_total=src_total,
                order_total=_best_available_order_total(src_total, src_shipping),
                matched_count=0,
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

    def chain_items_total(chain_items: dict) -> float:
        """Sum price × qty for barcodes in the common comparable set only."""
        return round(
            sum(
                item["price"] * qty(b)
                for b, item in chain_items.items()
                if b in source_barcodes
            ),
            2,
        )

    # Fetch shipping costs for all chains in one query
    all_chain_codes = list(competitor_data.keys()) + [request.source_chain_code]
    all_shipping_data = repo.get_shipping_costs(all_chain_codes)

    def make_shipping(chain_code: str, cart_total: float) -> list[ShippingOption]:
        opts: list[ShippingOption] = []
        for opt in all_shipping_data.get(chain_code, []):
            fee, unavailable = _calc_shipping_fee(opt, cart_total)
            opts.append(
                ShippingOption(
                    option_type=opt["option_type"],
                    fee=fee,
                    notes=opt["notes"],
                    min_order=opt.get("min_order"),
                    unavailable=unavailable,
                )
            )
        return opts

    # Build competitor totals first so we can choose one common fulfillment mode
    competitor_totals: list[dict] = []
    for chain_code, chain in competitor_data.items():
        cart_total = chain_items_total(chain["items"])
        matched_in_common = sum(1 for b in source_barcodes if b in chain["items"])
        shipping = make_shipping(chain_code, cart_total)
        competitor_totals.append(
            {
                "chain_code": chain_code,
                "chain_name": chain["chain_name"],
                "items_total": cart_total,
                "matched_count": matched_in_common,
                "shipping": shipping,
            }
        )

    # Build source ChainResult — total restricted to the common comparable set
    src_total = (
        round(sum(src["items"][b]["price"] * qty(b) for b in source_barcodes), 2)
        if src
        else 0.0
    )
    source_shipping = make_shipping(request.source_chain_code, src_total) if src else []
    comparison_option_type = _select_comparison_option_type(source_shipping, competitor_totals)

    # Build competitor ChainResults using the selected common fulfillment mode
    chain_results: list[ChainResult] = []
    for chain in competitor_totals:
        chain_results.append(
            ChainResult(
                chain_code=chain["chain_code"],
                chain_name=chain["chain_name"],
                items_total=chain["items_total"],
                order_total=_order_total_for_option(
                    chain["items_total"],
                    chain["shipping"],
                    comparison_option_type,
                ),
                matched_count=chain["matched_count"],
                shipping=chain["shipping"],
            )
        )
    source_chain_result = (
        ChainResult(
            chain_code=request.source_chain_code,
            chain_name=src["chain_name"],
            items_total=src_total,
            order_total=_order_total_for_option(
                src_total,
                source_shipping,
                comparison_option_type,
            ),
            matched_count=len(source_barcodes),
            shipping=source_shipping,
        )
        if src
        else None
    )

    # Cheapest competitor = lowest currently available order total.
    eligible_chain_results = [
        chain for chain in chain_results if chain.order_total is not None
    ]
    cheapest = (
        min(eligible_chain_results, key=lambda c: c.order_total)
        if eligible_chain_results
        else None
    )

    items: list[ItemResult] = []
    if cheapest:
        logger.info(
            "Cheapest available competitor: %s (₪%.2f)",
            cheapest.chain_name,
            cheapest.order_total,
        )

        cheapest_items = competitor_data[cheapest.chain_code]["items"]
        for barcode in request.barcodes:
            q = qty(barcode)
            if barcode in cheapest_items:
                entry = cheapest_items[barcode]
                unit = entry["price"]
                items.append(
                    ItemResult(
                        barcode=barcode,
                        product_name=entry["product_name"] or product_names.get(barcode),
                        quantity=q,
                        unit_price=unit,
                        competitor_price=round(unit * q, 2),
                        matched=True,
                    )
                )
            else:
                items.append(
                    ItemResult(
                        barcode=barcode,
                        product_name=product_names.get(barcode),
                        quantity=q,
                        unit_price=None,
                        competitor_price=None,
                        matched=False,
                    )
                )
    else:
        logger.info("No competitor has an available fulfillment option for this cart.")

    return CompareResponse(
        comparison_option_type=comparison_option_type,
        cheapest_chain=(
            CheapestChain(
                chain_code=cheapest.chain_code,
                chain_name=cheapest.chain_name,
                total_price=cheapest.order_total,
                items_total=cheapest.items_total,
            )
            if cheapest
            else None
        ),
        source_chain=source_chain_result,
        matched_count=cheapest.matched_count if cheapest else 0,
        total_count=len(request.barcodes),
        chains=chain_results,
        items=items,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
