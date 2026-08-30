from __future__ import annotations

from pathlib import Path

import streamlit as st

from storage import (
    STATUS_LABELS,
    class_stats,
    create_class,
    end_session,
    get_class,
    get_session,
    get_session_students,
    get_students,
    init_db,
    list_classes,
    next_student,
    record_answer,
    session_progress,
    start_or_resume_session,
    update_student_name,
)

st.set_page_config(page_title="Flash Trombi", page_icon="🧑‍🏫", layout="wide")
init_db()


def student_display_name(student: dict) -> str:
    name = " ".join(
        part for part in [student.get("first_name", ""), student.get("last_name", "")] if part
    ).strip()
    return name or f"Élève {student['position']:02d}"


def show_answer(student: dict) -> None:
    name = student_display_name(student)
    if student.get("first_name") or student.get("last_name"):
        st.success(name)
    label_path = student.get("label_path")
    if label_path and Path(label_path).exists():
        st.image(label_path, caption="Étiquette extraite du trombinoscope", width=360)


st.title("🧑‍🏫 Flash Trombi")
st.caption("Apprentissage progressif des élèves, classe par classe, avec historique SQLite local.")

classes = list_classes()

with st.sidebar:
    st.header("Navigation")
    page = st.radio("", ["🎓 Entraînement", "📚 Classes"], label_visibility="collapsed")
    st.divider()
    st.caption("Toutes les données restent dans le dossier local `data/`.")

if page == "📚 Classes":
    st.subheader("Importer une classe")
    st.write("Chaque PDF importé correspond à une classe distincte.")
    c1, c2 = st.columns([1, 2])
    with c1:
        new_class_name = st.text_input("Nom de la classe", placeholder="ex. TSTI2D3")
    with c2:
        uploaded = st.file_uploader("Trombinoscope PDF", type=["pdf"])

    if st.button("➕ Créer la classe", type="primary", disabled=not (new_class_name and uploaded)):
        try:
            with st.spinner("Extraction des portraits et création de la base…"):
                class_id = create_class(new_class_name, uploaded.getvalue())
            st.success("Classe créée.")
            st.session_state["selected_class_id"] = class_id
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    classes = list_classes()
    if not classes:
        st.info("Aucune classe importée pour le moment.")
        st.stop()

    labels = {f"{c['name']} ({c['student_count']} élèves)": c["id"] for c in classes}
    default_id = st.session_state.get("selected_class_id", classes[0]["id"])
    label_list = list(labels)
    default_index = next((i for i, label in enumerate(label_list) if labels[label] == default_id), 0)
    selected_label = st.selectbox("Classe à gérer", label_list, index=default_index)
    class_id = labels[selected_label]
    st.session_state["selected_class_id"] = class_id

    stats = class_stats(class_id)
    cols = st.columns(4)
    for col, status in zip(cols, ["non_commence", "vu", "memorise", "acquis"]):
        col.metric(STATUS_LABELS[status], stats[status])

    st.subheader("Élèves")
    st.caption(
        "Le nom peut être saisi manuellement. L'étiquette visuelle extraite du PDF reste disponible comme réponse."
    )
    students = get_students(class_id)
    for student in students:
        with st.expander(
            f"{student['position']:02d} · {student_display_name(student)} · {STATUS_LABELS[student['status']]}"
        ):
            a, b, c = st.columns([1, 1.2, 1.4])
            with a:
                st.image(student["photo_path"], width=150)
            with b:
                if student.get("label_path") and Path(student["label_path"]).exists():
                    st.image(student["label_path"], caption="Nom dans le PDF", width=280)
                if student["memory_dates"]:
                    st.caption("Cycle courant : " + ", ".join(student["memory_dates"]))
            with c:
                first = st.text_input("Prénom", value=student["first_name"], key=f"fn_{student['id']}")
                last = st.text_input("Nom", value=student["last_name"], key=f"ln_{student['id']}")
                if st.button("Enregistrer", key=f"save_{student['id']}"):
                    update_student_name(student["id"], first, last)
                    st.success("Nom enregistré.")

