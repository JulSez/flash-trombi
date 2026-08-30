import random
import re
import statistics
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Flash Trombinoscope", page_icon="🧑‍🎓", layout="wide")

CLASS_PATTERNS = [
    re.compile(r"\bclasse\s*[:\-]?\s*([A-Z0-9_-]{2,16})\b", re.I),
    re.compile(r"\b([3-6]\s*[A-Z0-9]{1,3})\b", re.I),
    re.compile(r"\b(2de|2nde|seconde)\s*([A-Z0-9]{0,3})\b", re.I),
    re.compile(r"\b(1re|1ere|premi[eè]re)\s*([A-Z0-9]{0,3})\b", re.I),
    re.compile(r"\b(terminale|tle)\s*([A-Z0-9]{0,3})\b", re.I),
]

STOP_WORDS = {
    "classe", "trombinoscope", "eleve", "élève", "annee", "année", "photo",
    "nom", "prenom", "prénom", "professeur", "principal", "principale",
    "groupe", "effectif", "collège", "college", "lycée", "lycee",
}


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" \t\n\r-–—:;,.|")


def looks_like_name(text: str) -> bool:
    value = normalize_spaces(text)
    if not value or len(value) < 3 or len(value) > 70:
        return False
    if any(word in value.lower().split() for word in STOP_WORDS):
        return False
    if re.search(r"@|https?://|www\.|\d{3,}", value, re.I):
        return False
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", value)
    return 2 <= len(words) <= 6


def split_name(full_name: str) -> Tuple[str, str]:
    text = normalize_spaces(full_name)
    words = text.split()
    if not words:
        return "", ""

    uppercase_words = []
    remainder = []
    upper_phase = True
    for word in words:
        letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", word)
        is_upper = bool(letters) and letters == letters.upper()
        if upper_phase and is_upper:
            uppercase_words.append(word)
        else:
            upper_phase = False
            remainder.append(word)

    if uppercase_words and remainder:
        return " ".join(uppercase_words).title(), " ".join(remainder).title()
    if len(words) >= 2:
        return " ".join(words[1:]).title(), words[0].title()
    return text.title(), ""


def line_records(page_dict: Dict) -> List[Dict]:
    lines = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalize_spaces(" ".join(span.get("text", "") for span in spans))
            if text:
                lines.append({"text": text, "bbox": fitz.Rect(line.get("bbox", (0, 0, 0, 0)))})
    return lines


def detect_class(lines: List[Dict], page_number: int, filename: str) -> str:
    top_text = " | ".join(
        item["text"] for item in lines if item["bbox"].y1 < 150
    )
    for pattern in CLASS_PATTERNS:
        match = pattern.search(top_text)
        if match:
            return " ".join(part for part in match.groups() if part).upper()

    stem = Path(filename).stem.upper()
    file_match = re.search(r"\bTROMBI(?:NOSCOPE)?[\s_-]+([A-Z0-9_-]{2,16})\b", stem)
    if file_match:
        return file_match.group(1)
    return f"Page {page_number}"


def portrait_blocks(page_dict: Dict, page_rect: fitz.Rect) -> List[Dict]:
    blocks = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 1 or not block.get("image"):
            continue
        bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if bbox.width < 32 or bbox.height < 42:
            continue
        if bbox.width > page_rect.width * 0.30 or bbox.height > page_rect.height * 0.32:
            continue
        aspect = bbox.width / max(1.0, bbox.height)
        if not 0.40 <= aspect <= 1.35:
            continue
        if bbox.y0 < 35:
            continue
        blocks.append({"block": block, "bbox": bbox})
    return sorted(blocks, key=lambda item: (item["bbox"].y0, item["bbox"].x0))


def group_portrait_rows(items: List[Dict]) -> List[List[Dict]]:
    if not items:
        return []
    median_height = statistics.median(item["bbox"].height for item in items)
    tolerance = max(12.0, median_height * 0.35)
    rows: List[List[Dict]] = []

    for item in items:
        cy = (item["bbox"].y0 + item["bbox"].y1) / 2
        best_row = None
        best_delta = None
        for row in rows:
            row_cy = statistics.mean((x["bbox"].y0 + x["bbox"].y1) / 2 for x in row)
            delta = abs(cy - row_cy)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_row = row
                best_delta = delta
        if best_row is None:
            rows.append([item])
        else:
            best_row.append(item)

    for row in rows:
        row.sort(key=lambda item: item["bbox"].x0)
    rows.sort(key=lambda row: statistics.mean(item["bbox"].y0 for item in row))
    return rows


