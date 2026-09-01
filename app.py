from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import streamlit as st

from practice_mode import (
    answer_practice,
    create_practice_session,
    current_practice_student,
    only_memorised_remain,
)
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
    get_today_open_session,
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

NAV_HOME = "🏠 Mes classes"
NAV_TRAIN = "🎓 Entraînement"
NAV_RANDOM = "🎲 Élève au hasard"
NAV_ADD = "➕ Ajouter une classe"
NAV_MANAGE = "🛠️ Gérer les classes"
NAV_BACKUP = "🛟 Sauvegarde & mise à jour"
NAV_ITEMS = [NAV_HOME, NAV_TRAIN, NAV_RANDOM, NAV_ADD, NAV_MANAGE, NAV_BACKUP]

MAIN_PHOTO_WIDTH = 357
MEMORISED_TOAST = "3 réussites : l'élève est mémorisé"


def student_display_name(student: dict) -> str:
    name = " ".join(
        part for part in [student.get("first_name", ""), student.get("last_name", "")] if part
    ).strip()
    return name or f"Élève {student['position']:02d}"


def show_answer(student: dict) -> None:
    if student.get("first_name") or student.get("last_name"):
        st.success(student_display_name(student))
        return

    label_path = student.get("label_path")
    if label_path and Path(label_path).exists():
        st.image(label_path, caption="Nom sur le trombinoscope", width=500)
        st.caption("Tu peux corriger ce nom dans « Gérer les classes ».")
    else:
        st.warning("Nom non renseigné.")


def go_to(page: str) -> None:
    st.session_state["nav"] = page
    if page != NAV_TRAIN:
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_revealed", None)


def go_training(class_id: int, class_name: str) -> None:
    st.session_state["multi_class_mode"] = False
    st.session_state["class_radio"] = class_name
    st.session_state["nav"] = NAV_TRAIN
    st.session_state.pop("session_id", None)
    st.session_state.pop("practice_session", None)
    st.session_state.pop("current_student", None)
    st.session_state.pop("answer_revealed", None)
    st.session_state.pop("memorised_toast", None)


def selected_students(class_ids: list[int]) -> list[dict]:
    selected: list[dict] = []
    for class_id in class_ids:
        selected.extend(get_students(class_id))
    return selected


def _start_memorised_practice(class_ids: list[int], students: list[dict]) -> bool:
    if not only_memorised_remain(students):
        return False
    practice = create_practice_session(class_ids, students, limit=10)
    st.session_state["practice_session"] = practice
    st.session_state.pop("session_id", None)
    st.session_state.pop("current_student", None)
    st.session_state["answer_revealed"] = False
    return True


def start_training(class_ids: list[int]) -> None:
    try:
        session = start_or_resume_session(class_ids)
        st.session_state["session_id"] = session["id"]
        st.session_state.pop("practice_session", None)
        st.session_state.pop("current_student", None)
        st.session_state["answer_revealed"] = False
    except Exception as exc:
        students = selected_students(class_ids)
        if "Rien à travailler aujourd'hui" in str(exc) and _start_memorised_practice(class_ids, students):
            return
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


def answer_practice_current(correct: bool) -> None:
    practice = st.session_state.get("practice_session")
    if not practice:
        return
    answer_practice(practice, correct)
    st.session_state["practice_session"] = practice
    st.session_state["answer_revealed"] = False


def stop_practice() -> None:
    st.session_state.pop("practice_session", None)
    st.session_state.pop("answer_revealed", None)


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


def delete_class_and_go_home(class_id: int) -> None:
    delete_class(class_id)
    st.session_state.pop(f"multi_class_{class_id}", None)
    st.session_state.pop("session_id", None)
    st.session_state.pop("practice_session", None)
    st.session_state.pop("current_student", None)
    st.session_state.pop("answer_revealed", None)
    st.session_state["nav"] = NAV_HOME


def sidebar_class_selector(classes: list[dict]) -> list[int]:
    if not classes:
        return []

    names = [str(row["name"]) for row in classes]
    ids_by_name = {str(row["name"]): int(row["id"]) for row in classes}

    st.markdown("### Classes")
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


