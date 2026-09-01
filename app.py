from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from progress_view import (
    STAGE_LABELS,
    STAGE_ORDER,
    daily_completion_ratio,
    display_stage,
    mastery_ratio,
    stage_counts,
)
from storage import (
    analyze_pdf,
    class_name_exists,
    create_backup_bytes,
    create_class_from_cards,
    delete_class,
    end_session,
    get_session,
    get_students,
    get_today_open_session_for_classes,
    init_db,
    list_classes,
    next_student,
    random_student,
    record_answer,
    restore_backup_bytes,
    session_progress,
    start_or_resume_session,
    update_student_name,
)
from updates import check_for_update

st.set_page_config(
    page_title="Flash Trombi",
    page_icon="🧑‍🏫",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()

NAV_TRAIN = "🎓 Entraînement"
NAV_RANDOM = "🎲 Élève au hasard"
NAV_PROGRESS = "📈 Mon avancée"
NAV_ADD = "➕ Ajouter une classe"
NAV_MANAGE = "🛠️ Gérer les classes"
NAV_BACKUP = "💾 Sauvegarde"
NAV_UPDATE = "⬆️ Mise à jour"

NAV_ITEMS = [
    NAV_TRAIN,
    NAV_RANDOM,
    NAV_PROGRESS,
    NAV_ADD,
    NAV_MANAGE,
    NAV_BACKUP,
    NAV_UPDATE,
]

MAIN_PHOTO_WIDTH = 357
MEMORISED_TOAST = "3 réussites : l'élève est mémorisé"
UPDATE_INTERVAL_SECONDS = 300


def student_display_name(student: dict) -> str:
    name = " ".join(
        part for part in [student.get("first_name", ""), student.get("last_name", "")] if part
    ).strip()
    return name or f"Élève {student['position']:02d}"


def selected_students(class_ids: list[int]) -> list[dict]:
    students: list[dict] = []
    for class_id in class_ids:
        students.extend(get_students(class_id))
    return students


def show_answer(student: dict) -> None:
    if student.get("first_name") or student.get("last_name"):
        st.markdown(f"## {student_display_name(student)}")
        return

    label_path = student.get("label_path")
    if label_path and Path(label_path).exists():
        st.image(label_path, caption="Nom sur le trombinoscope", width=500)
        st.caption("Tu peux corriger ce nom dans « Gérer les classes ».")
    else:
        st.warning("Nom non renseigné.")


def go_to(page: str) -> None:
    st.session_state["nav"] = page


def go_training(class_id: int, class_name: str) -> None:
    st.session_state["multi_class_mode"] = False
    st.session_state["class_radio"] = class_name
    st.session_state["nav"] = NAV_TRAIN
    _clear_working_selection_state()


def _clear_working_selection_state() -> None:
    for key in (
        "session_id",
        "current_student",
        "answer_revealed",
        "random_student",
        "random_recent",
        "friendly_error",
    ):
        st.session_state.pop(key, None)


def sync_selection_scope(active_ids: list[int]) -> None:
    """Clear displayed pupils immediately whenever the class selection changes."""
    scope = tuple(sorted(int(value) for value in active_ids))
    previous = st.session_state.get("selection_scope")
    if previous is None:
        st.session_state["selection_scope"] = scope
        return
    if tuple(previous) == scope:
        return

    st.session_state["selection_scope"] = scope
    _clear_working_selection_state()


def start_training(class_ids: list[int]) -> None:
    try:
        session = start_or_resume_session(class_ids)
        st.session_state["session_id"] = session["id"]
        st.session_state.pop("current_student", None)
        st.session_state["answer_revealed"] = False
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
        if result.get("message") == "Mémorisé pour aujourd'hui ✅":
            st.session_state["memorised_toast"] = True

        st.session_state["answer_revealed"] = False
        if result["session_finished"]:
            st.session_state.pop("current_student", None)
        else:
            st.session_state["current_student"] = next_student(session_id)
    except Exception as exc:
        st.session_state["friendly_error"] = str(exc)


def choose_random_student(class_ids: list[int]) -> None:
    recent = list(st.session_state.get("random_recent", []))[-5:]
    student = random_student(class_ids, recent)
    if student is None:
        st.session_state["friendly_error"] = "Aucun élève dans les classes sélectionnées."
        return
    st.session_state["random_student"] = student
    recent.append(int(student["id"]))
    st.session_state["random_recent"] = recent[-5:]


def clear_analysis() -> None:
    st.session_state.pop("pdf_analysis", None)
    for key in list(st.session_state):
        if key.startswith("keep_card_"):
            st.session_state.pop(key, None)


def delete_class_and_go_progress(class_id: int) -> None:
    delete_class(class_id)
    st.session_state.pop(f"multi_class_{class_id}", None)
    _clear_working_selection_state()
    st.session_state["nav"] = NAV_PROGRESS


def sidebar_class_selector(classes: list[dict]) -> list[int]:
    if not classes:
        return []

    names = [str(row["name"]) for row in classes]
    ids_by_name = {str(row["name"]): int(row["id"]) for row in classes}

    st.markdown("#### Classes")
    multi = st.toggle("Choisir plusieurs classes", key="multi_class_mode")

    if not multi:
        current = st.session_state.get("class_radio")
        if current not in names:
            st.session_state["class_radio"] = names[0]
        selected_name = st.radio(
            "Classe",
            names,
            key="class_radio",
            label_visibility="collapsed",
        )
        return [ids_by_name[selected_name]]

    active: list[int] = []
    current_single = st.session_state.get("class_radio")
    for row in classes:
        class_id = int(row["id"])
        key = f"multi_class_{class_id}"
        if key not in st.session_state:
            st.session_state[key] = str(row["name"]) == current_single
        if st.checkbox(str(row["name"]), key=key):
            active.append(class_id)

    if not active:
        st.caption("Choisis au moins une classe.")
    return active


def _cached_update_check(force: bool = False) -> dict | None:
    now = time.time()
    last = float(st.session_state.get("update_checked_at", 0.0) or 0.0)
    if force or "update_check" not in st.session_state or now - last >= UPDATE_INTERVAL_SECONDS:
        st.session_state["update_check"] = check_for_update()
        st.session_state["update_checked_at"] = now
    return st.session_state.get("update_check")


def _update_button() -> None:
    result = _cached_update_check()
    label = NAV_UPDATE
    if result and result.get("available"):
        label = "⬆️ Mise à jour  •"
    if st.button(label, key="nav_update", use_container_width=True):
        go_to(NAV_UPDATE)
        st.rerun()


if hasattr(st, "fragment"):
    _update_button = st.fragment(run_every=UPDATE_INTERVAL_SECONDS)(_update_button)


def render_sidebar(classes: list[dict]) -> list[int]:
    with st.sidebar:
        st.markdown("## 🧑‍🏫 Flash Trombi")
        st.caption("Apprendre les prénoms et les noms, sans friction.")

        st.markdown("#### Utiliser")
        for label in (NAV_TRAIN, NAV_RANDOM, NAV_PROGRESS):
            button_type = "primary" if st.session_state.get("nav") == label else "secondary"
            if st.button(label, key=f"nav_{label}", type=button_type, use_container_width=True):
                go_to(label)
                st.rerun()

        st.divider()
        active_ids = sidebar_class_selector(classes) if classes else []

        st.divider()
        st.markdown("#### Gérer")
        for label in (NAV_ADD, NAV_MANAGE, NAV_BACKUP):
            if st.button(label, key=f"nav_{label}", use_container_width=True):
                go_to(label)
                st.rerun()
        _update_button()

    return active_ids


def daily_progress_values(active_ids: list[int]) -> tuple[list[dict], float, int, int]:
    students = selected_students(active_ids)
    total = len(students)
    ratio = daily_completion_ratio(students) if students else 0.0
    done = round(ratio * total)
    return students, ratio, done, total


def render_vertical_progress(ratio: float, done: int, total: int) -> None:
    percent = max(0, min(100, round(ratio * 100)))
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:18px;margin:8px 0 16px 0;">
          <div style="height:210px;width:24px;background:rgba(128,128,128,.18);
                      border-radius:14px;position:relative;overflow:hidden;">
            <div style="position:absolute;bottom:0;left:0;right:0;height:{percent}%;
                        background:currentColor;border-radius:14px;"></div>
          </div>
          <div>
            <div style="font-size:2rem;font-weight:700;line-height:1;">{percent}%</div>
            <div style="opacity:.75;margin-top:6px;">{done}/{total} faits aujourd'hui</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_session_info(active_ids: list[int], session: dict | None) -> None:
    students, ratio, done, total = daily_progress_values(active_ids)
    st.markdown("### Aujourd'hui")
    render_vertical_progress(ratio, done, total)

    counts = stage_counts(students)
    if session and not session.get("completed_at"):
        progress = session_progress(session["id"])
        a, b = st.columns(2)
        a.metric("Dans la série", progress["active"])
        b.metric("Tentatives", progress["attempts"])

    st.caption(
        f"Nouveau {counts['new']} · Vu {counts['seen']} · "
        f"Mémorisé {counts['memorised']} · À réviser {counts['review']} · "
        f"Acquis {counts['acquired']}"
    )


def _resolve_training_session(active_ids: list[int]) -> dict | None:
    session_id = st.session_state.get("session_id")
    session = get_session(session_id) if session_id else None
    wanted_scope = sorted(active_ids)

    if not session or sorted(session.get("class_ids", [])) != wanted_scope:
        open_session = get_today_open_session_for_classes(active_ids)
        if open_session:
            st.session_state["session_id"] = open_session["id"]
            session = get_session(open_session["id"])
        else:
            session = None
            st.session_state.pop("session_id", None)
            st.session_state.pop("current_student", None)
            st.session_state.pop("answer_revealed", None)
    return session


def page_training(classes: list[dict], active_ids: list[int]) -> None:
    st.title("🎓 Entraînement")
    if not classes:
        st.info("Ajoute d'abord une classe.")
        return
    if not active_ids:
        st.info("Choisis au moins une classe dans la barre de gauche.")
        return

    active_names = [str(row["name"]) for row in classes if int(row["id"]) in active_ids]
    st.caption(" · ".join(active_names))

    if st.session_state.pop("memorised_toast", False):
        st.toast(MEMORISED_TOAST)

    session = _resolve_training_session(active_ids)

    if session and session.get("completed_at"):
        left, center, right = st.columns([0.9, 1.15, 1.1], gap="large")
        with left:
            render_session_info(active_ids, session)
        with center:
            st.markdown("## Session terminée 🎉")
            st.write("Tous les élèves de cette sélection sont mémorisés pour aujourd'hui ou acquis.")
            st.caption("Tu peux choisir une autre classe à gauche, ou continuer avec les mémorisés.")
        with right:
            st.markdown("### Et maintenant ?")
            st.button(
                "▶️ Continuer avec les mémorisés",
                type="primary",
                use_container_width=True,
                on_click=start_training,
                args=(list(active_ids),),
            )
            st.caption("Une réussite retire l'élève de la short-list. Une erreur le repasse en Vu.")
        return

    if not session:
        left, center, right = st.columns([0.9, 1.15, 1.1], gap="large")
        with left:
            render_session_info(active_ids, None)
        with center:
            st.markdown("## Prêt ?")
            st.write("Lance une série sur la sélection actuelle.")
        with right:
            st.button(
                "▶️ Commencer",
                type="primary",
                use_container_width=True,
                on_click=start_training,
                args=(list(active_ids),),
            )
            error = st.session_state.pop("friendly_error", None)
            if error:
                st.warning(error)
        return

    if st.session_state.get("current_student") is None:
        st.session_state["current_student"] = next_student(session["id"])
        st.session_state["answer_revealed"] = False

    student = st.session_state.get("current_student")
    if not student:
        st.session_state.pop("current_student", None)
        st.rerun()

    left, center, right = st.columns([0.9, 1.15, 1.1], gap="large")

    with left:
        render_session_info(active_ids, session)

    with center:
        st.image(student["photo_path"], caption="Qui est cet élève ?", width=MAIN_PHOTO_WIDTH)
        st.caption(f"{student.get('class_name', '')} · {STAGE_LABELS[display_stage(student)]}")

    with right:
        if not st.session_state.get("answer_revealed", False):
            st.markdown("### Donne son nom")
            st.button(
                "👀 Afficher le nom",
                type="primary",
                use_container_width=True,
                on_click=reveal_answer,
            )
        else:
            st.markdown("### Réponse")
            show_answer(student)
            st.markdown("#### Tu l'avais ?")
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

        st.divider()
        if st.button("⏹️ Arrêter la session", use_container_width=True):
            end_session(session["id"])
            _clear_working_selection_state()
            st.rerun()

        error = st.session_state.pop("friendly_error", None)
        if error:
            st.warning(error)


def page_random(classes: list[dict], active_ids: list[int]) -> None:
    st.title("🎲 Élève au hasard")
    st.caption("Pour désigner un élève au tableau ou choisir qui interroger. Ce tirage ne modifie jamais la progression.")

    if not active_ids:
        st.info("Choisis au moins une classe dans la barre de gauche.")
        return

    active_names = [str(row["name"]) for row in classes if int(row["id"]) in active_ids]
    st.caption(" · ".join(active_names))

    st.button(
        "🎲 Tirer un élève",
        type="primary",
        use_container_width=True,
        on_click=choose_random_student,
        args=(list(active_ids),),
    )

    student = st.session_state.get("random_student")
    if student and int(student["class_id"]) not in active_ids:
        st.session_state.pop("random_student", None)
        student = None
    if not student:
        return

    left, right = st.columns([1, 1.2], gap="large")
    with left:
        st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)
    with right:
        st.markdown("### Élève désigné")
        st.markdown(f"# {student_display_name(student)}")
        st.caption(student.get("class_name", ""))
        st.button(
            "🎲 Tirer quelqu'un d'autre",
            use_container_width=True,
            on_click=choose_random_student,
            args=(list(active_ids),),
            key="random_again",
        )


