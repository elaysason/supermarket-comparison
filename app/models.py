import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

BarcodeType = Annotated[str, StringConstraints(min_length=3, pattern=r"^\d+$")]


class Unit(str, Enum):
    GRAM = "gr"
    ML = "ml"
    UNIT = "unit"


# המילון שמתרגם עברית למתמטיקה
HEBREW_MULTIPLIERS = {
    "זוג": 2,
    "שלישיית": 3,
    "שלישית": 3,
    "רביעיית": 4,
    "רביעית": 4,
    "חמישיית": 5,
    "חמישית": 5,
    "שישיית": 6,
    "שישית": 6,
    "שמיניית": 8,
    "שמינית": 8,
    "עשיריית": 10,
    "עשירית": 10,
}


def extract_normalized_quantity(
    name: str, xml_qty: float, xml_unit: str
) -> tuple[float, Unit]:
    """
    Extracts the true mathematical weight/volume from Israeli supermarket data.
    Prioritizes the product name over XML data to avoid data entry errors.
    """
    # Defensive casting to handle nulls or unexpected types from the XML parser
    name = (name or "").lower()
    xml_unit = (xml_unit or "").lower().strip()
    xml_qty = float(xml_qty) if xml_qty else 1.0
    # 1. Math Multipacks (e.g., "4x160 גרם")
    math_multipack = re.search(r'(\d+)\s*[x*×]\s*(\d+)\s*(?:גר|ג"ר|גרם|מל|מ"ל)', name)
    if math_multipack:
        total = float(math_multipack.group(1)) * float(math_multipack.group(2))
        matched_string = math_multipack.group(0).replace('"', "")
        unit = Unit.ML if "מל" in matched_string else Unit.GRAM
        return total, unit

    # 2. Hebrew Word Multipacks (e.g., "רביעיית טונה 160 גרם")
    words_pattern = (
        r"("
        + "|".join(HEBREW_MULTIPLIERS.keys())
        + r').+?(\d+)\s*(?:גר|ג"ר|גרם|מל|מ"ל)'
    )
    hebrew_multipack = re.search(words_pattern, name)
    if hebrew_multipack:
        multiplier_word = hebrew_multipack.group(1)
        base_weight = float(hebrew_multipack.group(2))
        total = HEBREW_MULTIPLIERS[multiplier_word] * base_weight

        matched_string = hebrew_multipack.group(0).replace('"', "")
        unit = Unit.ML if "מל" in matched_string else Unit.GRAM
        return total, unit

    # 3. Standard Weight/Volume Regex (e.g., "700 גרם")
    weight_match = re.search(r'(\d+)\s*(?:גר|ג"ר|גרם|מל|מ"ל)', name)
    if weight_match:
        matched_string = weight_match.group(0).replace('"', "")
        unit = Unit.ML if "מל" in matched_string else Unit.GRAM
        return float(weight_match.group(1)), unit

    # 4. XML Fallback Logic
    if "100" in xml_unit:
        return xml_qty * 100, Unit.GRAM

    # Using 'any' for substrings to catch "1 קילו", but avoiding single letters!
    if any(k in xml_unit for k in ["kg", "קג", "קילו", 'ק"ג']):
        return xml_qty * 1000, Unit.GRAM

    if any(unit_name in xml_unit for unit_name in ["liter", "ליטר"]):
        return xml_qty * 1000, Unit.ML

    return xml_qty, xml_unit


class ProductModel(BaseModel):
    barcode: BarcodeType
    product_name: str
    family_id: Optional[int] = None
    image_url: Optional[str] = None
    unit_name: str
    total_quantity: float
    manufacturer_name: Optional[str] = None

    @model_validator(mode="after")
    def normalize_quantities(self):
        qty, unit = extract_normalized_quantity(
            name=self.product_name, xml_qty=self.total_quantity, xml_unit=self.unit_name
        )
        self.total_quantity = qty
        self.unit_name = unit.value if isinstance(unit, Unit) else unit
        return self


class StoreModel(BaseModel):
    chain_code: str
    store_code: str
    store_name: Optional[str] = None


class PriceModel(BaseModel):
    chain_code: str
    store_code: str
    barcode: BarcodeType
    price: float
    update_date: datetime

    # Excluded fields: Used ONLY for the PPU calculation, never saved to DB
    calc_quantity: Optional[float] = Field(default=None, exclude=True)
    calc_unit_name: Optional[str] = Field(default=None, exclude=True)

    price_per_unit: Optional[float] = None

    @model_validator(mode="after")
    def calculate_price_per_unit(self):
        allowed_units = ["gr", "ml"]
        if self.calc_quantity and self.calc_unit_name in allowed_units:
            if self.calc_quantity > 0:
                # Calculate standard price per 100 units
                calculated_ppu = (self.price / self.calc_quantity) * 100
                self.price_per_unit = round(calculated_ppu, 2)
        return self
