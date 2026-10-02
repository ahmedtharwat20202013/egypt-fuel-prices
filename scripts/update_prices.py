```python
#!/usr/bin/env python3
"""
Fetch official Egyptian fuel prices and safely update prices.json.

Behavior:
- If a fuel price exists on the official page, update it.
- If a fuel price is missing, skip it and keep the previous value.
- Missing individual prices do NOT stop the whole update.
- A real source/network error still stops the script.
- Suspicious price changes are rejected.
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


SOURCE_URL = (
    "https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx?ItemID=719"
)

DATA_FILE = Path(__file__).resolve().parents[1] / "prices.json"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EgyptFuelPricesBot/1.0; "
        "+https://github.com/)"
    ),
    "Accept-Language": "ar,en;q=0.8",
}


# Arabic labels expected on the official page.
#
# These are NOT mandatory anymore.
# If one is missing, the script simply skips it.
FUEL_LABELS = {
    "gasoline_80": ["بنزين 80"],
    "gasoline_92": ["بنزين 92"],
    "gasoline_95": ["بنزين 95"],
    "diesel": ["سولار"],
    "kerosene": ["كيروسين"],
    "cng": ["غاز تموين السيارات"],
}


# Conservative sanity limits.
MIN_PRICE = Decimal("1")
MAX_PRICE = Decimal("100")


def normalize_digits(value: str) -> str:
    """Convert Arabic/Persian digits to normal ASCII digits."""

    arabic = "٠١٢٣٤٥٦٧٨٩"
    persian = "۰۱۲۳۴۵۶۷۸۹"

    out = value

    for a, b in zip(arabic, "0123456789"):
        out = out.replace(a, b)

    for a, b in zip(persian, "0123456789"):
        out = out.replace(a, b)

    return out


def parse_number(value: str) -> Decimal:
    """Parse a decimal number from Arabic/English text."""

    value = normalize_digits(value)
    value = value.replace(",", ".").strip()

    match = re.search(
        r"\d+(?:\.\d+)?",
        value,
    )

    if not match:
        raise ValueError(
            f"Could not parse price from: {value!r}"
        )

    try:
        return Decimal(match.group(0))

    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid price: {value!r}"
        ) from exc


def fetch_html() -> str:
    """Download the official page."""

    print("========================================")
    print("Fetching official Egypt fuel prices...")
    print("========================================")

    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    if len(response.text) < 10_000:
        raise RuntimeError(
            "Official page response is unexpectedly small."
        )

    print(
        f"✅ Official page downloaded successfully "
        f"({len(response.text):,} characters)"
    )

    return response.text


def find_price_in_row(
    row_text: str,
    labels: list[str],
) -> Decimal | None:
    """
    Try to find a valid price inside a table row.
    """

    if not any(label in row_text for label in labels):
        return None

    numbers = re.findall(
        r"[٠-٩۰-۹0-9]+(?:[.,][٠-٩۰-۹0-9]+)?",
        row_text,
    )

    candidates: list[Decimal] = []

    for raw in numbers:
        try:
            number = parse_number(raw)

        except ValueError:
            continue

        if MIN_PRICE <= number <= MAX_PRICE:
            candidates.append(number)

    if not candidates:
        return None

    # The first valid number is considered the price.
    return candidates[0]


def find_price_in_text(
    text: str,
    labels: list[str],
) -> Decimal | None:
    """
    Fallback search in the full visible page text.
    """

    for label in labels:
        index = text.find(label)

        if index < 0:
            continue

        window = text[index:index + 180]

        numbers = re.findall(
            r"[٠-٩۰-۹0-9]+(?:[.,][٠-٩۰-۹0-9]+)?",
            window,
        )

        candidates: list[Decimal] = []

        for raw in numbers:
            try:
                number = parse_number(raw)

            except ValueError:
                continue

            if MIN_PRICE <= number <= MAX_PRICE:
                candidates.append(number)

        if candidates:
            return candidates[0]

    return None


def extract_prices(
    html: str,
) -> tuple[dict[str, Decimal], list[str]]:
    """
    Extract all available prices.

    Missing prices are skipped instead of raising an error.

    Returns:
        (found_prices, skipped_keys)
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rows = soup.find_all("tr")

    row_texts = [
        " ".join(row.stripped_strings)
        for row in rows
    ]

    visible_text = " ".join(
        soup.stripped_strings
    )

    result: dict[str, Decimal] = {}
    skipped: list[str] = []

    print("")
    print("========================================")
    print("Searching for fuel prices...")
    print("========================================")

    for key, labels in FUEL_LABELS.items():

        price: Decimal | None = None

        # ------------------------------------
        # First: search table rows
        # ------------------------------------

        for row_text in row_texts:

            price = find_price_in_row(
                row_text,
                labels,
            )

            if price is not None:
                break

        # ------------------------------------
        # Second: fallback full-text search
        # ------------------------------------

        if price is None:

            price = find_price_in_text(
                visible_text,
                labels,
            )

        # ------------------------------------
        # Result
        # ------------------------------------

        if price is None:

            skipped.append(key)

            print(
                f"⚠️ {key}: price not found "
                f"-> SKIPPED"
            )

            continue

        result[key] = price

        print(
            f"✅ {key}: {price}"
        )

    return result, skipped


def validate(
    new_prices: dict[str, Decimal],
    old_prices: dict,
) -> None:
    """
    Validate only prices that were actually found.

    Missing prices are allowed.
    """

    if not new_prices:

        raise RuntimeError(
            "No fuel prices were found on the official page."
        )

    print("")
    print("========================================")
    print("Validating prices...")
    print("========================================")

    for key, value in new_prices.items():

        if not (
            MIN_PRICE
            <= value
            <= MAX_PRICE
        ):

            raise RuntimeError(
                f"Validation failed: "
                f"{key}={value} is out of range."
            )

        print(
            f"✅ {key}: {value} "
            f"is within valid range"
        )

    # ------------------------------------
    # Detect suspicious price changes
    # ------------------------------------

    for key, new_value in new_prices.items():

        old_raw = old_prices.get(key)

        # New price with no previous value.
        if old_raw is None:
            continue

        try:
            old_value = Decimal(
                str(old_raw)
            )

        except InvalidOperation:

            raise RuntimeError(
                f"Validation failed: "
                f"invalid old price for {key}: "
                f"{old_raw!r}"
            )

        if old_value == 0:
            continue

        change = (
            abs(new_value - old_value)
            / old_value
        )

        if change > Decimal("0.60"):

            raise RuntimeError(
                f"Validation failed: "
                f"{key} changed by more than 60% "
                f"({old_value} -> {new_value}). "
                "Manual review required."
            )


def update_prices_json(
    old_data: dict,
    new_prices: dict[str, Decimal],
    skipped: list[str],
) -> dict:
    """
    Merge new prices with old prices.

    Important:
    Missing prices remain unchanged.
    """

    old_prices = dict(
        old_data.get("prices", {})
    )

    # Update only prices that were successfully found.
    for key, value in new_prices.items():

        old_prices[key] = float(value)

    now = datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )

    old_data["source"] = {
        "name": (
            "Egyptian Ministry of Petroleum "
            "and Mineral Resources"
        ),
        "url": SOURCE_URL,
    }

    old_data["currency"] = "EGP"

    old_data["unit"] = "liter"

    old_data["fetchedAt"] = now

    old_data["lastUpdated"] = now[:10]

    # IMPORTANT:
    # Keep old prices for anything that was not found.
    old_data["prices"] = old_prices

    return old_data


def main() -> int:

    try:

        # ====================================
        # 1. Read existing prices.json
        # ====================================

        if not DATA_FILE.exists():

            raise RuntimeError(
                f"Data file not found: {DATA_FILE}"
            )

        old_data = json.loads(
            DATA_FILE.read_text(
                encoding="utf-8"
            )
        )

        if "prices" not in old_data:

            raise RuntimeError(
                "prices.json does not contain a 'prices' object."
            )

        old_prices = old_data["prices"]

        # ====================================
        # 2. Download official page
        # ====================================

        html = fetch_html()

        # ====================================
        # 3. Extract prices
        # ====================================

        new_prices, skipped = extract_prices(
            html
        )

        # ====================================
        # 4. Validate found prices
        # ====================================

        validate(
            new_prices,
            old_prices,
        )

        # ====================================
        # 5. Update prices.json
        # ====================================

        updated_data = update_prices_json(
            old_data,
            new_prices,
            skipped,
        )

        DATA_FILE.write_text(
            json.dumps(
                updated_data,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        # ====================================
        # 6. Print final report
        # ====================================

        print("")
        print("========================================")
        print("UPDATE COMPLETED")
        print("========================================")

        print("")
        print("Updated prices:")

        for key, value in new_prices.items():

            print(
                f"  ✅ {key}: {value}"
            )

        if skipped:

            print("")
            print("Skipped prices:")

            for key in skipped:

                old_value = old_prices.get(
                    key,
                    "N/A",
                )

                print(
                    f"  ⚠️ {key}: "
                    f"not found -> keeping old value "
                    f"({old_value})"
                )

        print("")
        print("Final prices.json values:")

        print(
            json.dumps(
                updated_data["prices"],
                ensure_ascii=False,
                indent=2,
            )
        )

        print("")
        print(
            "SUCCESS: prices.json updated successfully."
        )

        return 0

    except requests.RequestException as exc:

        print(
            f"ERROR: Failed to download official page: "
            f"{exc}",
            file=sys.stderr,
        )

        return 1

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
```
