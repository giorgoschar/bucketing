"""
Receipt text parser — extracts structured fields from raw OCR text.
Supports Greek (ell) and English receipts.
No external dependencies.
"""
import re
from datetime import date, datetime
from difflib import SequenceMatcher


# ---------------------------------------------------------------------------
# Greek month name mapping
# ---------------------------------------------------------------------------
_GREEK_MONTHS = {
    "ΙΑΝΟΥΑΡΙΟΥ": 1, "ΙΑΝΟΥΑΡΙΟΣ": 1, "ΙΑΝ": 1,
    "ΦΕΒΡΟΥΑΡΙΟΥ": 2, "ΦΕΒΡΟΥΑΡΙΟΣ": 2, "ΦΕΒ": 2,
    "ΜΑΡΤΙΟΥ": 3, "ΜΑΡΤΙΟΣ": 3, "ΜΑΡ": 3,
    "ΑΠΡΙΛΙΟΥ": 4, "ΑΠΡΙΛΙΟΣ": 4, "ΑΠΡ": 4,
    "ΜΑΪΟΥ": 5, "ΜΑΙΟΥ": 5, "ΜΑΪΟΣ": 5, "ΜΑΙ": 5,
    "ΙΟΥΝΙΟΥ": 6, "ΙΟΥΝΙΟΣ": 6, "ΙΟΥ": 6,
    "ΙΟΥΛΙΟΥ": 7, "ΙΟΥΛΙΟΣ": 7,
    "ΑΥΓΟΥΣΤΟΥ": 8, "ΑΥΓΟΥΣΤΟΣ": 8, "ΑΥΓ": 8,
    "ΣΕΠΤΕΜΒΡΙΟΥ": 9, "ΣΕΠΤΕΜΒΡΙΟΣ": 9, "ΣΕΠ": 9,
    "ΟΚΤΩΒΡΙΟΥ": 10, "ΟΚΤΩΒΡΙΟΣ": 10, "ΟΚΤ": 10,
    "ΝΟΕΜΒΡΙΟΥ": 11, "ΝΟΕΜΒΡΙΟΣ": 11, "ΝΟΕ": 11,
    "ΔΕΚΕΜΒΡΙΟΥ": 12, "ΔΕΚΕΜΒΡΙΟΣ": 12, "ΔΕΚ": 12,
}

# ---------------------------------------------------------------------------
# Keywords that label the total line (Greek + English)
# ---------------------------------------------------------------------------
_TOTAL_KEYWORDS = [
    # Greek
    "ΣΥΝΟΛΟ ΠΛΗΡΩΤΕΟ", "ΤΕΛΙΚΟ ΣΥΝΟΛΟ", "ΣΥΝΟΛΟ", "ΠΛΗΡΩΤΕΟ", "ΠΛΗΡΩΤΕΑ",
    "ΓΕΝΙΚΟ ΣΥΝΟΛΟ", "ΣΥΝΟΛΙΚΗ ΑΞΙΑ", "ΤΕΛΙΚΗ ΑΞΙΑ", "ΑΞΙΑ", "ΠΟΣΟ",
    # English
    "GRAND TOTAL", "TOTAL DUE", "AMOUNT DUE", "TOTAL PAYABLE", "TOTAL",
    "BALANCE DUE", "NET TOTAL", "SUM",
]
# Sort by descending length so multi-word phrases match first
_TOTAL_KEYWORDS.sort(key=len, reverse=True)

