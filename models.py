from datetime import datetime
from typing import Annotated, Optional

from _typeshed import OpenBinaryMode, OptExcInfo, ProfileFunction
from pydantic import BaseModel, Field, StringConstraints, model_validator

BarcodeType = Annotated[str, StringConstraints(min_length=3, pattern=r"^\d+$")]


class ProductModel(BaseModel):
    barcode: BarcodeType
    prodact_name: str
    family_id: Optional[int] = None
    image_url: Optional[str] = None
    unit_name: str
    total_quantity: float

    @model_validator(mode="after")
    def normalize_quantities(self):
        clean_unit = self.unit_name.lower().strip().replace('"', "").replace("'", "")
        if clean_unit.startswith("100") and "1000" not in clean_unit:
            self.total_quantity *= 100
            clean_unit = clean_unit.replace("100", "").strip()
        
        elif clean_unit in ["kg", "קג","קילו"]:
            self.total_quantity *= 1000
            self.unit_name = "gr"
        elif clean_unit in ["l", "liter", "L", "ליטר"]:
            self.total_quantity *= 1000
            self.unit_name = "ml"
        return self

class PriceModel(BaseModel):
    store_id : int
    barcode : BarcodeType
    price : float
    original_price: Optional[float] = None

    is_promo: bool = False
    promo_description: Optional[str] = None
    promo_min_qty: int = 1
    promo_price_for_bundle: Optional[float] = None
    price_update_date: datetime
    price_per_unit: Optional[float] = None # calculated column


    

