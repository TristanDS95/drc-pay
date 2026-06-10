"""Money: integer minor units, exact parsing, currency safety."""
from __future__ import annotations

from drc_pay_api.domains.ledger.money import (
    CurrencyMismatch,
    Money,
    UnknownCurrency,
)


def test_from_major_parses_exactly() -> None:
    assert Money.from_major("10.50", "USD") == Money(1050, "USD")
    assert Money.from_major("0.01", "USD") == Money(1, "USD")
    assert Money.from_major(7, "USD") == Money(700, "USD")


def test_no_float_rounding_errors() -> None:
    # 0.1 + 0.2 in floats is not 0.3; in minor units it is exact.
    a = Money.from_major("0.10", "USD")
    b = Money.from_major("0.20", "USD")
    assert (a + b) == Money.from_major("0.30", "USD")


def test_half_up_rounding() -> None:
    assert Money.from_major("1.005", "USD") == Money(101, "USD")


def test_addition_and_subtraction() -> None:
    assert Money(1050, "USD") + Money(950, "USD") == Money(2000, "USD")
    assert Money(1050, "USD") - Money(50, "USD") == Money(1000, "USD")


def test_times_integer_factor() -> None:
    assert Money(250, "USD").times(3) == Money(750, "USD")


def test_currency_mismatch_raises() -> None:
    try:
        Money(100, "USD") + Money(100, "CDF")
    except CurrencyMismatch:
        pass
    else:
        raise AssertionError("expected CurrencyMismatch")


def test_unknown_currency_raises() -> None:
    try:
        Money(100, "EUR")
    except UnknownCurrency:
        pass
    else:
        raise AssertionError("expected UnknownCurrency")


def test_float_amount_rejected() -> None:
    try:
        Money(10.5, "USD")  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for a float amount")


def test_to_major_str() -> None:
    assert Money(1050, "USD").to_major_str() == "10.50"
    assert Money(1, "USD").to_major_str() == "0.01"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_money: all passed")
