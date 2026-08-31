from __future__ import annotations

import re
import statistics
from typing import Dict, List, Sequence, Tuple

import fitz

_OCR_ENGINE = None
_OCR_UNAVAILABLE = False


def _portrait_blocks(page: fitz.Page) -> List[Dict]:
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
        best_delta = None
        for row in rows:
            row_cy = statistics.mean((it["rect"].y0 + it["rect"].y1) / 2 for it in row)
            delta = abs(cy - row_cy)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                target = row
                best_delta = delta
        if target is None:
            rows.append([item])
        else:
            target.append(item)

    for row in rows:
        row.sort(key=lambda it: it["rect"].x0)
    rows.sort(key=lambda row: statistics.mean(it["rect"].y0 for it in row))
    return rows


def _row_label_band(page: fitz.Page, rows: List[List[Dict]], row_index: int) -> fitz.Rect:
    row = rows[row_index]
    row_bottom = max(item["rect"].y1 for item in row)
    top = row_bottom + 0.5
    if row_index + 1 < len(rows):
        next_top = min(item["rect"].y0 for item in rows[row_index + 1])
        bottom = min(next_top - 3.0, row_bottom + 48.0)
    else:
        bottom = min(page.rect.y1 - 3.0, row_bottom + 48.0)
    if bottom <= top + 6:
        bottom = min(page.rect.y1, top + 34.0)
    return fitz.Rect(page.rect.x0, top, page.rect.x1, bottom)


def _cell_label_clip(
    page: fitz.Page,
    row: List[Dict],
    col_index: int,
    band: fitz.Rect,
) -> fitz.Rect:
    centers = [(item["rect"].x0 + item["rect"].x1) / 2 for item in row]
    cx = centers[col_index]
    gaps = [b - a for a, b in zip(centers, centers[1:]) if b - a > 15]
    pitch = statistics.median(gaps) if gaps else row[col_index]["rect"].width * 1.75
    overlap = min(12.0, pitch * 0.10)

    if col_index > 0:
        left = (centers[col_index - 1] + cx) / 2 - overlap
    else:
        left = cx - pitch / 2 - overlap
    if col_index + 1 < len(row):
        right = (cx + centers[col_index + 1]) / 2 + overlap
    else:
        right = cx + pitch / 2 + overlap

    return fitz.Rect(
        max(page.rect.x0, left),
        band.y0,
        min(page.rect.x1, right),
        band.y1,
    )


def _nearest_index(value: float, centers: Sequence[float]) -> int:
    return min(range(len(centers)), key=lambda idx: abs(centers[idx] - value))


def _pdf_text_for_row(page: fitz.Page, band: fitz.Rect, centers: Sequence[float]) -> List[str]:
    grouped: List[List[Tuple[float, float, str]]] = [[] for _ in centers]
    for word in page.get_text("words", clip=band):
        x0, y0, x1, y1, text = word[:5]
        text = str(text).strip()
        if not text:
            continue
        cx = (float(x0) + float(x1)) / 2
        idx = _nearest_index(cx, centers)
        grouped[idx].append((float(y0), float(x0), text))

    return [
        " ".join(part[2] for part in sorted(parts, key=lambda item: (item[0], item[1]))).strip()
        for parts in grouped
    ]


def _get_ocr_engine():
    global _OCR_ENGINE, _OCR_UNAVAILABLE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if _OCR_UNAVAILABLE:
        return None
    try:
        from rapidocr import RapidOCR

        _OCR_ENGINE = RapidOCR()
        return _OCR_ENGINE
    except Exception:
        _OCR_UNAVAILABLE = True
        return None


