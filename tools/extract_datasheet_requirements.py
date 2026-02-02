from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass

import yaml
from pypdf import PdfReader


@dataclass(frozen=True)
class Candidate:
    id: str
    page: int
    text: str


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def extract_text_by_page(pdf_path: str) -> list[str]:
    reader = PdfReader(pdf_path)
    pages: list[str] = []

    for page in reader.pages:
        txt = page.extract_text() or ""
        pages.append(txt)

    return pages


def generate_candidates(pages: list[str]) -> list[Candidate]:
    """Heuristic candidate extraction.

    Datasheets often encode requirements as specs and bullet points rather than 'shall' statements.
    We look for short-ish lines that contain numbers/units, keywords, or list bullets.
    """

    candidates: list[Candidate] = []
    counter = 1

    keywords = re.compile(
        r"\b(must|shall|should|support|supports|require|required|minimum|maximum|max|min|operating|temperature|humidity|throughput|latency|power|voltage|current|frequency|protocol)\b",
        re.IGNORECASE,
    )
    has_number_or_unit = re.compile(r"(\d|%|\bms\b|\bps\b|\bmhz\b|\bghz\b|\bmbps\b|\bgbps\b|\bdb\b|\bmm\b|\bcm\b|\bkg\b|\bw\b|\bv\b|\ba\b)", re.IGNORECASE)

    for page_index, raw in enumerate(pages, start=1):
        lines = [
            _normalize_whitespace(line)
            for line in (raw or "").splitlines()
            if _normalize_whitespace(line)
        ]

        for line in lines:
            if len(line) < 20:
                continue
            if len(line) > 200:
                continue

            looks_like_bullet = line.startswith(("-", "•", "*"))
            interesting = bool(keywords.search(line) or has_number_or_unit.search(line) or looks_like_bullet)
            if not interesting:
                continue

            cid = f"CAND-{counter:04d}"
            counter += 1
            candidates.append(Candidate(id=cid, page=page_index, text=line))

    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text and spec candidates from a datasheet PDF")
    parser.add_argument("--pdf", required=True, help="Path to the datasheet PDF")
    parser.add_argument(
        "--out-dir",
        default="requirements",
        help="Output directory (default: requirements)",
    )
    args = parser.parse_args()

    pdf_path = args.pdf
    out_dir = args.out_dir

    os.makedirs(out_dir, exist_ok=True)

    pages = extract_text_by_page(pdf_path)

    text_out = os.path.join(out_dir, "eyesight_text_by_page.txt")
    with open(text_out, "w", encoding="utf-8") as f:
        for i, txt in enumerate(pages, start=1):
            f.write(f"===== PAGE {i} =====\n")
            f.write((txt or "").rstrip())
            f.write("\n\n")

    candidates = generate_candidates(pages)

    cand_out = os.path.join(out_dir, "eyesight_candidates.yaml")
    payload = {
        "source": {
            "document": "eyeSight Datasheet",
            "file": os.path.basename(pdf_path),
        },
        "candidates": [
            {
                "id": c.id,
                "page": c.page,
                "excerpt": c.text,
                "notes": "Promote to requirements/eyesight_datasheet.yaml after reviewing",
            }
            for c in candidates
        ],
    }

    with open(cand_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)

    print(f"Wrote: {text_out}")
    print(f"Wrote: {cand_out} ({len(candidates)} candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