else:
    if not classes:
        st.info("Commence par importer une classe dans l'onglet « Classes ».")
        st.stop()

    labels = {f"{c['name']} ({c['student_count']} élèves)": c["id"] for c in classes}
    selected_label = st.selectbox("Classe", list(labels))
    class_id = labels[selected_label]

    stats = class_stats(class_id)
    cols = st.columns(4)
    for col, status in zip(cols, ["non_commence", "vu", "memorise", "acquis"]):
        col.metric(STATUS_LABELS[status], stats[status])

    st.caption(
        "Priorité du groupe : Mémorisé → Vu → Non commencé. Les Acquis ne reviennent qu'en mode entretien quand toute la classe est acquise."
    )

    if st.button("▶️ Démarrer / reprendre la session", type="primary"):
        try:
            session = start_or_resume_session(class_id)
            st.session_state["session_id"] = session["id"]
            st.session_state.pop("current_student", None)
            st.session_state.pop("answer_result", None)
            st.rerun()
        except Exception as exc:
            st.warning(str(exc))

    session_id = st.session_state.get("session_id")
    session = get_session(session_id) if session_id else None
    if not session or session["class_id"] != class_id:
        st.info("Démarre une session pour travailler un groupe de 10 élèves.")
        st.stop()

    progress = session_progress(session_id)
    mode = "Entretien des acquis" if session["maintenance_mode"] else "Apprentissage"
    st.subheader(mode)
    st.progress(progress["completed"] / max(1, progress["total"]))
    st.caption(
        f"Groupe : {progress['total']} élève(s) · terminés aujourd'hui : {progress['completed']}/{progress['total']} · questions : {progress['attempts']}"
    )

    if session.get("completed_at"):
        st.success("Session terminée 🎉")
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_result", None)
        st.stop()

    if "current_student" not in st.session_state:
        st.session_state["current_student"] = next_student(session_id)
        st.session_state.pop("answer_result", None)

    student = st.session_state.get("current_student")
    if not student:
        st.success("Session terminée 🎉")
        st.stop()

    left, right = st.columns([1, 1.1])
    with left:
        st.image(student["photo_path"], caption="Qui est cet élève ?", width=360)
        st.caption(
            f"Statut : {STATUS_LABELS.get(student['status'], student['status'])} · réussites de cette session : {student.get('correct_count', 0)}/3"
        )

    with right:
        result = st.session_state.get("answer_result")
        if result is None:
            st.markdown("### Est-ce que tu l'avais ?")
            b1, b2 = st.columns(2)
            if b1.button("✅ Oui", type="primary", use_container_width=True):
                st.session_state["answer_result"] = record_answer(session_id, student["id"], True)
                st.rerun()
            if b2.button("❌ Non", use_container_width=True):
                st.session_state["answer_result"] = record_answer(session_id, student["id"], False)
                st.rerun()
        else:
            show_answer(student)
            if result["status"] == "memorise" and result["memory_dates"]:
                st.caption("Mémorisé : " + ", ".join(result["memory_dates"]))
            st.info(result["message"])

            if result["session_finished"]:
                st.success("Les élèves du groupe sont terminés pour aujourd'hui.")
            elif st.button("➡️ Élève suivant", type="primary", use_container_width=True):
                st.session_state["current_student"] = next_student(session_id)
                st.session_state.pop("answer_result", None)
                st.rerun()

    with st.expander("Voir le groupe de travail"):
        session_students = get_session_students(session_id)
        for item in session_students:
            marker = "✅" if item["completed"] else "•"
            dates = f" · {', '.join(item['memory_dates'])}" if item["memory_dates"] else ""
            st.write(
                f"{marker} {student_display_name(item)} — {STATUS_LABELS[item['status']]} — {item['correct_count']}/3{dates}"
            )

    if st.button("⏹️ Arrêter la session"):
        end_session(session_id)
        st.session_state.pop("session_id", None)
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_result", None)
        st.rerun()