def _ocr_text_for_row(
    page: fitz.Page,
    band: fitz.Rect,
    centers: Sequence[float],
    zoom: float = 4.0,
) -> List[str]:
    engine = _get_ocr_engine()
    if engine is None:
        return ["" for _ in centers]

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=band, alpha=False)
        result = engine(pix.tobytes("png"))
        txts = getattr(result, "txts", None)
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None)
        if txts is None or boxes is None:
            return ["" for _ in centers]

        grouped: List[List[Tuple[float, float, str]]] = [[] for _ in centers]
        for index, text in enumerate(txts):
            text = str(text).strip()
            if not text:
                continue
            if scores is not None and index < len(scores) and float(scores[index]) < 0.42:
                continue
            box = boxes[index]
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            pdf_x = band.x0 + (sum(xs) / len(xs)) / zoom
            pdf_y = band.y0 + (sum(ys) / len(ys)) / zoom
            idx = _nearest_index(pdf_x, centers)
            grouped[idx].append((pdf_y, pdf_x, text))

        return [
            " ".join(part[2] for part in sorted(parts, key=lambda item: (item[0], item[1]))).strip()
            for parts in grouped
        ]
    except Exception:
        return ["" for _ in centers]


def _clean_name_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" -–—|,;:")
    value = re.sub(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+|[^A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+$", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _is_upper_name_token(token: str) -> bool:
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", token)
    return bool(letters) and letters == letters.upper()


def split_pronote_name(value: str) -> Tuple[str, str]:
    """Return (first_name, last_name) from Pronote's 'SURNAME Firstname' labels."""
    text = _clean_name_text(value)
    tokens = text.split()
    if not tokens:
        return "", ""

    surname: List[str] = []
    first: List[str] = []
    in_first = False
    for token in tokens:
        if not in_first and _is_upper_name_token(token):
            surname.append(token)
        else:
            in_first = True
            first.append(token)

    if surname and first:
        return " ".join(first).title(), " ".join(surname).title()

    if len(tokens) >= 2:
        return " ".join(tokens[1:]).title(), tokens[0].title()
    return "", tokens[0].title()


def extract_cards(pdf_bytes: bytes) -> List[Dict]:
    """Extract portraits and names from printed Pronote-style trombinoscopes.

    Names are read from real PDF text when available. If the print operation has
    rasterised the labels, a local RapidOCR pass is performed on the whole label
    row and OCR boxes are assigned to the nearest portrait. The visual label crop
    remains as a final fallback.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    cards: List[Dict] = []
    global_index = 0

    for page_number, page in enumerate(doc, start=1):
        items = _portrait_blocks(page)
        rows = _group_rows(items)

        for row_index, row in enumerate(rows):
            band = _row_label_band(page, rows, row_index)
            centers = [(item["rect"].x0 + item["rect"].x1) / 2 for item in row]
            pdf_names = _pdf_text_for_row(page, band, centers)
            missing = [index for index, text in enumerate(pdf_names) if not _clean_name_text(text)]
            ocr_names = ["" for _ in row]
            if missing:
                ocr_names = _ocr_text_for_row(page, band, centers)

            for col_index, item in enumerate(row):
                global_index += 1
                block = item["block"]
                clip = _cell_label_clip(page, row, col_index, band)
                label_pix = page.get_pixmap(matrix=fitz.Matrix(3.5, 3.5), clip=clip, alpha=False)

                pdf_text = _clean_name_text(pdf_names[col_index])
                ocr_text = _clean_name_text(ocr_names[col_index])
                if pdf_text:
                    name_text = pdf_text
                    source = "pdf"
                elif ocr_text:
                    name_text = ocr_text
                    source = "ocr"
                else:
                    name_text = ""
                    source = ""
                first_name, last_name = split_pronote_name(name_text)

                cards.append(
                    {
                        "external_key": f"p{page_number:03d}_n{global_index:03d}",
                        "page": page_number,
                        "position": global_index,
                        "photo_bytes": block["image"],
                        "photo_ext": block.get("ext", "jpg") or "jpg",
                        "label_bytes": label_pix.tobytes("png"),
                        "name_text": name_text,
                        "first_name": first_name,
                        "last_name": last_name,
                        "name_source": source,
                    }
                )

    return cards
