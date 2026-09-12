"""
Extracts text and candidate engineering parameters (spans, loads, material
grade, section dimensions) from an uploaded PDF so they can be routed into
the structural_engine calculators instead of being guessed by the LLM.

This is a best-effort regex/heuristic extractor, not a drawing-recognition
system - it works on text-based PDFs (specs, calc sheets, reports) and on
scanned drawings only to the extent OCR text is embedded.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pdfplumber
from pydantic import BaseModel


class ExtractedQuantity(BaseModel):
    label: str
    value: float
    unit: str
    raw_match: str


class PdfExtractionResult(BaseModel):
    filename: str
    page_count: int
    text_excerpt: str
    tables_found: int
    quantities: list[ExtractedQuantity]


# label -> (regex, unit)
_PATTERNS: dict[str, tuple[str, str]] = {
    "span": (r"span[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(m|mm|ft)\b", ""),
    "length": (r"length[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(m|mm|ft)\b", ""),
    "load_udl": (r"(?:udl|uniformly distributed load|w\s*=)[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(kn/m|n/m|kg/m)\b", ""),
    "load_point": (r"(?:point load|concentrated load|p\s*=)[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(kn|n|kg)\b", ""),
    "width": (r"(?:width|breadth|b\s*=)[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(m|mm)\b", ""),
    "depth": (r"(?:depth|d\s*=)[^0-9]{0,15}([\d]+(?:\.\d+)?)\s*(m|mm)\b", ""),
    "grade_concrete": (r"\bM\s?(\d{2,3})\b", "grade"),
    "grade_steel": (r"\bFe\s?(\d{3})\b", "grade"),
}

_UNIT_TO_SI = {
    "m": 1.0,
    "mm": 0.001,
    "ft": 0.3048,
    "kn": 1000.0,
    "n": 1.0,
    "kg": 9.80665,
    "kn/m": 1000.0,
    "n/m": 1.0,
    "kg/m": 9.80665,
    "grade": 1.0,
}


def _extract_quantities(text: str) -> list[ExtractedQuantity]:
    found: list[ExtractedQuantity] = []
    lower = text.lower()
    for label, (pattern, _unused) in _PATTERNS.items():
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            groups = match.groups()
            if len(groups) == 2:
                raw_value, unit = groups
                unit = unit.lower()
            else:
                raw_value, unit = groups[0], "grade"
            try:
                value = float(raw_value)
            except ValueError:
                continue
            si_value = value * _UNIT_TO_SI.get(unit, 1.0)
            found.append(
                ExtractedQuantity(
                    label=label,
                    value=si_value,
                    unit="SI" if unit != "grade" else "grade",
                    raw_match=match.group(0).strip(),
                )
            )
    return found


def parse_pdf(file_bytes: bytes, filename: str) -> PdfExtractionResult:
    text_parts: list[str] = []
    table_count = 0
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            tables = page.extract_tables()
            table_count += len(tables)

    full_text = "\n".join(text_parts)
    quantities = _extract_quantities(full_text)

    return PdfExtractionResult(
        filename=filename,
        page_count=page_count,
        text_excerpt=full_text[:4000],
        tables_found=table_count,
        quantities=quantities,
    )
