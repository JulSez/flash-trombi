import random
import re
import statistics
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Flash Trombinoscope", page_icon="🧑‍🎓", layout="wide")

CLASS_PATTERNS = [
    re.compile(r"\b(?:classe\s*[:\-]?\s*)?([3-6]\s*[A-Z0-9]{1,3})\b", re.I),
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


def detect_class(top_lines: List[str], page_number: int) -> str:
    text = " | ".join(normalize_spaces(x) for x in top_lines if normalize_spaces(x))
    for pattern in CLASS_PATTERNS:
        match = pattern.search(text)
        if match:
            value = " ".join(x for x in match.groups() if x).upper().replace("  ", " ")
            return value
    return f"Page {page_number}"


def looks_like_name(text: str) -> bool:
    value = normalize_spaces(text)
    if not value or len(value) < 3 or len(value) > 70:
        return False

    low = value.lower()
    if any(word in low.split() for word in STOP_WORDS):
        return False
    if re.search(r"@|https?://|www\.|\d{3,}", value, re.I):
        return False

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", value)
    return 2 <= len(words) <= 6


def split_name(full_name: str) -> Tuple[str, str]:
    """Heuristique simple : blocs en MAJUSCULES = nom, reste = prénom."""
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
            if not text:
                continue
            bbox = fitz.Rect(line.get("bbox", (0, 0, 0, 0)))
            lines.append({"text": text, "bbox": bbox})
    return lines


def candidate_score(img_box: fitz.Rect, text_box: fitz.Rect) -> float:
    overlap = max(0.0, min(img_box.x1, text_box.x1) - max(img_box.x0, text_box.x0))
    overlap_ratio = overlap / max(1.0, min(img_box.width, text_box.width))

    if text_box.y0 >= img_box.y1:
        vertical_gap = text_box.y0 - img_box.y1
        direction_penalty = 0.0
    elif text_box.y1 <= img_box.y0:
        vertical_gap = img_box.y0 - text_box.y1
        direction_penalty = 45.0
    else:
        vertical_gap = 0.0
        direction_penalty = 20.0

    center_gap = abs((img_box.x0 + img_box.x1) / 2 - (text_box.x0 + text_box.x1) / 2)
    return vertical_gap + 0.25 * center_gap + direction_penalty - 35.0 * overlap_ratio


def cluster_values(values: List[float], tolerance: float) -> List[List[float]]:
    if not values:
        return []

    ordered = sorted(values)
    clusters: List[List[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        current_center = sum(clusters[-1]) / len(clusters[-1])
        if abs(value - current_center) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def classic_grid_name_anchors(lines: List[Dict], page_rect: fitz.Rect) -> List[Dict]:
    """Repère des lignes de noms organisées en grille dans un PDF imprimé/aplati."""
    candidates = []
    for line in lines:
        bbox = line["bbox"]
        if bbox.y0 < page_rect.height * 0.12:
            continue
        if bbox.width > page_rect.width * 0.45:
            continue
        if looks_like_name(line["text"]):
            candidates.append(line)

    if len(candidates) < 3:
        return []

    heights = [max(1.0, candidate["bbox"].height) for candidate in candidates]
    row_tolerance = max(10.0, statistics.median(heights) * 1.8)
    ordered = sorted(candidates, key=lambda candidate: (candidate["bbox"].y0, candidate["bbox"].x0))

    rows: List[List[Dict]] = []
    for candidate in ordered:
        cy = (candidate["bbox"].y0 + candidate["bbox"].y1) / 2
        placed = False
        for row in rows:
            row_cy = statistics.mean(
                (item["bbox"].y0 + item["bbox"].y1) / 2 for item in row
            )
            if abs(cy - row_cy) <= row_tolerance:
                row.append(candidate)
                placed = True
                break
        if not placed:
            rows.append([candidate])

    grid_rows = [row for row in rows if len(row) >= 2]
    anchors = [
        item
        for row in grid_rows
        for item in sorted(row, key=lambda candidate: candidate["bbox"].x0)
    ]
    return anchors if len(anchors) >= 3 else []


def estimate_grid_crop(anchors: List[Dict], anchor: Dict, page_rect: fitz.Rect) -> fitz.Rect:
    centers_x = sorted(
        (item["bbox"].x0 + item["bbox"].x1) / 2
        for item in anchors
    )
    centers_y = sorted(
        (item["bbox"].y0 + item["bbox"].y1) / 2
        for item in anchors
    )

    x_clusters = cluster_values(centers_x, tolerance=max(18.0, page_rect.width * 0.035))
    y_clusters = cluster_values(centers_y, tolerance=max(12.0, page_rect.height * 0.018))
    col_centers = [statistics.mean(cluster) for cluster in x_clusters]
    row_centers = [statistics.mean(cluster) for cluster in y_clusters]

    col_gaps = [
        right - left
        for left, right in zip(col_centers, col_centers[1:])
        if right - left > 25
    ]
    row_gaps = [
        bottom - top
        for top, bottom in zip(row_centers, row_centers[1:])
        if bottom - top > 35
    ]

    default_col_gap = page_rect.width / max(3, min(6, len(col_centers) or 4))
    default_row_gap = page_rect.height / max(3, min(7, len(row_centers) or 5))

    col_gap = statistics.median(col_gaps) if col_gaps else default_col_gap
    row_gap = statistics.median(row_gaps) if row_gaps else default_row_gap

    bbox = anchor["bbox"]
    center_x = (bbox.x0 + bbox.x1) / 2

    crop_width = min(170.0, max(72.0, col_gap * 0.82))
    crop_height = min(175.0, max(78.0, row_gap * 0.76))

    bottom = max(page_rect.y0 + 20.0, bbox.y0 - 3.0)
    top = max(page_rect.y0, bottom - crop_height)
    left = max(page_rect.x0, center_x - crop_width / 2)
    right = min(page_rect.x1, center_x + crop_width / 2)

    if right - left < crop_width:
        if left <= page_rect.x0:
            right = min(page_rect.x1, left + crop_width)
        elif right >= page_rect.x1:
            left = max(page_rect.x0, right - crop_width)

    return fitz.Rect(left, top, right, bottom)


def extract_from_rendered_grid(
    page: fitz.Page,
    lines: List[Dict],
    class_name: str,
    page_number: int,
) -> List[Dict]:
    """Fallback pour les PDF créés via Imprimer / Enregistrer en PDF.

    La page est rendue en bitmap puis chaque portrait est recadré au-dessus
    de son nom. Aucun OCR n'est nécessaire tant que les noms restent du texte.
    """
    anchors = classic_grid_name_anchors(lines, page.rect)
    if not anchors:
        return []

    students = []
    for index, anchor in enumerate(anchors, start=1):
        full_name = normalize_spaces(anchor["text"])
        nom, prenom = split_name(full_name)
        clip = estimate_grid_crop(anchors, anchor, page.rect)

        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(2.0, 2.0),
            clip=clip,
            alpha=False,
        )

        students.append(
            {
                "id": f"p{page_number}_r{index}",
                "classe": class_name,
                "nom": nom,
                "prenom": prenom,
                "nom_complet": full_name,
                "page": page_number,
                "image_bytes": pixmap.tobytes("png"),
                "image_ext": "png",
                "source": "page imprimée",
            }
        )
    return students


def extract_embedded_portraits(
    page: fitz.Page,
    page_dict: Dict,
    lines: List[Dict],
    class_name: str,
    page_number: int,
) -> List[Dict]:
    students = []
    image_blocks = [
        block
        for block in page_dict.get("blocks", [])
        if block.get("type") == 1 and block.get("image")
    ]

    for img_idx, block in enumerate(image_blocks):
        bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if bbox.width < 45 or bbox.height < 55:
            continue

        aspect = bbox.width / max(1.0, bbox.height)
        if not 0.45 <= aspect <= 1.35:
            continue

        nearby = []
        for line in lines:
            text_box = line["bbox"]
            if text_box.y0 > bbox.y1 + 130 or text_box.y1 < bbox.y0 - 90:
                continue
            if text_box.x1 < bbox.x0 - 45 or text_box.x0 > bbox.x1 + 45:
                continue
            if looks_like_name(line["text"]):
                nearby.append((candidate_score(bbox, text_box), line["text"]))

        if not nearby:
            continue

        nearby.sort(key=lambda item: item[0])
        full_name = normalize_spaces(nearby[0][1])
        nom, prenom = split_name(full_name)

        students.append(
            {
                "id": f"p{page_number}_i{img_idx + 1}",
                "classe": class_name,
                "nom": nom,
                "prenom": prenom,
                "nom_complet": full_name,
                "page": page_number,
                "image_bytes": block["image"],
                "image_ext": block.get("ext", "png") or "png",
                "source": "image PDF",
            }
        )

    return students


def extract_trombinoscope(pdf_bytes: bytes) -> List[Dict]:
    students: List[Dict] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page_idx, page in enumerate(doc):
        page_number = page_idx + 1
        page_dict = page.get_text("dict")
        lines = line_records(page_dict)
        top_lines = [
            item["text"]
            for item in lines
            if item["bbox"].y1 <= page.rect.height * 0.28
        ]
        class_name = detect_class(top_lines, page_number)

        page_students = extract_embedded_portraits(
            page, page_dict, lines, class_name, page_number
        )

        if not page_students:
            page_students = extract_from_rendered_grid(
                page, lines, class_name, page_number
            )

        students.extend(page_students)

    return students


def editable_dataframe(students: List[Dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": student["id"],
                "classe": student["classe"],
                "nom": student["nom"],
                "prenom": student["prenom"],
                "page": student["page"],
            }
            for student in students
        ]
    )


def student_lookup(students: List[Dict]) -> Dict[str, Dict]:
    return {student["id"]: student for student in students}


st.title("🧑‍🎓 Flash Trombinoscope")
st.caption("PDF local → extraction des photos/noms → correction → tirage aléatoire par classe.")

st.info(
    "Utilise uniquement des trombinoscopes que tu es autorisé à traiter. "
    "L'application ne fait aucun scraping : le PDF reste dans la session Streamlit."
)

uploaded = st.file_uploader("Dépose un trombinoscope PDF", type=["pdf"])

if uploaded is not None:
    file_signature = (uploaded.name, uploaded.size)
    if st.session_state.get("file_signature") != file_signature:
        with st.spinner("Extraction des portraits et des étiquettes…"):
            try:
                st.session_state.students = extract_trombinoscope(uploaded.getvalue())
                st.session_state.file_signature = file_signature
                st.session_state.current_student_id = None
                st.session_state.reveal = False
            except Exception as exc:
                st.error(f"Impossible de lire le PDF : {exc}")
                st.stop()

    students = st.session_state.get("students", [])
    if not students:
        st.warning(
            "Aucun portrait n'a été détecté. Si le PDF est une impression, "
            "le mode 'page imprimée' fonctionne tant que les noms sont encore "
            "sélectionnables dans le PDF. Si même le texte est aplati en image, "
            "il faudra ajouter un OCR."
        )
        st.stop()

    printed_count = sum(student.get("source") == "page imprimée" for student in students)
    if printed_count:
        st.success(
            f"{len(students)} portraits détectés, dont {printed_count} "
            "par recadrage d'une page imprimée."
        )
    else:
        st.success(f"{len(students)} portraits détectés.")

    base_df = editable_dataframe(students)
    st.subheader("1. Vérifier / corriger l'extraction")
    st.caption("Tu peux modifier la classe, le nom ou le prénom avant le tirage.")
    edited_df = st.data_editor(
        base_df,
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

    csv_export = edited_df[["classe", "nom", "prenom", "page"]].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Télécharger la liste CSV",
        data=csv_export,
        file_name="eleves_extraits.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("2. Flash card")

    classes = sorted({student["classe"] for student in students})
    selected_class = st.selectbox("Classe", classes)
    pool = [student for student in students if student["classe"] == selected_class]
    st.caption(f"{len(pool)} élève(s) dans cette classe.")

    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("🎲 Tirer un élève", type="primary", use_container_width=True):
            chosen = random.choice(pool)
            st.session_state.current_student_id = chosen["id"]
            st.session_state.reveal = False
    with c2:
        hide_after_answer = st.checkbox("Masquer à nouveau au prochain tirage", value=True)

    current_id = st.session_state.get("current_student_id")
    current = lookup.get(current_id) if current_id else None

    if current and current["classe"] == selected_class:
        left, right = st.columns([1, 1.2])
        with left:
            st.image(current["image_bytes"], caption="Qui est cet élève ?", width=340)
        with right:
            st.markdown("### Réponse")
            if st.button("👀 Afficher le nom", use_container_width=True):
                st.session_state.reveal = True

            if st.session_state.get("reveal"):
                display_name = " ".join(
                    value for value in [current["prenom"], current["nom"]] if value
                ).strip()
                st.success(display_name or "Nom non renseigné")
                st.caption(f"Classe : {current['classe']} · page {current['page']}")

                if st.button("➡️ Élève suivant", use_container_width=True):
                    chosen = random.choice(pool)
                    st.session_state.current_student_id = chosen["id"]
                    if hide_after_answer:
                        st.session_state.reveal = False
                    st.rerun()
    else:
        st.info("Clique sur « Tirer un élève » pour commencer.")

else:
    st.markdown(
        "**Formats pris en charge :** PDF avec portraits intégrés, ou PDF créé via "
        "« Imprimer / Enregistrer en PDF » avec noms encore sélectionnables. "
        "Un document entièrement aplati en image nécessite un OCR."
    )
