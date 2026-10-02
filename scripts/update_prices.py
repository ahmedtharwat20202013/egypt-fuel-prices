
#!/usr/bin/env python3

"""
Fetch official Egyptian fuel prices and safely update prices.json.

Behavior:
- If a fuel price is found on the official page, update it.
- If a fuel price is missing, keep the previous value.
- Missing individual prices do NOT stop the update.
- Network/source errors DO stop the workflow.
- Suspicious price changes are rejected.
- The product number (80, 92, 95) is NOT treated as the price.
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


# ============================================================
# CONFIGURATION
# ============================================================

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

# These labels are NOT mandatory.
# If one is missing from the official page,
# the previous value in prices.json will remain unchanged.
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

# Reject a suspiciously large change.
MAX_CHANGE = Decimal("0.60")


# ============================================================
# NUMBER HELPERS
# ============================================================

def normalize_digits(value: str) -> str:
    """
    Convert Arabic/Persian digits to normal ASCII digits.
    """

    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"

    result = value

    for arabic, western in zip(
        arabic_digits,
        "0123456789",
    ):
        result = result.replace(
            arabic,
            western,
        )

    for persian, western in zip(
        persian_digits,
        "0123456789",
    ):
        result = result.replace(
            persian,
            western,
        )

    return result


def parse_number(value: str) -> Decimal:
    """
    Parse a decimal number from text.
    """

    value = normalize_digits(value)
    value = value.strip()

    # Convert comma decimal separator to dot.
    value = value.replace(",", ".")

    match = re.search(
        r"\d+(?:\.\d+)?",
        value,
    )

    if not match:
        raise ValueError(
            f"Could not parse number from: {value!r}"
        )

    try:
        return Decimal(
            match.group(0)
        )

    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid number: {value!r}"
        ) from exc


# ============================================================
# FETCH OFFICIAL PAGE
# ============================================================

def fetch_html() -> str:
    """
    Download the official Ministry of Petroleum page.
    """

    print("=" * 60)
    print("Fetching official Egypt fuel prices...")
    print("=" * 60)

    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    html = response.text

    if len(html) < 10_000:
        raise RuntimeError(
            "Official page response is unexpectedly small."
        )

    print(
        f"SUCCESS: official page downloaded "
        f"({len(html):,} characters)"
    )

    return html


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_price_after_label(
    text: str,
    labels: list[str],
) -> Decimal | None:
    """
    Find a fuel label and then search ONLY after the label.

    This prevents:
        بنزين 80  -> 80

    from being interpreted as the price.

    Example:
        بنزين 80 15.75
        ^ label  ^ price
    """

    normalized_text = normalize_digits(text)

    for label in labels:

        normalized_label = normalize_digits(label)

        position = normalized_text.find(
            normalized_label
        )

        if position < 0:
            continue

        # Everything AFTER the product name.
        after_label = normalized_text[
            position + len(normalized_label):
        ]

        # Only inspect a reasonable window.
        window = after_label[:200]

        # Find numbers after the label.
        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            window,
        )

        for raw_number in numbers:

            try:
                number = parse_number(
                    raw_number
                )

            except ValueError:
                continue

            if (
                MIN_PRICE
                <= number
                <= MAX_PRICE
            ):
                return number

    return None


def extract_price_from_row(
    row_text: str,
    labels: list[str],
) -> Decimal | None:
    """
    Extract a price from one table row.

    Only numbers AFTER the product label are considered.
    """

    for label in labels:

        if label not in row_text:
            continue

        price = extract_price_after_label(
            row_text,
            [label],
        )

        if price is not None:
            return price

    return None


def extract_price_from_full_text(
    text: str,
    labels: list[str],
) -> Decimal | None:
    """
    Fallback extraction from the complete visible page text.
    """

    return extract_price_after_label(
        text,
        labels,
    )


def extract_prices(
    html: str,
) -> tuple[dict[str, Decimal], list[str]]:
    """
    Extract all available fuel prices.

    Returns:
        found_prices
        skipped_keys
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # Get table rows
    # --------------------------------------------------------

    rows = soup.find_all("tr")

    row_texts = [
        " ".join(
            row.stripped_strings
        )
        for row in rows
    ]

    # --------------------------------------------------------
    # Get visible page text
    # --------------------------------------------------------

    visible_text = " ".join(
        soup.stripped_strings
    )

    found_prices: dict[str, Decimal] = {}

    skipped: list[str] = []

    print("")
    print("=" * 60)
    print("Searching for fuel prices...")
    print("=" * 60)

    # --------------------------------------------------------
    # Search every fuel type
    # --------------------------------------------------------

    for key, labels in FUEL_LABELS.items():

        price: Decimal | None = None

        # ----------------------------------------------------
        # 1. Search table rows first
        # ----------------------------------------------------

        for row_text in row_texts:

            price = extract_price_from_row(
                row_text,
                labels,
            )

            if price is not None:
                break

        # ----------------------------------------------------
        # 2. Fallback to complete visible text
        # ----------------------------------------------------

        if price is None:

            price = extract_price_from_full_text(
                visible_text,
                labels,
            )

        # ----------------------------------------------------
        # 3. Found
        # ----------------------------------------------------

        if price is not None:

            found_prices[key] = price

            print(
                f"FOUND   {key:<15} = {price}"
            )

        # ----------------------------------------------------
        # 4. Missing
        # ----------------------------------------------------

        else:

            skipped.append(key)

            print(
                f"SKIPPED {key:<15} "
                f"= price not found"
            )

    return found_prices, skipped


# ============================================================
# VALIDATION
# ============================================================

