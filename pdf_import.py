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
        bottom = min(next_top - 3.0, row_bottom + 52.0)
    else:
        bottom = min(page.rect.y1 - 3.0, row_bottom + 52.0)
    if bottom <= top + 6:
        bottom = min(page.rect.y1, top + 38.0)
    return fitz.Rect(page.rect.x0, top, page.rect.x1, bottom)


def _cell_ranges(page: fitz.Page, row: List[Dict]) -> Tuple[List[float], List[Tuple[float, float]]]:
    """Return one horizontal label cell per portrait.

    Pronote starts each label at the same x coordinate as its portrait and
    wraps long labels before the next portrait starts. Using those portrait
    left edges as hard cell boundaries lets us crop each student's answer
    before text recognition, so neighbouring names can never be merged first.
    """
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
        if index + 1 < len(anchors):
            right = anchors[index + 1]
        else:
            right = left + pitch
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
    """Compatibility helper used by tests and older PDF layouts."""
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


def _pdf_lines_for_cell(page: fitz.Page, clip: fitz.Rect) -> List[str]:
    fragments: List[Tuple[float, float, float, float, str]] = []
    for word in page.get_text("words", clip=clip):
        x0, y0, x1, y1, text = word[:5]
        text = str(text).strip()
        if text:
            fragments.append((float(x0), float(y0), float(x1), float(y1), text))
    return _group_fragments_into_lines(fragments)


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


def _ocr_lines_for_cell(
    page: fitz.Page,
    clip: fitz.Rect,
    zoom: float = 4.5,
) -> List[str]:
    """Read exactly one Pronote card label.

    The old implementation read a whole row first and then tried to split the
    recognised boxes between students. On tight rows, the recogniser could
    merge e.g. "MEGHERBI Ahmed" and "MEYER Romane" into one box before our code
    got a chance to separate them. Cropping one cell first makes that merge
    impossible.
    """
    engine = _get_ocr_engine()
    if engine is None:
        return []

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        result = engine(pix.tobytes("png"))
        txts = getattr(result, "txts", None)
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None)
        if txts is None or boxes is None:
            return []

        fragments: List[Tuple[float, float, float, float, str]] = []
        for index, text in enumerate(txts):
            text = str(text).strip()
            if not text:
                continue
            if scores is not None and index < len(scores) and float(scores[index]) < 0.40:
                continue

            box = boxes[index]
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            x0 = clip.x0 + min(xs) / zoom
            x1 = clip.x0 + max(xs) / zoom
            y0 = clip.y0 + min(ys) / zoom
            y1 = clip.y0 + max(ys) / zoom
            fragments.append((x0, y0, x1, y1, text))

        return _group_fragments_into_lines(fragments)
    except Exception:
        return []


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
    """Return (first_name, last_name) from Pronote's SURNAME Firstname format.

    Pronote wraps at the card boundary. The surname may span several visual
    lines (RAMIREZ / ELIZALDE Brandon) and either surname or first name may be
    hyphenated at a line break (MARCHAND- / TAVENAUX Sacha,
    GRUMBERG John- / Alexandre).
    """
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


def extract_cards(pdf_bytes: bytes) -> List[Dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    cards: List[Dict] = []
    global_index = 0

    for page_number, page in enumerate(doc, start=1):
        items = _portrait_blocks(page)
        rows = _group_rows(items)

        for row_index, row in enumerate(rows):
            band = _row_label_band(page, rows, row_index)

            for col_index, item in enumerate(row):
                global_index += 1
                block = item["block"]

                # Important: read each label in its own non-overlapping cell.
                # This prevents a long label from being merged with the next one.
                read_clip = _cell_label_clip(
                    page,
                    row,
                    col_index,
                    band,
                    visual_margin=False,
                )
                pdf_lines = _pdf_lines_for_cell(page, read_clip)
                ocr_lines: List[str] = []
                if not _clean_lines(pdf_lines):
                    ocr_lines = _ocr_lines_for_cell(page, read_clip)

                lines, source = _best_name_lines(pdf_lines, ocr_lines)
                name_text = _clean_name_text(_join_name_lines(lines))
                first_name, last_name = split_pronote_name(name_text, lines)

                visual_clip = _cell_label_clip(
                    page,
                    row,
                    col_index,
                    band,
                    visual_margin=True,
                )
                label_pix = page.get_pixmap(
                    matrix=fitz.Matrix(3.5, 3.5),
                    clip=visual_clip,
                    alpha=False,
                )

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
