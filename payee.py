"""Payee name normalization for cleaner YNAB entries."""

import json
import os
import re
from typing import Optional, Tuple

# Common merchant prefixes to remove
PREFIXES_TO_REMOVE = [
    "SP ",      # Square Point of Sale
    "SP *",     # Square variant
    "SQ ",      # Square
    "SQ *",     # Square variant
    "SQ*",      # Square variant
    "TST*",     # Toast
    "TST* ",    # Toast
    "TST ",     # Toast
    "TLF*",     # Unknown POS
    "TLF* ",    # Unknown POS
    "NNT ",     # Unknown POS
    "PAYPAL *", # PayPal
    "PAYPAL*",  # PayPal
    "PP*",      # PayPal
    "GOOGLE *", # Google
    "APPLE.COM/", # Apple
    "AMZN ",    # Amazon
    "AMZN*",    # Amazon
    "AMAZON ",  # Amazon
    "VENMO *",  # Venmo
    "ZELLE *",  # Zelle
    "DOORDASH*", # DoorDash
    "DD ",      # DoorDash
    "UBER* ",   # Uber
    "UBER *",   # Uber
    "LYFT *",   # Lyft
    "VAGARO_*", # Vagaro booking system
    "VAGARO_",  # Vagaro booking system
]

# Business suffixes to remove
SUFFIXES_TO_REMOVE = [
    ", LLC",
    ",LLC",
    " LLC",
    ", INC",
    ",INC",
    " INC",
    ", CORP",
    " CORP",
    ", LTD",
    " LTD",
    " CO",
    " gosq.com",  # Square URL
    " GOSQ.COM",
]

# US State abbreviations and country codes for location removal
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "USA",  # Also match USA as country code
]

# Default payee mappings for common national chains
# These serve as examples and sensible defaults
_DEFAULT_PAYEE_MAPPINGS = {
    # National chains - examples of common mappings
    "STARBUCKS": "Starbucks",
    "TRADER JOE": "Trader Joe's",
    "TRADER JOES": "Trader Joe's",
    "TARGET": "Target",
    "COSTCO": "Costco",
    "WHOLE FOODS": "Whole Foods",
    "AMAZON": "Amazon",
    "AMAZON.COM": "Amazon",
    "NETFLIX": "Netflix",
    "SPOTIFY": "Spotify",
    "APPLE": "Apple",
    "GOOGLE": "Google",
    "MICROSOFT": "Microsoft",
    "MCDONALDS": "McDonald's",
    "MCDONALD'S": "McDonald's",
    "CHIPOTLE": "Chipotle",
    "SUBWAY": "Subway",
    "USPS PO": "USPS",
    "USPS ": "USPS",
}


def _load_payee_mappings() -> dict:
    """
    Load payee mappings from environment variable, merged with defaults.

    Personal/local mappings should be added to your .env file as:
    PAYEE_MAPPINGS={"PATTERN": "Clean Name", "ANOTHER": "Another Name"}

    Personal mappings take precedence over defaults.
    """
    mappings = _DEFAULT_PAYEE_MAPPINGS.copy()

    env_mappings = os.environ.get("PAYEE_MAPPINGS", "")
    if env_mappings:
        try:
            personal = json.loads(env_mappings)
            mappings.update(personal)  # Personal mappings override defaults
        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse PAYEE_MAPPINGS from environment: {e}")

    return mappings


# Load mappings at module import time
PAYEE_MAPPINGS = _load_payee_mappings()


def is_transfer(description: str) -> bool:
    """Check if a transaction is a transfer from FamZoo (money in from Checking)."""
    transfer_patterns = [
        r"Transfer from .+ for .+:",
        r"Transfer to .+ for .+:",
        r"^Transfer from ",
        r"^Transfer to ",
        r"^Direct Deposit",  # FamZoo labels some transfers as Direct Deposit
    ]
    for pattern in transfer_patterns:
        if re.search(pattern, description, re.IGNORECASE):
            return True
    return False