def nearby_name(lines: List[Dict], bbox: fitz.Rect, label_bottom: float) -> str:
    candidates = []
    for line in lines:
        tb = line["bbox"]
        if tb.y0 < bbox.y1 - 2 or tb.y1 > label_bottom + 5:
            continue
        horizontal_overlap = max(0.0, min(bbox.x1 + 35, tb.x1) - max(bbox.x0 - 35, tb.x0))
        if horizontal_overlap <= 0:
            continue
        if looks_like_name(line["text"]):
            center_gap = abs((bbox.x0 + bbox.x1 - tb.x0 - tb.x1) / 2)
            candidates.append((tb.y0 - bbox.y1 + center_gap * 0.08, line["text"]))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    return normalize_spaces(candidates[0][1])


def render_clip(page: fitz.Page, clip: fitz.Rect, zoom: float = 3.0) -> bytes:
    clip = clip & page.rect
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    return pixmap.tobytes("png")


def card_bounds(rows: List[List[Dict]], row_index: int, item_index: int, page_rect: fitz.Rect) -> Tuple[fitz.Rect, fitz.Rect]:
    row = rows[row_index]
    item = row[item_index]
    bbox = item["bbox"]

    if item_index > 0:
        prev_box = row[item_index - 1]["bbox"]
        left = (prev_box.x1 + bbox.x0) / 2
    else:
        if len(row) > 1:
            gap = max(10.0, row[1]["bbox"].x0 - bbox.x1)
            left = bbox.x0 - gap / 2
        else:
            left = bbox.x0 - 12

    if item_index + 1 < len(row):
        next_box = row[item_index + 1]["bbox"]
        right = (bbox.x1 + next_box.x0) / 2
    else:
        if len(row) > 1:
            gap = max(10.0, bbox.x0 - row[item_index - 1]["bbox"].x1)
            right = bbox.x1 + gap / 2
        else:
            right = bbox.x1 + 30

    row_bottom = max(x["bbox"].y1 for x in row)
    if row_index + 1 < len(rows):
        next_row_top = min(x["bbox"].y0 for x in rows[row_index + 1])
        label_bottom = min(next_row_top - 4, row_bottom + max(28.0, (next_row_top - row_bottom) * 0.90))
    else:
        label_bottom = min(page_rect.y1 - 4, row_bottom + 42)

    label_top = min(label_bottom - 8, bbox.y1 + 1)
    label_rect = fitz.Rect(max(page_rect.x0, left), label_top, min(page_rect.x1, right), label_bottom)
    card_rect = fitz.Rect(max(page_rect.x0, left), bbox.y0, min(page_rect.x1, right), label_bottom)
    return card_rect, label_rect


def extract_from_portrait_blocks(page: fitz.Page, page_dict: Dict, lines: List[Dict], class_name: str, page_number: int) -> List[Dict]:
    items = portrait_blocks(page_dict, page.rect)
    rows = group_portrait_rows(items)
    students = []

    for row_index, row in enumerate(rows):
        for item_index, item in enumerate(row):
            block = item["block"]
            bbox = item["bbox"]
            card_rect, label_rect = card_bounds(rows, row_index, item_index, page.rect)
            full_name = nearby_name(lines, bbox, label_rect.y1)
            nom, prenom = split_name(full_name) if full_name else ("", "")

            students.append({
                "id": f"p{page_number}_r{row_index + 1}_c{item_index + 1}",
                "classe": class_name,
                "nom": nom,
                "prenom": prenom,
                "nom_complet": full_name,
                "page": page_number,
                "image_bytes": block["image"],
                "image_ext": block.get("ext", "png") or "png",
                "label_bytes": render_clip(page, label_rect),
                "card_bytes": render_clip(page, card_rect, zoom=2.2),
                "source": "portrait PDF + découpe dynamique",
            })
    return students


def extract_trombinoscope(pdf_bytes: bytes, filename: str) -> List[Dict]:
    students: List[Dict] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page_idx, page in enumerate(doc):
        page_number = page_idx + 1
        page_dict = page.get_text("dict")
        lines = line_records(page_dict)
        class_name = detect_class(lines, page_number, filename)
        page_students = extract_from_portrait_blocks(page, page_dict, lines, class_name, page_number)
        students.extend(page_students)

    return students


def editable_dataframe(students: List[Dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "id": student["id"],
            "classe": student["classe"],
            "nom": student["nom"],
            "prenom": student["prenom"],
            "page": student["page"],
        }
        for student in students
    ])


def student_lookup(students: List[Dict]) -> Dict[str, Dict]:
    return {student["id"]: student for student in students}


