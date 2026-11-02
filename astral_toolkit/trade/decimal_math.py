"""Keep accepted price digits; round only non-terminating division, half-even."""

from contextlib import contextmanager
from decimal import Decimal, localcontext, ROUND_HALF_EVEN


@contextmanager
def precise(values):
    values = [v for v in values if isinstance(v, Decimal) and v.is_finite()]
    integer = max([1] + [v.adjusted() + 1 for v in values])
    fractional = max([0] + [-v.as_tuple().exponent for v in values])
    # 32 guard digits cover integer stock multiplication and arithmetic means.
    with localcontext() as context:
        context.prec = max(64, integer + fractional + 32 + len(str(len(values))))
        context.rounding = ROUND_HALF_EVEN
        yield
