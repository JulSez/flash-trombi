from __future__ import annotations

import hashlib
import io
import os
import pickle
import re
import statistics
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import fitz
from PIL import Image, ImageDraw

_OCR_ENGINE = None
_OCR_UNAVAILABLE = False
_IMPORT_CACHE_VERSION = "row-batch-v1"
_FAST_ZOOM = 3.2
_FALLBACK_SCALE = 1.45


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
        bottom = min(next_top - 3.0, row_bottom + 52.0)
    else:
        bottom = min(page.rect.y1 - 3.0, row_bottom + 52.0)
    if bottom <= top + 6:
        bottom = min(page.rect.y1, top + 38.0)
    return fitz.Rect(page.rect.x0, top, page.rect.x1, bottom)


def _cell_ranges(page: fitz.Page, row: List[Dict]) -> Tuple[List[float], List[Tuple[float, float]]]:
    """Return one horizontal label cell per portrait."""
    anchors = [float(item["rect"].x0) for item in row]
    if not anchors:
        return [], []

    if len(anchors) == 1:
        width = max(float(row[0]["rect"].width) * 2.2, 120.0)
        return anchors, [
            (
                max(float(page.rect.x0), anchors[0]),
                min(float(page.rect.x1), anchors[0] + width),
            )
        ]

    gaps = [right - left for left, right in zip(anchors, anchors[1:])]
    pitch = statistics.median(gaps)
    ranges: List[Tuple[float, float]] = []
    for index, left in enumerate(anchors):
        right = anchors[index + 1] if index + 1 < len(anchors) else left + pitch
        ranges.append(
            (
                max(float(page.rect.x0), left),
                min(float(page.rect.x1), right),
            )
        )
    return anchors, ranges


def _cell_label_clip(
    page: fitz.Page,
    row: List[Dict],
    col_index: int,
    band: fitz.Rect,
    *,
    visual_margin: bool = False,
) -> fitz.Rect:
    _, ranges = _cell_ranges(page, row)
    left, right = ranges[col_index]
    return fitz.Rect(left, band.y0, right, band.y1)


def _nearest_index(value: float, anchors: Sequence[float]) -> int:
    return min(range(len(anchors)), key=lambda idx: abs(anchors[idx] - value))


def _assign_cell(
    x0: float,
    x1: float,
    anchors: Sequence[float],
    ranges: Sequence[Tuple[float, float]],
) -> int:
    """Assign a text fragment to the card whose left edge owns it."""
    if not anchors:
        return 0

    nearest = _nearest_index(x0, anchors)
    if abs(float(x0) - float(anchors[nearest])) <= 3.0:
        return nearest

    for index in range(len(anchors) - 1, -1, -1):
        if float(x0) >= float(anchors[index]):
            return index
    return 0


def _group_fragments_into_lines(
    fragments: Sequence[Tuple[float, float, float, float, str]],
) -> List[str]:
    if not fragments:
        return []

    heights = [max(1.0, y1 - y0) for _, y0, _, y1, _ in fragments]
    tolerance = max(2.0, statistics.median(heights) * 0.65)
    rows: List[List[Tuple[float, float, float, float, str]]] = []

    for fragment in sorted(fragments, key=lambda item: ((item[1] + item[3]) / 2, item[0])):
        cy = (fragment[1] + fragment[3]) / 2
        target = None
        best_delta = None
        for row in rows:
            row_cy = statistics.mean((item[1] + item[3]) / 2 for item in row)
            delta = abs(cy - row_cy)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                target = row
                best_delta = delta
        if target is None:
            rows.append([fragment])
        else:
            target.append(fragment)

    rows.sort(key=lambda row: statistics.mean((item[1] + item[3]) / 2 for item in row))
    lines = []
    for row in rows:
        row.sort(key=lambda item: item[0])
        text = " ".join(item[4] for item in row).strip()
        if text:
            lines.append(text)
    return lines


def _pdf_lines_for_row(
    page: fitz.Page,
    band: fitz.Rect,
    anchors: Sequence[float],
    ranges: Sequence[Tuple[float, float]],
) -> List[List[str]]:
    grouped: List[List[Tuple[float, float, float, float, str]]] = [[] for _ in anchors]
    for word in page.get_text("words", clip=band):
        x0, y0, x1, y1, text = word[:5]
        text = str(text).strip()
        if not text:
            continue
        idx = _assign_cell(float(x0), float(x1), anchors, ranges)
        grouped[idx].append((float(x0), float(y0), float(x1), float(y1), text))
    return [_group_fragments_into_lines(parts) for parts in grouped]


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


def _image_to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _render_band_image(page: fitz.Page, band: fitz.Rect, zoom: float = _FAST_ZOOM) -> Image.Image:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=band, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _cell_pixel_box(
    band: fitz.Rect,
    cell_range: Tuple[float, float],
    zoom: float,
    image: Image.Image,
) -> Tuple[int, int, int, int]:
    left, right = cell_range
    x0 = max(0, min(image.width, int(round((left - band.x0) * zoom))))
    x1 = max(x0 + 1, min(image.width, int(round((right - band.x0) * zoom))))
    return x0, 0, x1, image.height