def page_progress(classes: list[dict], active_ids: list[int]) -> None:
    st.title("📈 Mon avancée")
    if not classes:
        st.info("Ajoute une classe pour commencer.")
        return
    if not active_ids:
        st.info("Choisis au moins une classe dans la barre de gauche.")
        return

    students, daily_ratio, done, total = daily_progress_values(active_ids)
    mastery = mastery_ratio(students)

    a, b = st.columns(2)
    with a:
        st.markdown("### Aujourd'hui")
        st.progress(daily_ratio)
        st.caption(f"{done}/{total} mémorisé(s) aujourd'hui ou acquis")
    with b:
        st.markdown("### Maîtrise globale")
        st.progress(mastery)
        st.caption(f"{round(mastery * 100)} % de maîtrise sur la sélection")

    counts = stage_counts(students)
    cols = st.columns(5)
    for col, stage in zip(cols, STAGE_ORDER):
        col.metric(STAGE_LABELS[stage], counts[stage])

    st.divider()
    st.subheader("Par classe")
    for row in classes:
        class_id = int(row["id"])
        if class_id not in active_ids:
            continue
        class_students = get_students(class_id)
        class_daily = daily_completion_ratio(class_students)
        class_mastery = mastery_ratio(class_students)
        with st.container(border=True):
            c1, c2, c3 = st.columns([1.3, 2, 2])
            c1.markdown(f"**{row['name']}**")
            c1.caption(f"{len(class_students)} élève(s)")
            c2.progress(class_daily)
            c2.caption(f"Aujourd'hui · {round(class_daily * 100)} %")
            c3.progress(class_mastery)
            c3.caption(f"Maîtrise · {round(class_mastery * 100)} %")