st.title("🧑‍🎓 Flash Trombinoscope")
st.caption("PDF local → détection automatique des cartes → correction → tirage aléatoire.")

st.info(
    "Les PDF restent dans la session Streamlit. Ne mets pas de trombinoscope réel dans le dépôt Git."
)

uploaded = st.file_uploader("Dépose un trombinoscope PDF", type=["pdf"])

if uploaded is not None:
    file_signature = (uploaded.name, uploaded.size)
    if st.session_state.get("file_signature") != file_signature:
        with st.spinner("Détection des portraits et découpe des étiquettes…"):
            try:
                st.session_state.students = extract_trombinoscope(uploaded.getvalue(), uploaded.name)
                st.session_state.file_signature = file_signature
                st.session_state.current_student_id = None
                st.session_state.reveal = False
            except Exception as exc:
                st.error(f"Impossible de lire le PDF : {exc}")
                st.stop()

    students = st.session_state.get("students", [])
    if not students:
        st.warning(
            "Aucun portrait séparé n'a été détecté dans ce PDF. Cette version sait gérer un nombre "
            "variable de portraits si les photos sont encore présentes comme images dans le PDF."
        )
        st.stop()

    st.success(f"{len(students)} portrait(s) détecté(s), sans supposer un nombre fixe.")

    missing_names = sum(not (student["nom"] or student["prenom"]) for student in students)
    if missing_names:
        st.info(
            f"{missing_names} nom(s) ne sont pas du texte sélectionnable. L'étiquette visuelle sous "
            "chaque portrait a donc été découpée automatiquement et servira de réponse."
        )

    with st.expander("🔎 Contrôler les découpes"):
        columns = st.columns(4)
        for index, student in enumerate(students):
            with columns[index % 4]:
                st.image(student["image_bytes"], width=115)
                st.image(student["label_bytes"], width=190)
                st.caption(student["id"])

    st.subheader("1. Vérifier / corriger la liste")
    st.caption("Si un nom n'est pas extrait en texte, tu peux le saisir ici en regardant l'étiquette découpée au-dessus.")
    edited_df = st.data_editor(
        editable_dataframe(students),
        hide_index=True,
        use_container_width=True,
        disabled=["id", "page"],
        key="student_editor",
    )

    lookup = student_lookup(students)
    for row in edited_df.to_dict("records"):
        if row["id"] in lookup:
            lookup[row["id"]]["classe"] = normalize_spaces(str(row.get("classe", ""))) or "Sans classe"
            lookup[row["id"]]["nom"] = normalize_spaces(str(row.get("nom", "")))
            lookup[row["id"]]["prenom"] = normalize_spaces(str(row.get("prenom", "")))

    st.download_button(
        "Télécharger la liste CSV",
        data=edited_df[["classe", "nom", "prenom", "page"]].to_csv(index=False).encode("utf-8-sig"),
        file_name="eleves_extraits.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("2. Flash card")

    classes = sorted({student["classe"] for student in students})
    selected_class = st.selectbox("Classe", classes)
    pool = [student for student in students if student["classe"] == selected_class]
    st.caption(f"{len(pool)} élève(s) dans cette classe.")

    if st.button("🎲 Tirer un élève", type="primary"):
        chosen = random.choice(pool)
        st.session_state.current_student_id = chosen["id"]
        st.session_state.reveal = False

    current_id = st.session_state.get("current_student_id")
    current = lookup.get(current_id) if current_id else None

    if current and current["classe"] == selected_class:
        left, right = st.columns([1, 1.2])
        with left:
            st.image(current["image_bytes"], caption="Qui est cet élève ?", width=340)
        with right:
            if st.button("👀 Afficher la réponse", use_container_width=True):
                st.session_state.reveal = True

            if st.session_state.get("reveal"):
                display_name = " ".join(value for value in [current["prenom"], current["nom"]] if value).strip()
                if display_name:
                    st.success(display_name)
                else:
                    st.image(current["label_bytes"], caption="Étiquette extraite du PDF", width=360)
                st.caption(f"Classe : {current['classe']} · page {current['page']}")

                if st.button("➡️ Élève suivant", use_container_width=True):
                    chosen = random.choice(pool)
                    st.session_state.current_student_id = chosen["id"]
                    st.session_state.reveal = False
                    st.rerun()
    else:
        st.info("Clique sur « Tirer un élève » pour commencer.")

else:
    st.markdown(
        "**Principe :** le nombre de portraits est détecté automatiquement. L'application regroupe les "
        "photos par lignes puis découpe chaque carte aux milieux des espaces entre les voisins."
    )