def _crop_cell_image(
    row_image: Image.Image,
    band: fitz.Rect,
    cell_range: Tuple[float, float],
    zoom: float,
) -> Image.Image:
    return row_image.crop(_cell_pixel_box(band, cell_range, zoom, row_image))


def _separated_row_image(
    row_image: Image.Image,
    band: fitz.Rect,
    ranges: Sequence[Tuple[float, float]],
    zoom: float,
) -> Image.Image:
    """Insert thin white gutters so the recogniser cannot merge neighbouring names."""
    image = row_image.copy()
    draw = ImageDraw.Draw(image)
    half_width = max(2, int(round(1.2 * zoom)))
    for left, _ in ranges[1:]:
        x = int(round((left - band.x0) * zoom))
        draw.rectangle((x - half_width, 0, x + half_width, image.height), fill="white")
    return image


def _ocr_fragments(image: Image.Image, *, min_score: float = 0.40):
    engine = _get_ocr_engine()
    if engine is None:
        return []
    try:
        result = engine(_image_to_png(image))
        txts = getattr(result, "txts", None)
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None)
        if txts is None or boxes is None:
            return []

        fragments = []
        for index, text in enumerate(txts):
            text = str(text).strip()
            if not text:
                continue
            if scores is not None and index < len(scores) and float(scores[index]) < min_score:
                continue
            box = boxes[index]
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            fragments.append((min(xs), min(ys), max(xs), max(ys), text))
        return fragments
    except Exception:
        return []


def _ocr_lines_for_row_image(
    row_image: Image.Image,
    band: fitz.Rect,
    anchors: Sequence[float],
    ranges: Sequence[Tuple[float, float]],
    zoom: float = _FAST_ZOOM,
) -> List[List[str]]:
    grouped: List[List[Tuple[float, float, float, float, str]]] = [[] for _ in anchors]
    prepared = _separated_row_image(row_image, band, ranges, zoom)
    for px0, py0, px1, py1, text in _ocr_fragments(prepared):
        x0 = band.x0 + px0 / zoom
        x1 = band.x0 + px1 / zoom
        y0 = band.y0 + py0 / zoom
        y1 = band.y0 + py1 / zoom
        idx = _assign_cell(x0, x1, anchors, ranges)
        grouped[idx].append((x0, y0, x1, y1, text))
    return [_group_fragments_into_lines(parts) for parts in grouped]


def _ocr_lines_for_cell_image(cell_image: Image.Image) -> List[str]:
    if cell_image.width < 2 or cell_image.height < 2:
        return []
    enlarged = cell_image.resize(
        (
            max(2, int(round(cell_image.width * _FALLBACK_SCALE))),
            max(2, int(round(cell_image.height * _FALLBACK_SCALE))),
        ),
        Image.Resampling.LANCZOS,
    )
    return _group_fragments_into_lines(_ocr_fragments(enlarged))