def sidebar_day_progress(active_ids: list[int]) -> None:
    if not active_ids:
        return
    students = selected_students(active_ids)
    ratio = daily_completion_ratio(students)
    st.markdown("### Aujourd'hui")
    st.progress(ratio)
    done = round(ratio * len(students))
    st.caption(f"{done}/{len(students)} mémorisé(s) ou acquis")


def status_metrics(students: list[dict]) -> None:
    counts = stage_counts(students)
    cols = st.columns(5)
    for col, stage in zip(cols, STAGE_ORDER):
        col.metric(STAGE_LABELS[stage], counts[stage])


def page_home(classes: list[dict]) -> None:
    st.title("🧑‍🏫 Flash Trombi")
    st.caption("Apprendre les noms de tes élèves, simplement.")

    if not classes:
        st.info("Tu n'as encore aucune classe.")
        st.button(
            "➕ Ajouter ma première classe",
            type="primary",
            use_container_width=True,
            on_click=go_to,
            args=(NAV_ADD,),
        )
        return

    st.subheader("Mes classes")
    for class_row in classes:
        class_id = int(class_row["id"])
        students = get_students(class_id)
        total = len(students)
        ratio = mastery_ratio(students)

        with st.container(border=True):
            left, middle, right = st.columns([2.1, 2.3, 1.2])
            with left:
                st.markdown(f"### {class_row['name']}")
                st.caption(f"{total} élève(s)")
            with middle:
                st.progress(ratio)
            with right:
                open_session = get_today_open_session(class_id)
                label = "▶️ Reprendre" if open_session else "▶️ Continuer"
                st.button(
                    label,
                    key=f"home_train_{class_id}",
                    type="primary",
                    use_container_width=True,
                    on_click=go_training,
                    args=(class_id, str(class_row["name"])),
                )

    st.button("➕ Ajouter une classe", on_click=go_to, args=(NAV_ADD,))


def page_add_class() -> None:
    st.title("➕ Ajouter une classe")
    st.write("Choisis le trombinoscope et donne un nom à la classe.")

    c1, c2 = st.columns([1, 2])
    with c1:
        class_name = st.text_input("Nom de la classe", placeholder="ex. TSTI2D3")
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
    st.success(f"{len(cards)} portrait(s) détecté(s) · {named} nom(s) trouvé(s).")
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
                st.session_state["pending_nav"] = NAV_HOME
                st.rerun()
            except Exception:
                st.error("La classe n'a pas pu être créée. Réessaie une fois.")
    with b2:
        if st.button("↩️ Recommencer", use_container_width=True):
            clear_analysis()
            st.rerun()


def render_practice(active_ids: list[int]) -> bool:
    practice = st.session_state.get("practice_session")
    if not practice:
        return False

    if sorted(practice.get("class_ids", [])) != sorted(active_ids):
        stop_practice()
        return False

    if practice.get("completed"):
        st.success("Série terminée 🎉")
        st.caption("Les ratés ont été revus à la fin.")
        st.button(
            "▶️ Refaire une série",
            type="primary",
            use_container_width=True,
            on_click=start_training,
            args=(list(active_ids),),
        )
        return True

    student = current_practice_student(practice)
    if not student:
        practice["completed"] = True
        st.session_state["practice_session"] = practice
        st.rerun()

    if practice.get("phase") == "first":
        question_no = min(int(practice.get("first_done", 0)) + 1, int(practice.get("first_total", 1)))
        st.caption(f"Révision express · question {question_no}/{practice['first_total']}")
    else:
        st.caption("Retour sur les ratés")

    left, right = st.columns([1.05, 1])
    with left:
        st.image(student["photo_path"], caption="Qui est cet élève ?", width=MAIN_PHOTO_WIDTH)
        st.caption(f"{student.get('class_name', '')} · Mémorisé")

    with right:
        if not st.session_state.get("answer_revealed", False):
            st.markdown("## Donne son nom")
            st.button(
                "👀 Afficher le nom",
                type="primary",
                use_container_width=True,
                on_click=reveal_answer,
                key="practice_reveal",
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
                on_click=answer_practice_current,
                args=(True,),
                key="practice_yes",
            )
            no.button(
                "❌ Non",
                use_container_width=True,
                on_click=answer_practice_current,
                args=(False,),
                key="practice_no",
            )

    st.button("⏹️ Arrêter", on_click=stop_practice, key="stop_practice")
    return True