def page_add_class() -> None:
    st.title("➕ Ajouter une classe")
    st.write("Choisis le trombinoscope et donne un nom à la classe.")

    c1, c2 = st.columns([1, 2])
    with c1:
        class_name = st.text_input("Nom de la classe", placeholder="ex. TG4")
    with c2:
        uploaded = st.file_uploader("Trombinoscope PDF", type=["pdf"])

    can_analyze = bool(class_name.strip() and uploaded is not None)
    if st.button("🔎 Vérifier le trombinoscope", type="primary", disabled=not can_analyze):
        name = class_name.strip()
        if class_name_exists(name):
            st.error("Une classe portant ce nom existe déjà. Choisis un autre nom.")
        else:
            try:
                pdf_bytes = uploaded.getvalue()
                with st.spinner("Lecture du trombinoscope…"):
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
                st.error(
                    "Je n'ai pas réussi à lire ce PDF. "
                    "Essaie de l'imprimer de nouveau en PDF puis réimporte-le."
                )

    analysis = st.session_state.get("pdf_analysis")
    if not analysis:
        return

    cards = analysis["cards"]
    named = sum(bool(card.get("first_name") or card.get("last_name")) for card in cards)
    st.write(f"{len(cards)} portrait(s) détecté(s) · {named} nom(s) trouvé(s).")
    st.caption("Vérifie rapidement les portraits. Tu pourras corriger les noms plus tard.")

    columns = st.columns(5)
    for index, card in enumerate(cards):
        with columns[index % 5]:
            with st.container(border=True):
                st.image(card["photo_bytes"], width=120)
                detected = " ".join(
                    part for part in [card.get("first_name", ""), card.get("last_name", "")] if part
                ).strip()
                if detected:
                    st.markdown(f"**{detected}**")
                else:
                    st.image(card["label_bytes"], width=190)
                st.checkbox("Garder", value=True, key=f"keep_card_{index}")

    selected_cards = [
        card for index, card in enumerate(cards) if st.session_state.get(f"keep_card_{index}", True)
    ]

    b1, b2 = st.columns([2, 1])
    with b1:
        if st.button(
            "✅ Créer la classe",
            type="primary",
            use_container_width=True,
            disabled=not selected_cards,
        ):
            try:
                with st.spinner("Création de la classe…"):
                    create_class_from_cards(
                        analysis["class_name"], analysis["pdf_bytes"], selected_cards
                    )
                created_name = str(analysis["class_name"])
                clear_analysis()
                st.session_state["multi_class_mode"] = False
                st.session_state["class_radio"] = created_name
                st.session_state["pending_nav"] = NAV_PROGRESS
                st.rerun()
            except Exception:
                st.error("La classe n'a pas pu être créée. Réessaie une fois.")
    with b2:
        if st.button("↩️ Recommencer", use_container_width=True):
            clear_analysis()
            st.rerun()


