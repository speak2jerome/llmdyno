from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ._mode import USE_DECIMAL


def money(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Item:
    sku: str
    name: str
    qty: int
    price: float

    def __post_init__(self):
        self.qty = int(self.qty)
        self.price = money(self.price) if USE_DECIMAL else float(self.price)


@dataclass
class Movement:
    sku: str
    delta: int
    reason: str
    timestamp: str