# ---------------------------------------------------------------------------
# Category hint rules: (list_of_keywords, hint_name)
# ---------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[list[str], str]] = [
    # Food / groceries
    (["ΣΟΥΠΕΡ ΜΑΡΚΕΤ", "SUPER MARKET", "SUPERMARKET", "ΑΒΑΞ", "SKLAVENITIS",
      "ΣΚΛΑΒΕΝΙΤΗΣ", "ΣΠΑΡ", "SPAR", "ΜΑΡΙΝΟΠΟΥΛΟΣ", "LIDL", "ALDI", "AB ΒΑΣΙΛΟΠΟΥΛΟΣ",
      "ΒΑΣΙΛΟΠΟΥΛΟΣ", "ΓΑΛΑΞΙΑΣ", "BAZAAR", "ΜΙΝΙΜΑΡΚΕΤ", "MINIMARKET"], "groceries"),
    # Dining out
    (["ΕΣΤΙΑΤΟΡΙΟ", "ΤΑΒΕΡΝΑ", "ΜΕΖΕΔΟΠΩΛΕΙΟ", "ΚΑΦΕ", "ΚΑΦΕΤΕΡΙΑ", "CAFE",
      "COFFEE", "RESTAURANT", "PIZZERIA", "ΠΙΤΣΑΡΙΑ", "ΜΠΑΡ", "BAR", "GRILL",
      "ΣΟΥΒΛΑΤΖΙΔΙΚΟ", "FAST FOOD", "DELIVERY", "EFOOD", "WOLT", "FOODY",
      "ΑΝΑΨΥΚΤΗΡΙΟ", "ΑΡΤΟΠΟΙΕΙΟ", "ΑΡΤΟΖΑΧΑΡΟΠΛΑΣΤΕΙΟ", "ΖΑΧΑΡΟΠΛΑΣΤΕΙΟ",
      "ΖΥΜΑΡΙΑ", "ΖΥΜΑΡΗ", "ΨΗΤΟΠΩΛΕΙΟ", "ΣΝΑΚ", "SNACK", "ΚΥΛΙΚΕΙΟ",
      "ESPRESSO", "FREDDO", "FRAPPE", "CAPPUCCINO"], "food & drink"),
    # Transport / fuel
    (["ΒΕΝΖΙΝΑΔΙΚΟ", "ΠΡΑΤΗΡΙΟ", "SHELL", "BP", "AVIN", "ΕΛΙΝ", "ELIN", "REVOIL",
      "ΜΟΤΟΡ ΟΙΛ", "MOTOR OIL", "FUEL", "ΕΛΒΟΚ", "PARKING", "ΠΑΡΚΙΝΓΚ",
      "ΚΤΕΛ", "ΑΤΤΙΚΟ ΜΕΤΡΟ", "METRO", "TAXI", "UBER", "BEAT"], "transport"),
    # Health / pharmacy
    (["ΦΑΡΜΑΚΕΙΟ", "PHARMACY", "APOTHEKE", "ΦΑΡΜΑ", "PHARMA",
      "ΚΛΙΝΙΚΗ", "ΝΟΣΟΚΟΜΕΙΟ", "ΙΑΤΡΕΙΟ", "DOCTOR", "DENTAL"], "health"),
    # Utilities / telecom
    (["ΔΕΗ", "ΕΥΔΑΠ", "ΔΕΠΑ", "COSMOTE", "VODAFONE", "WIND", "NOVA",
      "ΤΗΛΕΦΩΝΟ", "ΡΕΥΜΑ", "ΝΕΡΟ", "INTERNET", "TELECOM"], "utilities"),
    # Entertainment
    (["CINEMA", "ΚΙΝΗΜΑΤΟΓΡΑΦΟΣ", "ΘΕΑΤΡΟ", "THEATRE", "CONCERT", "SPOTIFY",
      "NETFLIX", "YOUTUBE", "STEAM", "GAMING", "DISNEY", "AMAZON PRIME"], "entertainment"),
    # Shopping / clothing
    (["ZARA", "H&M", "PULL", "MANGO", "ΈΝΔΥΣΗ", "ΡΟΥΧΑ", "ΠΑΠΟΥΤΣΙΑ",
      "SHOES", "CLOTHING", "BOUTIQUE", "JUMBO", "ИКЕА", "IKEA", "LEROY"], "shopping"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common Tesseract confusions on thermal Greek receipts.
# Corrected before parsing so keyword matching still works.
_OCR_FIXES: list[tuple[str, str]] = [
    # Greek total keywords corrupted by digit/letter swaps
    (r"[5Ss][Y\u03a5][Nn][O\u039f][\u039blL][O\u039f]", "\u03a3\u03a5\u039d\u039f\u039b\u039f"),  # 5YNOΛO / SYNOЛО -> ΣΥΝΟΛΟ
    (r"[Pp][Ll\u039b][Hh\u0397][Pp\u03a1][Oo\u03a9][Tt\u03a4][Ee\u0395][Oo\u039f]", "\u03a0\u039b\u0397\u03a1\u03a9\u03a4\u0395\u039f"),
    # Lowercase l between Greek capitals -> iota
    (r"(?<=[\u0391-\u03a9])l(?=[\u0391-\u03a9])", "\u0399"),
    # Trailing E after a number likely means euro
    (r"(?<=\d) *E(?=[\s,.]|$)", "\u20ac"),
]


def _clean_ocr_noise(text: str) -> str:
    """Correct common Tesseract misreads on Greek thermal receipts."""
    for pattern, replacement in _OCR_FIXES:
        try:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        except re.error:
            pass
    return text


def _normalize(text: str) -> str:
    """Upper-case + collapse whitespace for easier matching."""
    return re.sub(r"\s+", " ", text.upper().strip())


def _parse_number(s: str) -> float | None:
    """Parse a Greek/European formatted number (1.234,56 or 1234.56 or 1234,56)."""
    s = s.strip()
    # Remove thousands separators: 1.234,56 -> 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# Greek VAT rates — these appear after prices and must not be taken as the total
_GREEK_VAT_RATES: frozenset[float] = frozenset({6.0, 6.5, 13.0, 24.0})


def _strip_vat_percentages(s: str) -> str:
    """Remove NN,NN% / NN.NN% / NN% patterns so VAT rates don't pollute number lists."""
    return re.sub(r"\d+[,.]\d+\s*%|\d+\s*%", " ", s)


def _extract_numbers_near(text: str, keyword: str) -> list[float]:
    """Find all numbers on the same line(s) as keyword."""
    results = []
    norm = _normalize(text)
    kw_pos = norm.find(keyword)
    if kw_pos == -1:
        return results
    # Take 250 chars from keyword — receipts often put the amount on the next line
    # e.g. ΣΥΝΟΛΟ\nΠΙΣΤ.ΚΑΡΤΑ    4,30 ΕΥΡΩ
    snippet = _strip_vat_percentages(norm[kw_pos: kw_pos + 250])
    for m in re.finditer(r"\d[\d.,]*\d|\d", snippet):
        val = _parse_number(m.group())
        if val is not None and val > 0:
            results.append(val)
    return results


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def _extract_amount(text: str) -> float | None:
    norm = _normalize(text)
    candidates: list[float] = []

    for kw in _TOTAL_KEYWORDS:
        nums = _extract_numbers_near(norm, kw)
        if nums:
            # The total is usually the last / largest number on the total line
            candidates.extend(nums)
            break  # stop at the first matching keyword

    if not candidates:
        # Fallback: largest number in the document that looks like a price (> 0.5)
        for m in re.finditer(r"\d[\d.,]*\d|\d", norm):
            val = _parse_number(m.group())
            if val is not None and val > 0.5:
                candidates.append(val)

    if not candidates:
        return None

    # Filter out implausible values: years, large codes, and Greek VAT rates (6/13/24)
    reasonable = [
        v for v in candidates
        if 0.01 <= v <= 99_999
        and v not in _GREEK_VAT_RATES
        and not (1990 <= v <= 2100)  # year-like numbers
    ]
    return max(reasonable) if reasonable else None


def _extract_currency(text: str) -> str:
    norm = _normalize(text)
    if "€" in norm or "EUR" in norm or "ΕΥΡΩ" in norm:
        return "EUR"
    if "$" in norm or "USD" in norm:
        return "USD"
    if "£" in norm or "GBP" in norm:
        return "GBP"
    return "EUR"  # default for Greece


def _extract_date(text: str) -> str | None:
    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # YYYY-MM-DD (ISO)
    m = re.search(r"\b(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # DD ΜΗΝΑΣ YYYY (Greek month names)
    norm = _normalize(text)
    for month_name, month_num in _GREEK_MONTHS.items():
        pattern = rf"\b(\d{{1,2}})\s+{re.escape(month_name)}\s+(\d{{4}})\b"
        m = re.search(pattern, norm)
        if m:
            d, y = int(m.group(1)), int(m.group(2))
            if 1 <= d <= 31 and 2000 <= y <= 2100:
                return f"{y:04d}-{month_num:02d}-{d:02d}"

    return None


# Prefixes that identify boilerplate lines printed on every Greek fiscal receipt.
# None of these are the merchant name.
_MERCHANT_SKIP_PREFIXES: tuple[str, ...] = (
    "ΦΟΡΟΛΟΓΙΚΗ ΑΠΟΔΕΙΞΗ", "ΑΠΟΔΕΙΞΗ ΛΙΑΝΙΚΗΣ", "ΑΠΟΔΕΙΞΗ ΛΙΑΝΙΚOY",
    "FISCAL", "RECEIPT",
    "ΑΦΜ", "ΔΟΥ", "ΥΠ:", "ΥΠ.", "ΕΔ:", "ΕΔ.",
    "ΜΗΧΑΝΗ", "ΩΡΑ:", "ΩΡΑ ",
    "ΠΑΡΑΣΚΕΥΗ", "ΣΑΒΒΑΤΟ", "ΚΥΡΙΑΚΗ", "ΔΕΥΤΕΡΑ", "ΤΡΙΤΗ", "ΤΕΤΑΡΤΗ", "ΠΕΜΠΤΗ",
    "ΗΜΕΡΟΜΗΝΙΑ", "ΗΜΕΡΗΣΙΟΣ",
    "ΑΡΙΘΜΟΣ", "ΑΡΙΘ.",
    "ΠΛΗΡΩΜΗ", "ΠΙΣΤ.", "ΜΕΤΡΗΤΑ", "CASH",
    "ECB", "QR",
)


def _extract_merchant(text: str) -> str | None:
    """
    Return the first non-boilerplate, non-numeric line — this is the merchant name.
    Greek fiscal receipts always open with "ΦΟΡΟΛΟΓΙΚΗ ΑΠΟΔΕΙΞΗ – ΕΝΑΡΞΗ"
    followed by the actual business name on line 2.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        norm_line = line.upper()
        # Skip Greek fiscal / POS boilerplate
        if any(norm_line.startswith(p) for p in _MERCHANT_SKIP_PREFIXES):
            continue
        # Skip lines that are mostly numbers / separators / codes
        if re.match(r"^[\d\s/.\-:,€$£%=_*|]+$", line):
            continue
        # Skip typical address lines: starts with letters then digits (e.g. "ΦΡΑΓΚΟΥΔΗ 9")
        if re.match(r"^[\w\s]+\d+", line) and len(line) < 35 and re.search(r"\d", line):
            # Only skip if it looks like a street address (has a number embedded short line)
            if re.search(r"\b\d{1,3}\b", line):
                continue
        # Skip very short lines
        if len(line) < 3:
            continue
        return line
    return None


def _extract_category_hint(text: str) -> str | None:
    norm = _normalize(text)
    for keywords, hint in _CATEGORY_RULES:
        for kw in keywords:
            if kw in norm:
                return hint
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_receipt_text(text: str) -> dict:
    """
    Parse raw OCR text from a receipt/invoice.
    Returns a dict with keys:
      amount      (float | None)
      currency    (str)  — default "EUR"
      date        (str | None)  — ISO format YYYY-MM-DD
      merchant    (str | None)
      category_hint (str | None)
    """
    text = _clean_ocr_noise(text)
    return {
        "amount": _extract_amount(text),
        "currency": _extract_currency(text),
        "date": _extract_date(text),
        "merchant": _extract_merchant(text),
        "category_hint": _extract_category_hint(text),
    }


def match_category(hint: str | None, categories: list) -> str | None:
    """
    Fuzzy-match a category_hint string against a list of Category ORM objects.
    Returns the best-matching category.id or None.
    """
    if not hint or not categories:
        return None

    hint_lower = hint.lower()
    best_id = None
    best_ratio = 0.0

    for cat in categories:
        name_lower = cat.name.lower()
        # Exact substring match wins immediately
        if hint_lower in name_lower or name_lower in hint_lower:
            return cat.id
        ratio = SequenceMatcher(None, hint_lower, name_lower).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = cat.id

    # Only return a match if similarity is reasonable
    return best_id if best_ratio >= 0.4 else None