def page_manage(classes: list[dict]) -> None:
    st.title("🛠️ Gérer les classes")
    if not classes:
        st.info("Aucune classe à gérer.")
        return

    labels = {f"{c['name']} ({c['student_count']} élèves)": int(c["id"]) for c in classes}
    class_label = st.selectbox("Classe", list(labels))
    class_id = labels[class_label]
    class_row = next(c for c in classes if int(c["id"]) == class_id)
    students = get_students(class_id)

    st.subheader("Élèves")
    st.caption("Tu peux corriger un prénom ou un nom à tout moment.")
    for student in students:
        stage = STAGE_LABELS[display_stage(student)]
        title = f"{student['position']:02d} · {student_display_name(student)} · {stage}"
        with st.expander(title):
            a, b, c = st.columns([1, 1.2, 1.4])
            with a:
                st.image(student["photo_path"], width=150)
            with b:
                if student.get("label_path") and Path(student["label_path"]).exists():
                    st.image(student["label_path"], caption="Nom sur le trombinoscope", width=340)
            with c:
                first = st.text_input("Prénom", value=student["first_name"], key=f"fn_{student['id']}")
                last = st.text_input("Nom", value=student["last_name"], key=f"ln_{student['id']}")
                if st.button("💾 Enregistrer", key=f"save_{student['id']}"):
                    update_student_name(student["id"], first, last)

    st.divider()
    with st.expander("🗑️ Supprimer cette classe"):
        st.warning("Cela supprimera cette classe et toute sa progression.")
        typed = st.text_input(
            f"Pour confirmer, écris exactement : {class_row['name']}",
            key=f"delete_confirm_{class_id}",
        )
        st.button(
            "Supprimer définitivement",
            disabled=typed != class_row["name"],
            type="primary",
            key=f"delete_{class_id}",
            on_click=delete_class_and_go_progress,
            args=(class_id,),
        )


