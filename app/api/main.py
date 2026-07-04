import logging
import os
import re
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.models import (
    ChainResult,
    CheapestChain,
    CompareRequest,
    CompareResponse,
    BlockedChain,
    ItemResult,
    ShippingOption,
)
from app.db.repository import SupabaseRepository

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _env_list(name: str) -> list[str]:
    return [
        value.strip().rstrip("/")
        for value in os.getenv(name, "").split(",")
        if value.strip()
    ]


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Invalid %s=%r; using %d", name, value, default)
        return default
    if parsed <= 0:
        logger.warning("Invalid %s=%r; using %d", name, value, default)
        return default
    return parsed


ALLOWED_EXTENSION_ORIGINS = set(_env_list("ALLOWED_EXTENSION_ORIGINS"))
ALLOWED_LOCAL_ORIGINS = os.getenv("ALLOW_LOCAL_ORIGINS", "").lower() in (
    "1",
    "true",
    "yes",
)
LOCAL_ORIGIN_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")
MAX_COMPARE_BARCODES = _positive_int_env("MAX_COMPARE_BARCODES", 100)
MAX_BARCODE_LENGTH = _positive_int_env("MAX_BARCODE_LENGTH", 64)
MAX_ITEM_QUANTITY = _positive_int_env("MAX_ITEM_QUANTITY", 99)
READY_CACHE_SECONDS = _positive_int_env("READY_CACHE_SECONDS", 30)
MIN_COVERAGE_RATIO = 0.60
CARREFOUR_CHAIN_CODE = "7290055700007"
STALE_WARNING_DAYS = 2
STALE_STRONG_WARNING_DAYS = 4
STALE_BLOCK_DAYS = 7
_last_ready_at = 0.0

allowed_cors_origins = list(ALLOWED_EXTENSION_ORIGINS)
allowed_cors_regex = (
    r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$" if ALLOWED_LOCAL_ORIGINS else None
)

