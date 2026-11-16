from decimal import Decimal


def convert(amount, to, rates):
    """Convert a USD amount string to `to`."""
    return str((Decimal(amount) / Decimal(str(rates[to]))).quantize(Decimal("0.01")))