def page_backup() -> None:
    st.title("💾 Sauvegarde")
    st.write(
        "Flash Trombi enregistre automatiquement tes classes et ta progression sur ce PC. "
        "Tu n'as rien à sauvegarder après chaque séance."
    )
    st.info(
        "La sauvegarde ZIP sert surtout à transférer Flash Trombi vers un autre PC, "
        "à conserver une copie de sécurité ou à récupérer tes données après une réinstallation."
    )

    st.subheader("Créer une copie")
    try:
        backup = create_backup_bytes()
        filename = f"FlashTrombi-sauvegarde-{datetime.now():%Y-%m-%d}.zip"
        st.download_button(
            "⬇️ Télécharger ma sauvegarde",
            data=backup,
            file_name=filename,
            mime="application/zip",
            type="primary",
        )
    except Exception:
        st.error("Impossible de préparer la sauvegarde pour le moment.")

    st.divider()
    st.subheader("Restaurer une copie")
    st.caption("La restauration remplace les classes et la progression actuellement présentes sur ce PC.")
    restore_file = st.file_uploader("Choisir une sauvegarde .zip", type=["zip"], key="restore_zip")
    confirm = st.checkbox("Je comprends que mes données actuelles seront remplacées.")
    if st.button("♻️ Restaurer", disabled=not (restore_file and confirm)):
        try:
            restore_backup_bytes(restore_file.getvalue())
            for key in list(st.session_state):
                if key not in {"nav"}:
                    st.session_state.pop(key, None)
            st.rerun()
        except Exception:
            st.error("Cette sauvegarde n'a pas pu être restaurée.")


