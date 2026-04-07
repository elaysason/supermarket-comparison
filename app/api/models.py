from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    source_chain_code: str = Field(
        ..., description="The chain code of the store the user is currently shopping at."
    )
    barcodes: List[str] = Field(
        ..., description="List of barcodes extracted from the user's active cart."
    )
    quantities: Dict[str, int] = Field(
        default_factory=dict,
        description="Map of barcode → quantity in cart. Missing entries default to 1.",
    )


class CheapestChain(BaseModel):
    chain_code: str
    chain_name: str
    total_price: float


class ShippingOption(BaseModel):
    option_type: str = Field(..., description="'delivery' or 'pickup'")
    fee: float = Field(..., description="Shipping/pickup fee in NIS for this cart total.")
    notes: Optional[str] = None
    unavailable: bool = Field(
        False,
        description="True when the cart total is below the chain's minimum order for this option.",
    )


class ChainResult(BaseModel):
    chain_code: str
    chain_name: str
    items_total: float = Field(..., description="Sum of matched item prices × quantities.")
    matched_count: int
    shipping: List[ShippingOption] = Field(
        default_factory=list,
        description="Available delivery/pickup options with their fees for this cart total.",
    )


class ItemResult(BaseModel):
    barcode: str
    product_name: Optional[str] = None
    quantity: int = Field(1, description="Number of this item in the cart.")
    unit_price: Optional[float] = Field(
        None, description="Unit price at the cheapest competitor. None if not matched."
    )
    competitor_price: Optional[float] = Field(
        None, description="Line total (unit_price × quantity) at the cheapest competitor."
    )
    matched: bool = Field(
        ..., description="True if this barcode was found at the cheapest competitor."
    )


class CompareResponse(BaseModel):
    cheapest_chain: Optional[CheapestChain] = Field(
        None,
        description="The competitor chain with the lowest items-only total. None if no matches.",
    )
    source_chain: Optional[ChainResult] = Field(
        None,
        description="The user's current chain with items_total for matched barcodes only. None if source has no price data.",
    )
    matched_count: int = Field(
        ..., description="Number of cart barcodes found in competitor price data."
    )
    total_count: int = Field(
        ..., description="Total number of barcodes sent in the request."
    )
    chains: List[ChainResult] = Field(
        default_factory=list,
        description="All competitor chains with their totals and shipping options.",
    )
    items: List[ItemResult] = Field(
        default_factory=list,
        description="Per-item breakdown against the cheapest chain.",
    )