app = FastAPI(
    title="Cart Sniper API",
    description=(
        "Compares a supermarket cart against competitor chains using exact "
        "barcode matching."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_cors_origins,
    allow_origin_regex=allowed_cors_regex,
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
    if origin in ALLOWED_EXTENSION_ORIGINS:
        return
    if ALLOWED_LOCAL_ORIGINS and LOCAL_ORIGIN_RE.match(origin):
        return

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


def _best_available_order_total(
    items_total: float, options: list[ShippingOption]
) -> float | None:
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
        supported_by_any_competitor |= {
            option.option_type for option in chain["shipping"]
        }

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


def _age_days(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    ).total_seconds() / 86400


def _freshness_status(source_file_date: datetime | None) -> str:
    age_days = _age_days(source_file_date)
    if age_days is None:
        return "no_data"
    if age_days >= STALE_BLOCK_DAYS:
        return "blocked_stale"
    if age_days >= STALE_STRONG_WARNING_DAYS:
        return "stale_strong_warning"
    if age_days >= STALE_WARNING_DAYS:
        return "stale_warning"
    return "available"


def _blocked_chain(chain_code: str, status: dict) -> BlockedChain:
    return BlockedChain(
        chain_code=chain_code,
        chain_name=status["chain_name"],
        status=(
            "blocked_stale"
            if _freshness_status(status.get("source_file_date")) == "blocked_stale"
            else "no_data"
        ),
        last_updated=status.get("source_file_date"),
    )


def _coverage_status(matched_count: int, total_count: int) -> str:
    if total_count == 0 or matched_count == total_count:
        return "full"
    if matched_count / total_count < MIN_COVERAGE_RATIO:
        return "low_coverage"
    return "partial"


def _overall_last_updated(chains: list[ChainResult]) -> datetime | None:
    dates = [chain.last_updated for chain in chains if chain.last_updated is not None]
    return min(dates) if dates else None


@app.post("/api/compare", response_model=CompareResponse)
def compare_cart(
    request: CompareRequest,
    raw_request: Request,
) -> CompareResponse:
    _verify_origin(raw_request)

    original_barcodes = request.barcodes
    if len(original_barcodes) > MAX_COMPARE_BARCODES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many barcodes. Maximum is {MAX_COMPARE_BARCODES}.",
        )
    if len(request.quantities) > MAX_COMPARE_BARCODES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many quantity entries. Maximum is {MAX_COMPARE_BARCODES}.",
        )
    if any(len(barcode) > MAX_BARCODE_LENGTH for barcode in original_barcodes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Barcode length must be at most {MAX_BARCODE_LENGTH} characters.",
        )
    if any(quantity > MAX_ITEM_QUANTITY for quantity in request.quantities.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Item quantity must be at most {MAX_ITEM_QUANTITY}.",
        )

    if not original_barcodes:
        return CompareResponse(
            cheapest_chain=None, matched_count=0, total_count=0, chains=[], items=[]
        )

    repo = SupabaseRepository()
    known_input_product_names = repo.get_product_names(original_barcodes)
    resolved_barcodes = {}
    if request.source_chain_code == CARREFOUR_CHAIN_CODE:
        unresolved_input_barcodes = set(original_barcodes) - set(
            known_input_product_names
        )
        resolved_barcodes = repo.resolve_barcodes_by_names(
            source_chain_code=request.source_chain_code,
            item_names={
                item_id: name
                for item_id, name in request.item_names.items()
                if item_id in unresolved_input_barcodes
            },
        )
    barcode_aliases = {
        barcode: resolved_barcodes.get(barcode, barcode)
        for barcode in original_barcodes
    }
    barcodes = list(dict.fromkeys(barcode_aliases.values()))
    quantities_by_barcode: dict[str, int] = {}
    item_names_by_barcode: dict[str, str] = {}
    for original_barcode in original_barcodes:
        resolved_barcode = barcode_aliases[original_barcode]
        quantities_by_barcode[resolved_barcode] = quantities_by_barcode.get(
            resolved_barcode, 0
        ) + max(1, request.quantities.get(original_barcode, 1))
        item_name = request.item_names.get(original_barcode)
        if item_name and resolved_barcode not in item_names_by_barcode:
            item_names_by_barcode[resolved_barcode] = item_name

    logger.info(
        "Comparing %d barcodes for source chain %s",
        len(barcodes),
        request.source_chain_code,
    )

    def qty(barcode: str) -> int:
        return max(1, quantities_by_barcode.get(barcode, 1))

    product_names = repo.get_product_names(barcodes)
    product_names.update(
        {
            barcode: name
            for barcode, name in item_names_by_barcode.items()
            if barcode not in product_names
        }
    )
    compare_statuses = repo.get_compare_chain_statuses()
    source_import_status = compare_statuses.get(request.source_chain_code)
    source_freshness_status = _freshness_status(
        source_import_status.get("source_file_date") if source_import_status else None
    )
    blocked_statuses = {
        chain_code: status
        for chain_code, status in compare_statuses.items()
        if _freshness_status(status.get("source_file_date"))
        in ("blocked_stale", "no_data")
    }
    blocked_chains = [
        _blocked_chain(chain_code, status)
        for chain_code, status in blocked_statuses.items()
        if chain_code != request.source_chain_code
    ]

    if source_freshness_status in ("blocked_stale", "no_data"):
        source_chain_result = None
        source_data = repo.get_source_prices(
            source_chain_code=request.source_chain_code,
            barcodes=barcodes,
        )
        src = source_data.get(request.source_chain_code)
        if src:
            source_chain_result = ChainResult(
                chain_code=request.source_chain_code,
                chain_name=src["chain_name"],
                items_total=0,
                order_total=None,
                matched_count=0,
                shipping=[],
                status=source_freshness_status,
                last_updated=(
                    source_import_status.get("source_file_date")
                    if source_import_status
                    else None
                ),
            )
        return CompareResponse(
            recommendation_status="stale_blocked",
            coverage_status="full",
            cheapest_chain=None,
            source_chain=source_chain_result,
            matched_count=0,
            total_count=len(barcodes),
            chains=[],
            blocked_chains=blocked_chains,
            items=[
                ItemResult(
                    barcode=b,
                    product_name=product_names.get(b),
                    quantity=qty(b),
                    unit_price=None,
                    competitor_price=None,
                    matched=False,
                )
                for b in barcodes
            ],
        )

    available_competitor_codes = [
        chain_code
        for chain_code in compare_statuses
        if chain_code != request.source_chain_code
        and chain_code not in blocked_statuses
    ]
    competitor_data = repo.get_competitor_prices(
        source_chain_code=request.source_chain_code,
        barcodes=barcodes,
        chain_codes=available_competitor_codes,
    )
    source_data = repo.get_source_prices(
        source_chain_code=request.source_chain_code,
        barcodes=barcodes,
    )

    # Build the common barcode set. When the source chain has reliable price
    # data, require the source and every displayed competitor to share the same
    # barcodes. When the source feed is missing (for example Yohananof online
    # store 150), fall back to the requested cart barcodes and compare only the
    # overlap across competitors.
    src = source_data.get(request.source_chain_code)
    src_barcodes_raw = set(src["items"].keys()) if src else set(barcodes)

    common_barcodes = set(src_barcodes_raw)
    for chain in competitor_data.values():
        common_barcodes &= set(chain["items"].keys())

    if not common_barcodes:
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
                status=source_freshness_status,
                last_updated=source_import_status.get("source_file_date"),
            )

        return CompareResponse(
            recommendation_status="no_comparison",
            coverage_status="low_coverage" if barcodes else "full",
            overall_last_updated=(
                source_import_status.get("source_file_date")
                if source_import_status
                else None
            ),
            cheapest_chain=None,
            source_chain=source_chain_result,
            matched_count=0,
            total_count=len(barcodes),
            chains=[],
            blocked_chains=blocked_chains,
            items=[
                ItemResult(
                    barcode=b,
                    product_name=product_names.get(b),
                    quantity=qty(b),
                    unit_price=None,
                    competitor_price=None,
                    matched=False,
                )
                for b in barcodes
            ],
        )

    def chain_items_total(chain_items: dict) -> float:
        """Sum price × qty for barcodes in the common comparable set only."""
        return round(
            sum(
                item["price"] * qty(b)
                for b, item in chain_items.items()
                if b in common_barcodes
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
        matched_in_common = sum(1 for b in common_barcodes if b in chain["items"])
        shipping = make_shipping(chain_code, cart_total)
        competitor_totals.append(
            {
                "chain_code": chain_code,
                "chain_name": chain["chain_name"],
                "items_total": cart_total,
                "matched_count": matched_in_common,
                "shipping": shipping,
                "status": _freshness_status(
                    compare_statuses[chain_code].get("source_file_date")
                ),
                "last_updated": compare_statuses[chain_code].get("source_file_date"),
            }
        )

    # Build source ChainResult — total restricted to the common comparable set
    src_total = (
        round(sum(src["items"][b]["price"] * qty(b) for b in common_barcodes), 2)
        if src
        else 0.0
    )
    # Keep the source chain's supported fulfillment modes available even when we
    # do not have trustworthy source prices, so competitor-only comparison can
    # still choose the right mode (for example Yohananof pickup).
    source_shipping = make_shipping(
        request.source_chain_code, src_total if src else 0.0
    )
    comparison_option_type = _select_comparison_option_type(
        source_shipping, competitor_totals
    )

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
                status=chain["status"],
                last_updated=chain["last_updated"],
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
            matched_count=len(common_barcodes),
            shipping=source_shipping,
            status=source_freshness_status,
            last_updated=source_import_status.get("source_file_date"),
        )
        if src
        else None
    )

    all_available_chains = [
        chain for chain in [source_chain_result, *chain_results] if chain
    ]
    coverage = _coverage_status(len(common_barcodes), len(barcodes))
    recommendation_status = "available"
    if len(all_available_chains) < 2:
        recommendation_status = "not_enough_chains"
    elif coverage == "low_coverage":
        recommendation_status = "low_coverage"

    # Cheapest competitor = lowest currently available order total.
    eligible_chain_results = [
        chain for chain in chain_results if chain.order_total is not None
    ]
    cheapest = (
        min(eligible_chain_results, key=lambda c: c.order_total)
        if eligible_chain_results and recommendation_status == "available"
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
        for barcode in barcodes:
            q = qty(barcode)
            if barcode in common_barcodes and barcode in cheapest_items:
                entry = cheapest_items[barcode]
                unit = entry["price"]
                items.append(
                    ItemResult(
                        barcode=barcode,
                        product_name=(
                            entry["product_name"] or product_names.get(barcode)
                        ),
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
        recommendation_status=recommendation_status,
        coverage_status=coverage,
        overall_last_updated=_overall_last_updated(all_available_chains),
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
        matched_count=len(common_barcodes),
        total_count=len(barcodes),
        chains=chain_results,
        blocked_chains=blocked_chains,
        items=items,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    global _last_ready_at

    now = time.monotonic()
    if now - _last_ready_at < READY_CACHE_SECONDS:
        return {"status": "ready"}

    try:
        SupabaseRepository().ping()
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready.",
        ) from exc
    _last_ready_at = now
    return {"status": "ready"}