def page_update() -> None:
    st.title("⬆️ Mise à jour")
    result = _cached_update_check(force=True)
    if not result:
        st.info("Impossible de vérifier les mises à jour maintenant.")
        return

    if result.get("available"):
        st.success(result["message"])
        download_url = result.get("download_url") or result.get("url")
        st.link_button(
            "⬇️ Télécharger la nouvelle version",
            download_url,
            type="primary",
            use_container_width=True,
        )
        st.caption("Le téléchargement démarre directement sur l'installateur Windows.")
    else:
        st.write(result["message"])

    st.caption("Flash Trombi vérifie automatiquement les nouvelles versions toutes les 5 minutes.")


def main() -> None:
    pending_nav = st.session_state.pop("pending_nav", None)
    if pending_nav in NAV_ITEMS:
        st.session_state["nav"] = pending_nav

    if st.session_state.get("nav") not in NAV_ITEMS:
        st.session_state["nav"] = NAV_TRAIN

    classes = list_classes()
    active_ids = render_sidebar(classes)
    sync_selection_scope(active_ids)

    nav = st.session_state["nav"]
    if nav == NAV_TRAIN:
        page_training(classes, active_ids)
    elif nav == NAV_RANDOM:
        page_random(classes, active_ids)
    elif nav == NAV_PROGRESS:
        page_progress(classes, active_ids)
    elif nav == NAV_ADD:
        page_add_class()
    elif nav == NAV_MANAGE:
        page_manage(classes)
    elif nav == NAV_BACKUP:
        page_backup()
    else:
        page_update()


try:
    main()
except Exception:
    st.error("Flash Trombi a rencontré un problème. Ferme puis relance l'application.")
