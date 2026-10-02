#!/usr/bin/env python3
"""
Fetch official Egyptian fuel prices and safely update prices.json.

Source:
https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx?ItemID=719

The script intentionally fails instead of publishing incomplete or
suspiciously parsed prices.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx?ItemID=719"
DATA_FILE = Path(__file__).resolve().parents[1] / "prices.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EgyptFuelPricesBot/1.0; "
        "+https://github.com/)"
    ),
    "Accept-Language": "ar,en;q=0.8",
}

# Exact Arabic labels expected on the official page.
REQUIRED = {
    "gasoline_80": ["بنزين 80"],
    "gasoline_92": ["بنزين 92"],
    "gasoline_95": ["بنزين 95"],
    "diesel": ["سولار"],
    "kerosene": ["كيروسين"],
    "cng": ["غاز تموين السيارات"],
}

# Conservative sanity limits. They are not price predictions.
MIN_PRICE = Decimal("1")
MAX_PRICE = Decimal("100")


def normalize_digits(value: str) -> str:
    arabic = "٠١٢٣٤٥٦٧٨٩"
    persian = "۰۱۲۳۴۵۶۷۸۹"
    out = value
    for a, b in zip(arabic, "0123456789"):
        out = out.replace(a, b)
    for a, b in zip(persian, "0123456789"):
        out = out.replace(a, b)
    return out


def parse_number(value: str) -> Decimal:
    value = normalize_digits(value)
    value = value.replace(",", ".").strip()
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        raise ValueError(f"Could not parse price from: {value!r}")
    try:
        return Decimal(match.group(0))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid price: {value!r}") from exc


def fetch_html() -> str:
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    if len(response.text) < 10_000:
        raise RuntimeError("Official page response is unexpectedly small.")
    return response.text


def extract_prices(html: str) -> dict[str, Decimal]:
    soup = BeautifulSoup(html, "html.parser")

    # Search table rows first; this reduces accidental matches elsewhere.
    rows = soup.find_all("tr")
    row_texts = [" ".join(row.stripped_strings) for row in rows]

    result: dict[str, Decimal] = {}

    for key, labels in REQUIRED.items():
        candidates = []

        for row_text in row_texts:
            if any(label in row_text for label in labels):
                # Price normally appears after the product name.
                numbers = re.findall(r"[٠-٩۰-۹0-9]+(?:[.,][٠-٩۰-۹0-9]+)?", row_text)
                for raw in numbers:
                    try:
                        n = parse_number(raw)
                    except ValueError:
                        continue
                    if MIN_PRICE <= n <= MAX_PRICE:
                        candidates.append(n)

        if not candidates:
            # Fallback: search the full visible text around the label.
            text = " ".join(soup.stripped_strings)
            for label in labels:
                idx = text.find(label)
                if idx >= 0:
                    window = text[idx:idx + 180]
                    numbers = re.findall(
                        r"[٠-٩۰-۹0-9]+(?:[.,][٠-٩۰-۹0-9]+)?", window
                    )
                    for raw in numbers:
                        try:
                            n = parse_number(raw)
                        except ValueError:
                            continue
                        if MIN_PRICE <= n <= MAX_PRICE:
                            candidates.append(n)

        if not candidates:
            raise RuntimeError(
                f"Missing official price for {key}. "
                "The source page may have changed; refusing to publish."
            )

        # The first valid price in the matching official row is the intended one.
        result[key] = candidates[0]

    return result


def validate(new_prices: dict[str, Decimal], old_prices: dict) -> None:
    expected = set(REQUIRED)
    if set(new_prices) != expected:
        raise RuntimeError("Validation failed: missing or unexpected price keys.")

    for key, value in new_prices.items():
        if not (MIN_PRICE <= value <= MAX_PRICE):
            raise RuntimeError(f"Validation failed: {key}={value} is out of range.")

    # Detect suspicious parsing errors without blocking legitimate changes forever.
    # A huge change is allowed only if the official page still contains all required
    # products and prices, but we fail closed here to force human review.
    for key, new_value in new_prices.items():
        old_raw = old_prices.get(key)
        if old_raw is None:
            continue
        old_value = Decimal(str(old_raw))
        if old_value == 0:
            continue
        change = abs(new_value - old_value) / old_value
        if change > Decimal("0.60"):
            raise RuntimeError(
                f"Validation failed: {key} changed by more than 60% "
                f"({old_value} -> {new_value}). Manual review required."
            )


def main() -> int:
    try:
        old_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        html = fetch_html()
        new_prices = extract_prices(html)
        validate(new_prices, old_data["prices"])

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        old_data["source"] = {
            "name": "Egyptian Ministry of Petroleum and Mineral Resources",
            "url": SOURCE_URL,
        }
        old_data["currency"] = "EGP"
        old_data["unit"] = "liter"
        old_data["fetchedAt"] = now
        old_data["lastUpdated"] = now[:10]
        old_data["prices"] = {
            key: float(value) for key, value in new_prices.items()
        }

        DATA_FILE.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print("SUCCESS: official fuel prices validated and written to prices.json")
        print(json.dumps(old_data["prices"], ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