def _clean_name_line(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" \t|,;:–—")
    value = re.sub(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+", "", value)
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'’\-]+$", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _clean_lines(lines: Sequence[str]) -> List[str]:
    return [cleaned for cleaned in (_clean_name_line(line) for line in lines) if cleaned]


def _join_name_lines(lines: Sequence[str]) -> str:
    cleaned = _clean_lines(lines)
    if not cleaned:
        return ""

    result = cleaned[0]
    for line in cleaned[1:]:
        if result.endswith("-"):
            result += line.lstrip("- ")
        else:
            result += " " + line

    result = re.sub(r"\s+", " ", result).strip()
    if result.endswith("-"):
        result = result[:-1].rstrip()
    return result


def _clean_name_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" \t|,;:–—")
    value = re.sub(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+", "", value)
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+$", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _is_upper_name_token(token: str) -> bool:
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", token)
    return bool(letters) and letters == letters.upper()


def _join_wrapped_tokens(lines: Sequence[str]) -> List[str]:
    """Flatten visual lines while keeping hyphenated wrapped names together."""
    tokens: List[str] = []
    for line in _clean_lines(lines):
        for raw_token in line.split():
            token = re.sub(r"-{2,}", "-", raw_token)
            if tokens and tokens[-1].endswith("-"):
                tokens[-1] = tokens[-1] + token
            else:
                tokens.append(token)
    return tokens


def _name_case(value: str) -> str:
    return " ".join(part.title() for part in value.split())


def split_pronote_name(value: str, lines: Sequence[str] | None = None) -> Tuple[str, str]:
    """Return (first_name, last_name) from Pronote's SURNAME Firstname format."""
    cleaned_lines = _clean_lines(lines or [])
    tokens = _join_wrapped_tokens(cleaned_lines)

    if not tokens:
        cleaned_value = _clean_name_text(value)
        tokens = _join_wrapped_tokens([cleaned_value]) if cleaned_value else []
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
        return _name_case(" ".join(first)), _name_case(" ".join(surname))

    if len(tokens) >= 2:
        return _name_case(" ".join(tokens[1:])), _name_case(tokens[0])
    return "", _name_case(tokens[0])


def _best_name_lines(pdf_lines: Sequence[str], ocr_lines: Sequence[str]) -> Tuple[List[str], str]:
    clean_pdf = _clean_lines(pdf_lines)
    if clean_pdf:
        return clean_pdf, "pdf"
    clean_ocr = _clean_lines(ocr_lines)
    if clean_ocr:
        return clean_ocr, "ocr"
    return [], ""


def _looks_like_merged_label(lines: Sequence[str]) -> bool:
    """Detect a likely second surname appearing after the first name has begun."""
    tokens = _join_wrapped_tokens(lines)
    started_first = False
    for token in tokens:
        if not started_first:
            if not _is_upper_name_token(token):
                started_first = True
        elif _is_upper_name_token(token):
            return True
    return False


def _needs_cell_fallback(lines: Sequence[str]) -> bool:
    cleaned = _clean_lines(lines)
    if not cleaned or _looks_like_merged_label(cleaned):
        return True
    name_text = _clean_name_text(_join_name_lines(cleaned))
    first_name, last_name = split_pronote_name(name_text, cleaned)
    return not bool(first_name and last_name)


def _cache_path(pdf_bytes: bytes) -> Path:
    override = os.environ.get("FLASH_TROMBI_IMPORT_CACHE_DIR")
    root = Path(override) if override else Path(tempfile.gettempdir()) / "FlashTrombi-import-cache"
    digest = hashlib.sha256(_IMPORT_CACHE_VERSION.encode("utf-8") + b"\0" + pdf_bytes).hexdigest()
    return root / f"{digest}.pkl"


def _load_cached_cards(pdf_bytes: bytes) -> List[Dict] | None:
    path = _cache_path(pdf_bytes)
    try:
        with path.open("rb") as handle:
            value = pickle.load(handle)
        if isinstance(value, list):
            return value
    except Exception:
        return None
    return None


def _save_cached_cards(pdf_bytes: bytes, cards: List[Dict]) -> None:
    path = _cache_path(pdf_bytes)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        with temp_path.open("wb") as handle:
            pickle.dump(cards, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(path)
    except Exception:
        return


def _extract_cards_uncached(pdf_bytes: bytes) -> List[Dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    cards: List[Dict] = []
    global_index = 0

    for page_number, page in enumerate(doc, start=1):
        items = _portrait_blocks(page)
        rows = _group_rows(items)

        for row_index, row in enumerate(rows):
            band = _row_label_band(page, rows, row_index)
            anchors, ranges = _cell_ranges(page, row)
            pdf_by_cell = _pdf_lines_for_row(page, band, anchors, ranges)
            row_image = _render_band_image(page, band, _FAST_ZOOM)

            need_ocr = [not _clean_lines(lines) for lines in pdf_by_cell]
            ocr_by_cell: List[List[str]] = [[] for _ in row]
            if any(need_ocr):
                ocr_by_cell = _ocr_lines_for_row_image(
                    row_image,
                    band,
                    anchors,
                    ranges,
                    _FAST_ZOOM,
                )

            fallback_indices = [
                index
                for index, needed in enumerate(need_ocr)
                if needed and _needs_cell_fallback(ocr_by_cell[index])
            ]
            for index in fallback_indices:
                cell_image = _crop_cell_image(row_image, band, ranges[index], _FAST_ZOOM)
                fallback = _ocr_lines_for_cell_image(cell_image)
                if _clean_lines(fallback):
                    ocr_by_cell[index] = fallback

            for col_index, item in enumerate(row):
                global_index += 1
                block = item["block"]
                lines, source = _best_name_lines(pdf_by_cell[col_index], ocr_by_cell[col_index])
                name_text = _clean_name_text(_join_name_lines(lines))
                first_name, last_name = split_pronote_name(name_text, lines)

                label_image = _crop_cell_image(
                    row_image,
                    band,
                    ranges[col_index],
                    _FAST_ZOOM,
                )

                cards.append(
                    {
                        "external_key": f"p{page_number:03d}_n{global_index:03d}",
                        "page": page_number,
                        "position": global_index,
                        "photo_bytes": block["image"],
                        "photo_ext": block.get("ext", "jpg") or "jpg",
                        "label_bytes": _image_to_png(label_image),
                        "name_text": name_text,
                        "first_name": first_name,
                        "last_name": last_name,
                        "name_source": source,
                    }
                )

    return cards


def extract_cards(pdf_bytes: bytes) -> List[Dict]:
    cached = _load_cached_cards(pdf_bytes)
    if cached is not None:
        return cached
    cards = _extract_cards_uncached(pdf_bytes)
    _save_cached_cards(pdf_bytes, cards)
    return cards