def normalize_payee(description: str) -> str:
    """
    Normalize a payee name for cleaner YNAB entries.

    - Removes common prefixes (SP, SQ, TST, etc.)
    - Removes business suffixes (LLC, INC, etc.)
    - Removes location info (CITY STATE)
    - Applies known mappings
    - Title cases the result
    """
    if not description:
        return description

    original = description
    name = description.strip()

    # Remove common prefixes (sort by length descending to match longer prefixes first)
    name_upper = name.upper()
    for prefix in sorted(PREFIXES_TO_REMOVE, key=len, reverse=True):
        if name_upper.startswith(prefix.upper()):
            name = name[len(prefix):].strip()
            name_upper = name.upper()
            break  # Only remove one prefix

    # Remove any leading asterisks or special characters left over
    name = name.lstrip("*").strip()
    name_upper = name.upper()

    # Check for known mappings EARLY (before location removal)
    # This catches cases like "BERT'S RED APPL SEATTLE WA" -> mapping matches "BERT'S RED APPL"
    for pattern, clean_name in sorted(PAYEE_MAPPINGS.items(), key=lambda x: len(x[0]), reverse=True):
        if pattern.upper() in name_upper or name_upper.startswith(pattern.upper()):
            return clean_name

    # Remove location patterns (CITY STATE at end)
    # Exclude "CO" from location matching since it conflicts with " CO" (Company) suffix
    location_states = [s for s in US_STATES if s != "CO"]
    states_pattern = '|'.join(location_states)
    location_pattern = r'\s+[A-Z][A-Za-z]+\s+(' + states_pattern + r')$'
    name = re.sub(location_pattern, '', name, flags=re.IGNORECASE).strip()

    # Remove business suffixes (LLC, INC, CO, etc.)
    name_upper = name.upper()
    for suffix in SUFFIXES_TO_REMOVE:
        if name_upper.endswith(suffix.upper()):
            name = name[:-len(suffix)].strip()
            name_upper = name.upper()

    # Remove trailing numbers that look like store numbers (e.g., "#1234" or "1234")
    name = re.sub(r'\s*#?\d{3,}$', '', name).strip()

    # Remove terminal identifiers like "- A", "- B", etc.
    name = re.sub(r'\s*-\s*[A-Z]$', '', name, flags=re.IGNORECASE).strip()

    # Check for known mappings (sort by pattern length descending for more specific matches first)
    # Also handles truncated names where FamZoo cuts off the description (e.g., "MADISON PARK PHA")
    name_upper_clean = name.upper().strip()
    for pattern, clean_name in sorted(PAYEE_MAPPINGS.items(), key=lambda x: len(x[0]), reverse=True):
        pattern_upper = pattern.upper()
        if (pattern_upper in name_upper_clean or
            name_upper_clean.startswith(pattern_upper) or
            (len(name_upper_clean) >= 10 and pattern_upper.startswith(name_upper_clean))):
            return clean_name

    # Clean up multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()

    # Title case if all uppercase
    if name.isupper() and len(name) > 2:
        # Smart title case that handles apostrophes
        name = smart_title_case(name)

    return name if name else original


def smart_title_case(text: str) -> str:
    """
    Convert to title case while handling special cases.

    - Handles apostrophes correctly (Bert's not Bert'S)
    - Keeps common acronyms uppercase
    """
    words = text.lower().split()
    result = []

    acronyms = {"atm", "usps", "ups", "qfc", "rei", "ikea"}

    for word in words:
        if word in acronyms:
            result.append(word.upper())
        elif "'" in word:
            # Handle apostrophes - capitalize first letter only
            parts = word.split("'")
            result.append("'".join([parts[0].capitalize()] + parts[1:]))
        else:
            result.append(word.capitalize())

    return " ".join(result)


def parse_transfer_info(description: str) -> Tuple[bool, Optional[str]]:
    """
    Parse transfer information from description.

    Returns:
        Tuple of (is_transfer, transfer_source)
        transfer_source is the name in "Transfer from X for Y:" pattern
    """
    # Match "Transfer from Family for Child:"
    match = re.search(r'Transfer from (.+?) for .+:', description, re.IGNORECASE)
    if match:
        return True, match.group(1).strip()

    # Match simpler "Transfer from X"
    match = re.search(r'Transfer from (.+?)(?:\s|$)', description, re.IGNORECASE)
    if match:
        return True, match.group(1).strip()

    return False, None