def page_training(classes: list[dict], active_ids: list[int]) -> None:
    st.title("🎓 Entraînement")
    if not classes:
        st.info("Ajoute d'abord une classe.")
        return
    if not active_ids:
        st.info("Choisis au moins une classe dans la barre de gauche.")
        return

    active_names = [row["name"] for row in classes if int(row["id"]) in active_ids]
    st.caption(" · ".join(active_names))
    status_metrics(selected_students(active_ids))

    if st.session_state.pop("memorised_toast", False):
        st.toast(MEMORISED_TOAST)

    if render_practice(active_ids):
        return

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

    if not session:
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

    if session.get("completed_at"):
        st.success("C'est bon pour aujourd'hui 🎉")
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_revealed", None)
        st.button(
            "▶️ Continuer",
            type="primary",
            use_container_width=True,
            on_click=start_training,
            args=(list(active_ids),),
        )
        return

    progress = session_progress(session["id"])
    st.caption(f"{progress['active']} élève(s) en cours")

    if "current_student" not in st.session_state or st.session_state.get("current_student") is None:
        st.session_state["current_student"] = next_student(session["id"])
        st.session_state["answer_revealed"] = False

    student = st.session_state.get("current_student")
    if not student:
        st.success("C'est bon pour aujourd'hui 🎉")
        return

    left, right = st.columns([1.05, 1])
    with left:
        st.image(student["photo_path"], caption="Qui est cet élève ?", width=MAIN_PHOTO_WIDTH)
        st.caption(f"{student.get('class_name', '')} · {STAGE_LABELS[display_stage(student)]}")

    with right:
        if not st.session_state.get("answer_revealed", False):
            st.markdown("## Donne son nom")
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

    error = st.session_state.pop("friendly_error", None)
    if error:
        st.warning(error)

    if st.button("⏹️ Arrêter"):
        end_session(session["id"])
        st.session_state.pop("session_id", None)
        st.session_state.pop("current_student", None)
        st.session_state.pop("answer_revealed", None)
        st.rerun()


def page_random(classes: list[dict], active_ids: list[int]) -> None:
    st.title("🎲 Élève au hasard")
    st.caption("Pour désigner un élève au tableau ou choisir qui interroger.")
    if not active_ids:
        st.info("Choisis au moins une classe dans la barre de gauche.")
        return

    active_names = [row["name"] for row in classes if int(row["id"]) in active_ids]
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
        student = None
        st.session_state.pop("random_student", None)
    if not student:
        return

    left, right = st.columns([1, 1.2])
    with left:
        st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)
    with right:
        st.markdown("## Élève désigné")
        st.markdown(f"# {student_display_name(student)}")
        st.caption(student.get("class_name", ""))
        st.button(
            "🎲 Tirer quelqu'un d'autre",
            use_container_width=True,
            on_click=choose_random_student,
            args=(list(active_ids),),
            key="random_again",
        )


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
    status_metrics(students)

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
                    st.success("Enregistré.")

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
            on_click=delete_class_and_go_home,
            args=(class_id,),
        )


def page_backup() -> None:
    st.title("🛟 Sauvegarde & mise à jour")
    st.subheader("Sauvegarder")
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

    st.subheader("Restaurer")
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


def main() -> None:
    pending_nav = st.session_state.pop("pending_nav", None)
    if pending_nav in NAV_ITEMS:
        st.session_state["nav"] = pending_nav

    if "nav" not in st.session_state:
        st.session_state["nav"] = NAV_HOME

    classes = list_classes()

    with st.sidebar:
        st.markdown("## 🧑‍🏫 Flash Trombi")
        st.radio("Navigation", NAV_ITEMS, key="nav", label_visibility="collapsed")
        if classes:
            st.divider()
            active_ids = sidebar_class_selector(classes)
            st.divider()
            sidebar_day_progress(active_ids)
        else:
            active_ids = []

    nav = st.session_state["nav"]

    if nav == NAV_HOME:
        page_home(classes)
    elif nav == NAV_TRAIN:
        page_training(classes, active_ids)
    elif nav == NAV_RANDOM:
        page_random(classes, active_ids)
    elif nav == NAV_ADD:
        page_add_class()
    elif nav == NAV_MANAGE:
        page_manage(classes)
    else:
        page_backup()


try:
    main()
except Exception:
    st.error("Flash Trombi a rencontré un problème. Ferme puis relance l'application.")
