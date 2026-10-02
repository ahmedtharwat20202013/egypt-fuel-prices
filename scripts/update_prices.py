#!/usr/bin/env python3
"""Safely fetch and publish official Egyptian fuel prices.

The script never modifies prices.json until every required product and every
validation rule passes. Any exception leaves the existing file untouched.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx"
CNG_SOURCE_URL = "https://www.petroleum.gov.eg/ar-eg/media-center/news/news-pages/Pages/mop_10032026_02.aspx"
DATA_FILE = Path(__file__).resolve().parents[1] / "prices.json"
HEADERS = {
    "User-Agent": "EgyptFuelPricesBot/1.0 (+https://github.com/ahmedtharwat20202013/egypt-fuel-prices)",
    "Accept-Language": "ar,en;q=0.8",
}
REQUIRED = {
    "gasoline_80": ("بنزين 80",),
    "gasoline_92": ("بنزين 92",),
    "gasoline_95": ("بنزين 95",),
    "diesel": ("سولار",),
    "cng": ("غاز تموين السيارات",),
}
MIN_PRICE = Decimal("1")
MAX_PRICE = Decimal("100")


def normalize_digits(value: str) -> str:
    table = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return value.translate(table).replace("٫", ".").replace("٬", ",")


def parse_number(value: str) -> Decimal:
    value = normalize_digits(value).strip().replace(",", ".")
    match = re.search(r"(?<!\d)\d+(?:\.\d+)?(?!\d)", value)
    if not match:
        raise ValueError(f"Not a numeric price: {value!r}")
    try:
        return Decimal(match.group(0))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric price: {value!r}") from exc


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=(10, 30))
    response.raise_for_status()
    if not response.text or len(response.text) < 1_000:
        raise RuntimeError(f"Official response is empty or unexpectedly small: {url}")
    return response.text


def extract_from_tables(html: str, labels: tuple[str, ...]) -> Decimal | None:
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = [" ".join(cell.stripped_strings) for cell in row.find_all(["th", "td"])]
        row_text = " ".join(cells)
        if not any(label in row_text for label in labels):
            continue
        # The official tables may contain an empty icon cell before the label.
        # Only inspect cells after the cell containing the product label; this
        # prevents interpreting the octane number in "بنزين 80" as its price.
        label_index = next(i for i, cell in enumerate(cells) if any(label in cell for label in labels))
        for cell in cells[label_index + 1:]:
            try:
                price = parse_number(cell)
            except ValueError:
                continue
            if MIN_PRICE <= price <= MAX_PRICE:
                return price
    return None


def extract_cng_from_official_notice(html: str) -> Decimal | None:
    text = normalize_digits(" ".join(BeautifulSoup(html, "html.parser").stripped_strings))
    match = re.search(r"غاز تموين السيارات\s+من\s+\d+(?:[.,]\d+)?\s+الي\s+(\d+(?:[.,]\d+)?)\s+جنيه", text)
    return parse_number(match.group(1)) if match else None


def extract_prices(main_html: str, cng_html: str) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for key, labels in REQUIRED.items():
        price = extract_from_tables(main_html, labels)
        if price is not None:
            prices[key] = price
    cng = extract_cng_from_official_notice(cng_html)
    if cng is not None:
        prices["cng"] = cng
    missing = sorted(set(REQUIRED) - set(prices))
    if missing:
        raise RuntimeError("Required official products missing: " + ", ".join(missing))
    return prices


def load_data() -> dict[str, Any]:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read valid existing {DATA_FILE.name}: {exc}") from exc
    if not isinstance(data.get("prices"), dict):
        raise RuntimeError("Existing prices.json has no valid prices object")
    return data


def validate_prices(new: dict[str, Decimal], old: dict[str, Any]) -> None:
    for key in REQUIRED:
        value = new.get(key)
        if value is None or not (MIN_PRICE <= value <= MAX_PRICE):
            raise RuntimeError(f"Invalid price for {key}: {value!r}")


def json_price(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def build_data(old_data: dict[str, Any], new_prices: dict[str, Decimal]) -> dict[str, Any]:
    data = dict(old_data)
    data["country"] = "EG"
    data["currency"] = "EGP"
    data["unit"] = "liter"
    data["source"] = {"name": "Egyptian Ministry of Petroleum and Mineral Resources", "url": SOURCE_URL}
    data["lastUpdated"] = datetime.now(timezone.utc).date().isoformat()
    data["fetchedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data["prices"] = {key: json_price(new_prices[key]) for key in REQUIRED}
    return data


def write_atomically(data: dict[str, Any]) -> None:
    directory = DATA_FILE.parent
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(DATA_FILE)


def main() -> int:
    print(f"Fetching official source: {SOURCE_URL}")
    main_html = fetch_html(SOURCE_URL)
    cng_html = fetch_html(CNG_SOURCE_URL)
    old_data = load_data()
    prices = extract_prices(main_html, cng_html)
    print("Extracted: " + ", ".join(f"{key}={value}" for key, value in prices.items()))
    validate_prices(prices, old_data["prices"])
    new_data = build_data(old_data, prices)
    if new_data["prices"] == old_data["prices"]:
        print("Validation passed; prices are unchanged. No file update needed.")
        return 0
    write_atomically(new_data)
    print("Validation passed; prices.json updated safely.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL-SAFE: {exc}", file=sys.stderr)
        print("prices.json was not modified.", file=sys.stderr)
        raise SystemExit(1)
