from __future__ import annotations

import statistics
from typing import Dict, List

import fitz


def _portrait_blocks(page: fitz.Page) -> List[Dict]:
    """Return the dominant repeated portrait-image family on a Pronote-like page."""
    page_dict = page.get_text("dict")
    images = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 1 or not block.get("image"):
            continue
        rect = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if rect.width < 28 or rect.height < 40:
            continue
        aspect = rect.width / max(rect.height, 1)
        if not 0.42 <= aspect <= 1.25:
            continue
        images.append({"block": block, "rect": rect})

    if not images:
        return []

    # Portraits are normally a repeated size. Use a tolerant family because
    # placeholders / crops can be a few points shorter than regular portraits.
    def same_family(a: Dict, b: Dict) -> bool:
        ar, br = a["rect"], b["rect"]
        return (
            abs(ar.width - br.width) <= max(7.0, br.width * 0.15)
            and abs(ar.height - br.height) <= max(9.0, br.height * 0.15)
        )

    families = [[other for other in images if same_family(seed, other)] for seed in images]
    dominant = max(families, key=len)
    if len(dominant) >= 2:
        images = dominant

    return sorted(images, key=lambda item: (item["rect"].y0, item["rect"].x0))


def _group_rows(items: List[Dict]) -> List[List[Dict]]:
    if not items:
        return []
    median_height = statistics.median(item["rect"].height for item in items)
    tolerance = max(8.0, median_height * 0.35)
    rows: List[List[Dict]] = []

    for item in sorted(items, key=lambda it: (it["rect"].y0, it["rect"].x0)):
        cy = (item["rect"].y0 + item["rect"].y1) / 2
        target = None
        for row in rows:
            row_cy = statistics.mean((it["rect"].y0 + it["rect"].y1) / 2 for it in row)
            if abs(cy - row_cy) <= tolerance:
                target = row
                break
        if target is None:
            rows.append([item])
        else:
            target.append(item)

    for row in rows:
        row.sort(key=lambda it: it["rect"].x0)
    return rows


def _label_clip(page: fitz.Page, rows: List[List[Dict]], row_index: int, col_index: int) -> fitz.Rect:
    row = rows[row_index]
    item = row[col_index]
    rect = item["rect"]
    cx = (rect.x0 + rect.x1) / 2

    centers = [(it["rect"].x0 + it["rect"].x1) / 2 for it in row]
    gaps = [b - a for a, b in zip(centers, centers[1:]) if b - a > 20]
    default_gap = statistics.median(gaps) if gaps else rect.width * 1.65

    if col_index > 0:
        prev_cx = centers[col_index - 1]
        left = (prev_cx + cx) / 2
    else:
        left = cx - default_gap / 2

    if col_index + 1 < len(row):
        next_cx = centers[col_index + 1]
        right = (cx + next_cx) / 2
    else:
        right = cx + default_gap / 2

    left = max(page.rect.x0, left)
    right = min(page.rect.x1, right)

    label_top = rect.y1 + 1.0
    if row_index + 1 < len(rows):
        next_top = min(it["rect"].y0 for it in rows[row_index + 1])
        label_bottom = min(next_top - 4.0, rect.y1 + 36.0)
    else:
        label_bottom = min(page.rect.y1 - 4.0, rect.y1 + 38.0)

    if label_bottom <= label_top + 5:
        label_bottom = min(page.rect.y1, label_top + 30)

    return fitz.Rect(left, label_top, right, label_bottom)


def extract_cards(pdf_bytes: bytes) -> List[Dict]:
    """Extract N portrait cards without assuming a fixed number or grid shape.

    The portrait is taken from the PDF image block. The visual name label below
    it is rendered separately, so the app can reveal the answer even if the
    printed PDF rasterized the name and no text extraction is possible.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    cards: List[Dict] = []
    global_index = 0

    for page_number, page in enumerate(doc, start=1):
        items = _portrait_blocks(page)
        rows = _group_rows(items)
        for row_index, row in enumerate(rows):
            for col_index, item in enumerate(row):
                global_index += 1
                block = item["block"]
                clip = _label_clip(page, rows, row_index, col_index)
                label_pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
                cards.append(
                    {
                        "external_key": f"p{page_number:03d}_n{global_index:03d}",
                        "page": page_number,
                        "position": global_index,
                        "photo_bytes": block["image"],
                        "photo_ext": block.get("ext", "jpg") or "jpg",
                        "label_bytes": label_pix.tobytes("png"),
                    }
                )

    return cards
