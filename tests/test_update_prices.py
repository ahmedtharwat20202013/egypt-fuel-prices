import importlib.util
from decimal import Decimal
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("update_prices", Path(__file__).parents[1] / "scripts/update_prices.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

MAIN_HTML = """
<table><tr><th>النوع</th><th>السعر</th></tr>
<tr><td>بنزين 80</td><td>20.75 جنيه/لتر</td></tr>
<tr><td>بنزين 95</td><td>24 جنيه/لتر</td></tr>
<tr><td>بنزين 92</td><td>22.25 جنيه/لتر</td></tr>
<tr><td>سولار</td><td>20.5 جنيه/لتر</td></tr>
<tr><td>كيروسين</td><td>20.5 جنيه/لتر</td></tr>
</table>
"""
CNG_HTML = "<p>غاز تموين السيارات من 10 الي 13 جنيه للمتر</p>"
EXPECTED = {"gasoline_80": Decimal("20.75"), "gasoline_92": Decimal("22.25"), "gasoline_95": Decimal("24"), "diesel": Decimal("20.5"), "kerosene": Decimal("20.5"), "cng": Decimal("13")}


def test_extracts_all_products_and_arabic_digits():
    assert MOD.extract_prices(MAIN_HTML, CNG_HTML) == EXPECTED


def test_missing_product_fails():
    try:
        MOD.extract_prices(MAIN_HTML.replace("بنزين 92", "بنزين X"), CNG_HTML)
    except RuntimeError as exc:
        assert "gasoline_92" in str(exc)
    else:
        raise AssertionError("missing product must fail")


def test_invalid_price_fails_validation():
    bad = dict(EXPECTED, diesel=Decimal("0"))
    try:
        MOD.validate_prices(bad, EXPECTED)
    except RuntimeError:
        pass
    else:
        raise AssertionError("invalid price must fail")


def test_change_over_sixty_percent_fails():
    try:
        MOD.validate_prices(dict(EXPECTED, gasoline_92=Decimal("99")), EXPECTED)
    except RuntimeError as exc:
        assert "60%" in str(exc)
    else:
        raise AssertionError("large change must fail")
