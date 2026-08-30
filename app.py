import io
import random
import re
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
}


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" \t\n\r-–—:;,.|")


def detect_class(top_lines: List[str], page_number: int) -> str:
    text = " | ".join(normalize_spaces(x) for x in top_lines if normalize_spaces(x))
    for pattern in CLASS_PATTERNS:
        m = pattern.search(text)
        if m:
            value = " ".join(x for x in m.groups() if x).upper().replace("  ", " ")
            return value
    return f"Page {page_number}"


def looks_like_name(text: str) -> bool:
    t = normalize_spaces(text)
    if not t or len(t) < 3 or len(t) > 70:
        return False
    low = t.lower()
    if any(word in low.split() for word in STOP_WORDS):
        return False
    if re.search(r"@|https?://|www\.|\d{3,}", t, re.I):
        return False
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", t)
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
    for w in words:
        letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", w)
        is_upper = bool(letters) and letters == letters.upper()
        if upper_phase and is_upper:
            uppercase_words.append(w)
        else:
            upper_phase = False
            remainder.append(w)

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


def extract_trombinoscope(pdf_bytes: bytes) -> List[Dict]:
    students: List[Dict] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page_idx, page in enumerate(doc):
        page_dict = page.get_text("dict")
        lines = line_records(page_dict)
        top_lines = [x["text"] for x in lines if x["bbox"].y1 <= page.rect.height * 0.28]
        class_name = detect_class(top_lines, page_idx + 1)

        image_blocks = [b for b in page_dict.get("blocks", []) if b.get("type") == 1 and b.get("image")]

        for img_idx, block in enumerate(image_blocks):
            bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
            if bbox.width < 45 or bbox.height < 55:
                continue
            aspect = bbox.width / max(1.0, bbox.height)
            if not 0.45 <= aspect <= 1.35:
                continue

            nearby = []
            for line in lines:
                tb = line["bbox"]
                if tb.y0 > bbox.y1 + 130 or tb.y1 < bbox.y0 - 90:
                    continue
                if tb.x1 < bbox.x0 - 45 or tb.x0 > bbox.x1 + 45:
                    continue
                if looks_like_name(line["text"]):
                    nearby.append((candidate_score(bbox, tb), line["text"]))

            if not nearby:
                continue

            nearby.sort(key=lambda x: x[0])
            full_name = normalize_spaces(nearby[0][1])
            nom, prenom = split_name(full_name)
            image_bytes = block["image"]
            ext = block.get("ext", "png") or "png"

            students.append({
                "id": f"p{page_idx + 1}_i{img_idx + 1}",
                "classe": class_name,
                "nom": nom,
                "prenom": prenom,
                "nom_complet": full_name,
                "page": page_idx + 1,
                "image_bytes": image_bytes,
                "image_ext": ext,
            })

    return students


def editable_dataframe(students: List[Dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "id": s["id"],
            "classe": s["classe"],
            "nom": s["nom"],
            "prenom": s["prenom"],
            "page": s["page"],
        }
        for s in students
    ])


def student_lookup(students: List[Dict]) -> Dict[str, Dict]:
    return {s["id"]: s for s in students}


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
            "Aucun portrait exploitable n'a été détecté. Le PDF contient peut-être des pages scannées "
            "ou une mise en page différente. Dans ce cas, il faudra ajouter un mode OCR / import CSV."
        )
        st.stop()

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

    classes = sorted({s["classe"] for s in students})
    selected_class = st.selectbox("Classe", classes)
    pool = [s for s in students if s["classe"] == selected_class]
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
                display_name = " ".join(x for x in [current["prenom"], current["nom"]] if x).strip()
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
        "**Format conseillé :** un PDF avec des portraits intégrés et un nom placé sous chaque photo. "
        "Les PDF entièrement scannés nécessitent un OCR, non activé dans cette version."
    )