def validate_prices(
    new_prices: dict[str, Decimal],
    old_prices: dict,
) -> None:
    """
    Validate only prices that were actually found.
    """

    # If absolutely nothing was found,
    # something is probably wrong with the source.
    if not new_prices:

        raise RuntimeError(
            "No fuel prices were found on the official page."
        )

    print("")
    print("=" * 60)
    print("Validating extracted prices...")
    print("=" * 60)

    # --------------------------------------------------------
    # Range validation
    # --------------------------------------------------------

    for key, value in new_prices.items():

        if not (
            MIN_PRICE
            <= value
            <= MAX_PRICE
        ):

            raise RuntimeError(
                f"Validation failed: "
                f"{key}={value} is outside "
                f"the allowed range."
            )

        print(
            f"VALID   {key:<15} = {value}"
        )

    # --------------------------------------------------------
    # Change validation
    # --------------------------------------------------------

    print("")
    print("Checking for suspicious price changes...")

    for key, new_value in new_prices.items():

        old_raw = old_prices.get(key)

        # No previous value.
        if old_raw is None:
            print(
                f"NEW     {key:<15} = {new_value}"
            )
            continue

        try:

            old_value = Decimal(
                str(old_raw)
            )

        except InvalidOperation as exc:

            raise RuntimeError(
                f"Invalid old price for "
                f"{key}: {old_raw!r}"
            ) from exc

        if old_value <= 0:
            continue

        change = (
            abs(new_value - old_value)
            / old_value
        )

        percentage = change * Decimal("100")

        print(
            f"CHANGE  {key:<15} "
            f"{old_value} -> {new_value} "
            f"({percentage:.2f}%)"
        )

        if change > MAX_CHANGE:

            raise RuntimeError(
                f"Validation failed: "
                f"{key} changed by more than 60% "
                f"({old_value} -> {new_value}). "
                f"Manual review required."
            )


# ============================================================
# UPDATE JSON
# ============================================================

def update_prices_json(
    old_data: dict,
    new_prices: dict[str, Decimal],
) -> dict:
    """
    Merge new prices with old prices.

    Important:
    Missing prices remain unchanged.
    """

    old_prices = dict(
        old_data.get(
            "prices",
            {},
        )
    )

    # --------------------------------------------------------
    # Update ONLY prices that were found.
    # --------------------------------------------------------

    for key, value in new_prices.items():

        old_prices[key] = float(
            value
        )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Final prices
    # --------------------------------------------------------

    old_data["prices"] = old_prices

    return old_data


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    try:

        # ====================================================
        # 1. Check prices.json
        # ====================================================

        if not DATA_FILE.exists():

            raise RuntimeError(
                f"prices.json not found: "
                f"{DATA_FILE}"
            )

        old_data = json.loads(
            DATA_FILE.read_text(
                encoding="utf-8"
            )
        )

        if "prices" not in old_data:

            raise RuntimeError(
                "prices.json does not contain "
                "a 'prices' object."
            )

        old_prices = old_data["prices"]

        print("=" * 60)
        print("Existing prices:")
        print("=" * 60)

        print(
            json.dumps(
                old_prices,
                ensure_ascii=False,
                indent=2,
            )
        )

        # ====================================================
        # 2. Download official source
        # ====================================================

        html = fetch_html()

        # ====================================================
        # 3. Extract prices
        # ====================================================

        new_prices, skipped = extract_prices(
            html
        )

        # ====================================================
        # 4. Validate
        # ====================================================

        validate_prices(
            new_prices,
            old_prices,
        )

        # ====================================================
        # 5. Merge with old data
        # ====================================================

        updated_data = update_prices_json(
            old_data,
            new_prices,
        )

        # ====================================================
        # 6. Write prices.json
        # ====================================================

        DATA_FILE.write_text(
            json.dumps(
                updated_data,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        # ====================================================
        # 7. Report
        # ====================================================

        print("")
        print("=" * 60)
        print("UPDATE COMPLETED SUCCESSFULLY")
        print("=" * 60)

        print("")
        print("Updated prices:")

        for key, value in new_prices.items():

            old_value = old_prices.get(
                key
            )

            if old_value is None:

                print(
                    f"  NEW  {key}: "
                    f"{value}"
                )

            else:

                print(
                    f"  OK   {key}: "
                    f"{old_value} -> {value}"
                )

        # ----------------------------------------------------
        # Skipped prices
        # ----------------------------------------------------

        if skipped:

            print("")
            print(
                "Prices not found "
                "(old values kept):"
            )

            for key in skipped:

                old_value = old_prices.get(
                    key,
                    "N/A",
                )

                print(
                    f"  KEEP {key}: "
                    f"{old_value}"
                )

        # ----------------------------------------------------
        # Final JSON
        # ----------------------------------------------------

        print("")
        print("=" * 60)
        print("Final prices.json values:")
        print("=" * 60)

        print(
            json.dumps(
                updated_data["prices"],
                ensure_ascii=False,
                indent=2,
            )
        )

        print("")
        print(
            "SUCCESS: prices.json "
            "has been updated."
        )

        return 0

    # ========================================================
    # NETWORK ERROR
    # ========================================================

    except requests.RequestException as exc:

        print(
            "",
            file=sys.stderr,
        )

        print(
            "=" * 60,
            file=sys.stderr,
        )

        print(
            "ERROR: Could not download "
            "the official page.",
            file=sys.stderr,
        )

        print(
            str(exc),
            file=sys.stderr,
        )

        print(
            "=" * 60,
            file=sys.stderr,
        )

        return 1

    # ========================================================
    # OTHER ERROR
    # ========================================================

    except Exception as exc:

        print(
            "",
            file=sys.stderr,
        )

        print(
            "=" * 60,
            file=sys.stderr,
        )

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        print(
            "=" * 60,
            file=sys.stderr,
        )

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    sys.exit(main())
```
