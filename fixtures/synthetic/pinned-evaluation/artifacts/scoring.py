# Fictional scoring script for the pinned-evaluation example.
from decimal import Decimal


def signed_error(forecast, outcome):
    return str(Decimal(forecast) - Decimal(outcome))
