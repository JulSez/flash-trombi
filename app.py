from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from paths import DATA_DIR
from storage import (
    STATUS_LABELS,
    analyze_pdf,
    class_name_exists,
    class_stats,
    create_backup_bytes,
    create_class_from_cards,
    delete_class,
    get_session,
    get_students,
    get_today_open_session,
    init_db,
    list_classes,
    next_student,
    record_answer,
    restore_backup_bytes,
    session_progress,
    start_or_resume_session,
    update_student_name,
)
from updates import check_for_update
from version import APP_VERSION

st.set_page_config(
    page_title="Flash Trombi",
    page_icon="🧑‍🏫",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()

NAV_HOME = "🏠 Mes classes"
NAV_TRAIN = "🎓 Entraînement"
NAV_ADD = "➕ Ajouter une classe"
NAV_MANAGE = "🛠️ Gérer les classes"
NAV_BACKUP = "🛟 Sauvegarde & mise à jour"
NAV_ITEMS = [NAV_HOME, NAV_TRAIN, NAV_ADD, NAV_MANAGE, NAV_BACKUP]


def student_display_name(student: dict) -> str:
    name = " ".join(
        part for part in [student.get("first_name", ""), student.get("last_name", "")] if part
    ).strip()
    return name or f"Élève {student['position']:02d}"


def show_answer(student: dict) -> None:
    if student.get("first_name") or student.get("last_name"):
        st.success(student_display_name(student))
    label_path = student.get("label_path")
    if label_path and Path(label_path).exists():
        st.image(label_path, caption="Nom sur le trombinoscope", width=420)


def go_to(page: str, class_id: int | None = None) -> None:
    st.session_state["nav"] = page
    if class_id is not None:
        st.session_state["selected_class_id"] = class_id
    if page != NAV_TRAIN:
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_revealed", None)


def go_training(class_id: int) -> None:
    st.session_state["selected_class_id"] = class_id
    st.session_state["nav"] = NAV_TRAIN
    st.session_state.pop("current_student", None)
    st.session_state.pop("answer_revealed", None)
    st.session_state.pop("feedback", None)


def start_training(class_id: int) -> None:
    try:
        session = start_or_resume_session(class_id)
        st.session_state["session_id"] = session["id"]
        st.session_state["selected_class_id"] = class_id
        st.session_state.pop("current_student", None)
        st.session_state["answer_revealed"] = False
        st.session_state.pop("feedback", None)
    except Exception as exc:
        st.session_state["friendly_error"] = str(exc)


def reveal_answer() -> None:
    st.session_state["answer_revealed"] = True


def answer_current(correct: bool) -> None:
    session_id = st.session_state.get("session_id")
    student = st.session_state.get("current_student")
    if not session_id or not student:
        return
    try:
        result = record_answer(session_id, student["id"], correct)
        st.session_state["feedback"] = result["message"]
        st.session_state["answer_revealed"] = False
        if result["session_finished"]:
            st.session_state.pop("current_student", None)
        else:
            st.session_state["current_student"] = next_student(session_id)
    except Exception as exc:
        st.session_state["friendly_error"] = str(exc)


def clear_analysis() -> None:
    st.session_state.pop("pdf_analysis", None)
    for key in list(st.session_state):
        if key.startswith("keep_card_"):
            st.session_state.pop(key, None)


def status_metrics(class_id: int) -> None:
    stats = class_stats(class_id)
    cols = st.columns(4)
    for col, status in zip(cols, ["non_commence", "vu", "memorise", "acquis"]):
        col.metric(STATUS_LABELS[status], stats[status])


def page_home(classes: list[dict]) -> None:
    st.title("🧑‍🏫 Flash Trombi")
    st.caption("Apprendre les prénoms et noms de tes élèves, sans terminal ni tableur.")

    if not classes:
        st.info("Tu n'as encore aucune classe.")
        st.button(
            "➕ Ajouter ma première classe",
            type="primary",
            use_container_width=True,
            on_click=go_to,
            args=(NAV_ADD,),
        )
        st.markdown("**Comment ça marche ?** PDF → vérification des portraits → entraînement par séries de 10.")
        return

    st.subheader("Mes classes")
    for class_row in classes:
        total = int(class_row.get("student_count") or 0)
        acquired = int(class_row.get("acquired_count") or 0)
        with st.container(border=True):
            left, middle, right = st.columns([2.1, 2.3, 1.2])
            with left:
                st.markdown(f"### {class_row['name']}")
                st.caption(f"{total} élève(s)")
            with middle:
                ratio = acquired / max(1, total)
                st.progress(ratio)
                st.caption(f"{acquired}/{total} acquis")
            with right:
                open_session = get_today_open_session(class_row["id"])
                label = "▶️ Reprendre" if open_session else "▶️ Continuer"
                st.button(
                    label,
                    key=f"home_train_{class_row['id']}",
                    type="primary",
                    use_container_width=True,
                    on_click=go_training,
                    args=(class_row["id"],),
                )

    st.button("➕ Ajouter une classe", on_click=go_to, args=(NAV_ADD,))


def page_add_class() -> None:
    st.title("➕ Ajouter une classe")
    st.write("1 PDF = 1 classe. Donne-lui un nom puis vérifie les portraits détectés.")

    c1, c2 = st.columns([1, 2])
    with c1:
        class_name = st.text_input("Nom de la classe", placeholder="ex. TSTI2D3")
    with c2:
        uploaded = st.file_uploader("Trombinoscope PDF", type=["pdf"])

    can_analyze = bool(class_name.strip() and uploaded is not None)
    if st.button("🔎 Analyser le PDF", type="primary", disabled=not can_analyze):
        name = class_name.strip()
        if class_name_exists(name):
            st.error("Une classe portant ce nom existe déjà. Choisis un autre nom.")
        else:
            try:
                pdf_bytes = uploaded.getvalue()
                with st.spinner("Je cherche les portraits…"):
                    cards = analyze_pdf(pdf_bytes)
                if not cards:
                    st.error("Je n'ai trouvé aucun portrait exploitable dans ce PDF.")
                else:
                    clear_analysis()
                    st.session_state["pdf_analysis"] = {
                        "class_name": name,
                        "filename": uploaded.name,
                        "pdf_bytes": pdf_bytes,
                        "cards": cards,
                    }
                    st.rerun()
            except Exception:
                st.error("Je n'ai pas réussi à lire ce PDF. Essaie de l'imprimer de nouveau en PDF puis réimporte-le.")

    analysis = st.session_state.get("pdf_analysis")
    if not analysis:
        st.caption("Le PDF et les données d'élèves restent uniquement sur cet ordinateur.")
        return

    cards = analysis["cards"]
    st.success(f"{len(cards)} portrait(s) détecté(s). Vérifie rapidement la grille ci-dessous.")
    st.caption("Décoche une vignette si ce n'est pas un élève ou si la découpe est mauvaise.")

    columns = st.columns(5)
    for index, card in enumerate(cards):
        with columns[index % 5]:
            with st.container(border=True):
                st.image(card["photo_bytes"], width=120)
                st.image(card["label_bytes"], width=180)
                st.checkbox("Garder", value=True, key=f"keep_card_{index}")

    selected_cards = [
        card for index, card in enumerate(cards) if st.session_state.get(f"keep_card_{index}", True)
    ]
    st.caption(f"{len(selected_cards)} portrait(s) seront ajoutés à « {analysis['class_name']} ».")

    b1, b2 = st.columns([2, 1])
    with b1:
        if st.button(
            "✅ Tout est bon — créer la classe",
            type="primary",
            use_container_width=True,
            disabled=not selected_cards,
        ):
            try:
                with st.spinner("Création de la classe…"):
                    class_id = create_class_from_cards(
                        analysis["class_name"], analysis["pdf_bytes"], selected_cards
                    )
                clear_analysis()
                st.session_state["selected_class_id"] = class_id
                st.session_state["nav"] = NAV_HOME
                st.session_state["welcome_message"] = "Classe créée avec succès."
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with b2:
        if st.button("↩️ Recommencer", use_container_width=True):
            clear_analysis()
            st.rerun()


def page_training(classes: list[dict]) -> None:
    st.title("🎓 Entraînement")
    if not classes:
        st.info("Ajoute d'abord une classe.")
        return

    labels = [f"{c['name']} · {c['student_count']} élèves" for c in classes]
    ids = [int(c["id"]) for c in classes]
    preferred = st.session_state.get("selected_class_id")
    default_index = ids.index(preferred) if preferred in ids else 0
    selected_label = st.selectbox("Classe", labels, index=default_index)
    class_id = ids[labels.index(selected_label)]
    st.session_state["selected_class_id"] = class_id

    status_metrics(class_id)
    st.caption("Séries de 10 : Mémorisé → Vu → Non commencé. Les acquis reviennent seulement quand toute la classe est acquise.")

    session_id = st.session_state.get("session_id")
    session = get_session(session_id) if session_id else None
    if not session or int(session["class_id"]) != class_id:
        open_session = get_today_open_session(class_id)
        if open_session:
            st.session_state["session_id"] = open_session["id"]
            session = open_session
        else:
            session = None

    if not session:
        st.button(
            "▶️ Commencer une série de 10",
            type="primary",
            use_container_width=True,
            on_click=start_training,
            args=(class_id,),
        )
        error = st.session_state.pop("friendly_error", None)
        if error:
            st.warning(error)
        return

    session = get_session(session["id"])
    if session and session.get("completed_at"):
        st.success("Série terminée 🎉")
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_revealed", None)
        st.button(
            "▶️ Continuer avec une nouvelle série",
            type="primary",
            use_container_width=True,
            on_click=start_training,
            args=(class_id,),
        )
        error = st.session_state.pop("friendly_error", None)
        if error:
            st.info(error)
        return

    progress = session_progress(session["id"])
    st.progress(progress["completed"] / max(1, progress["total"]))
    st.caption(f"Série : {progress['completed']}/{progress['total']} terminés · {progress['attempts']} questions")

    feedback = st.session_state.pop("feedback", None)
    if feedback:
        st.toast(feedback)

    if "current_student" not in st.session_state or st.session_state.get("current_student") is None:
        st.session_state["current_student"] = next_student(session["id"])
        st.session_state["answer_revealed"] = False

    student = st.session_state.get("current_student")
    if not student:
        st.success("Série terminée 🎉")
        return

    left, right = st.columns([1.05, 1])
    with left:
        st.image(student["photo_path"], caption="Qui est cet élève ?", width=420)
        st.caption(
            f"{STATUS_LABELS.get(student['status'], student['status'])} · "
            f"{student.get('correct_count', 0)}/3 réussites dans cette série"
        )

    with right:
        if not st.session_state.get("answer_revealed", False):
            st.markdown("## Donne son nom")
            st.write("Réponds mentalement ou à voix haute, puis vérifie.")
            st.button(
                "👀 Afficher le nom",
                type="primary",
                use_container_width=True,
                on_click=reveal_answer,
            )
        else:
            st.markdown("## Réponse")
            show_answer(student)
            st.markdown("### Tu l'avais ?")
            yes, no = st.columns(2)
            yes.button(
                "✅ Oui",
                type="primary",
                use_container_width=True,
                on_click=answer_current,
                args=(True,),
            )
            no.button(
                "❌ Non",
                use_container_width=True,
                on_click=answer_current,
                args=(False,),
            )
            st.caption("Après Oui/Non, l'élève suivant arrive automatiquement.")

    error = st.session_state.pop("friendly_error", None)
    if error:
        st.warning(error)


def page_manage(classes: list[dict]) -> None:
    st.title("🛠️ Gérer les classes")
    if not classes:
        st.info("Aucune classe à gérer.")
        return

    labels = {f"{c['name']} ({c['student_count']} élèves)": int(c["id"]) for c in classes}
    class_label = st.selectbox("Classe", list(labels))
    class_id = labels[class_label]
    class_row = next(c for c in classes if int(c["id"]) == class_id)
    status_metrics(class_id)

    st.subheader("Élèves")
    st.caption("Tu peux corriger les noms manuellement. L'étiquette découpée du PDF reste visible.")
    for student in get_students(class_id):
        title = f"{student['position']:02d} · {student_display_name(student)} · {STATUS_LABELS[student['status']]}"
        with st.expander(title):
            a, b, c = st.columns([1, 1.2, 1.4])
            with a:
                st.image(student["photo_path"], width=150)
            with b:
                if student.get("label_path") and Path(student["label_path"]).exists():
                    st.image(student["label_path"], caption="Nom dans le PDF", width=280)
                if student.get("memory_dates"):
                    st.caption("Cycle courant : " + " · ".join(student["memory_dates"]))
            with c:
                first = st.text_input("Prénom", value=student["first_name"], key=f"fn_{student['id']}")
                last = st.text_input("Nom", value=student["last_name"], key=f"ln_{student['id']}")
                if st.button("💾 Enregistrer", key=f"save_{student['id']}"):
                    update_student_name(student["id"], first, last)
                    st.success("Enregistré.")

    st.divider()
    with st.expander("🗑️ Supprimer cette classe"):
        st.warning("Cela supprime la classe, son PDF, ses portraits et toute sa progression.")
        typed = st.text_input(
            f"Pour confirmer, écris exactement : {class_row['name']}",
            key=f"delete_confirm_{class_id}",
        )
        if st.button(
            "Supprimer définitivement",
            disabled=typed != class_row["name"],
            type="primary",
            key=f"delete_{class_id}",
        ):
            delete_class(class_id)
            st.session_state.pop("session_id", None)
            st.session_state.pop("selected_class_id", None)
            st.session_state["nav"] = NAV_HOME
            st.rerun()


def page_backup() -> None:
    st.title("🛟 Sauvegarde & mise à jour")
    st.subheader("Sauvegarder mes données")
    st.write("La sauvegarde contient les classes, photos et toute la progression.")
    try:
        backup = create_backup_bytes()
        filename = f"FlashTrombi-sauvegarde-{datetime.now():%Y-%m-%d}.zip"
        st.download_button(
            "⬇️ Télécharger ma sauvegarde",
            data=backup,
            file_name=filename,
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )
    except Exception:
        st.error("Impossible de préparer la sauvegarde pour le moment.")

    st.subheader("Restaurer une sauvegarde")
    restore_file = st.file_uploader("Choisir une sauvegarde .zip", type=["zip"], key="restore_zip")
    confirm = st.checkbox("Je comprends que la restauration remplacera les données actuelles.")
    if st.button("♻️ Restaurer", disabled=not (restore_file and confirm)):
        try:
            restore_backup_bytes(restore_file.getvalue())
            for key in list(st.session_state):
                if key not in {"nav"}:
                    st.session_state.pop(key, None)
            st.success("Sauvegarde restaurée.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Mises à jour")
    st.caption(f"Version installée : {APP_VERSION}")
    if st.button("🔄 Vérifier les mises à jour"):
        with st.spinner("Vérification…"):
            st.session_state["update_check"] = check_for_update()
    result = st.session_state.get("update_check")
    if result:
        if result["available"]:
            st.success(result["message"])
            st.link_button("⬇️ Télécharger la nouvelle version", result["url"], use_container_width=True)
        else:
            st.info(result["message"])

    with st.expander("Dépannage"):
        st.caption("Tes données sont enregistrées ici :")
        st.code(str(DATA_DIR))
        st.write("Une mise à jour ou une réinstallation de l'application ne supprime pas ce dossier.")


def main() -> None:
    if "nav" not in st.session_state:
        st.session_state["nav"] = NAV_HOME

    with st.sidebar:
        st.markdown("## 🧑‍🏫 Flash Trombi")
        st.caption(f"v{APP_VERSION}")
        st.radio("Navigation", NAV_ITEMS, key="nav", label_visibility="collapsed")
        st.divider()
        st.caption("Données privées stockées uniquement sur cet ordinateur.")

    classes = list_classes()
    nav = st.session_state["nav"]

    welcome = st.session_state.pop("welcome_message", None)
    if welcome:
        st.toast(welcome)

    if nav == NAV_HOME:
        page_home(classes)
    elif nav == NAV_TRAIN:
        page_training(classes)
    elif nav == NAV_ADD:
        page_add_class()
    elif nav == NAV_MANAGE:
        page_manage(classes)
    else:
        page_backup()


try:
    main()
except Exception as exc:
    st.error("Flash Trombi a rencontré un problème inattendu.")
    st.write("Ferme puis relance l'application. Si le problème revient, fais une sauvegarde et conserve le message ci-dessous.")
    with st.expander("Détails techniques"):
        st.code(f"{type(exc).__name__}: {exc}")
