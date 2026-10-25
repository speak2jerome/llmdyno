class InventoryError(Exception):
    pass


class DuplicateSku(InventoryError):
    pass


class UnknownSku(InventoryError):
    pass


class InsufficientStock(InventoryError):
    pass
