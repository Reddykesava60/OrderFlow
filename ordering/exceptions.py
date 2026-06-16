class CartError(Exception):
    """Raised for any validation failure during checkout."""
    def __init__(self, code, message, item_name=None):
        self.code       = code       # e.g. 'STOCK_ERROR', 'ITEM_UNAVAILABLE'
        self.message    = message
        self.item_name  = item_name
        super().__init__(message)


class PaymentConfigurationError(Exception):
    """Raised when a restaurant does not have a usable Razorpay configuration."""
    pass
