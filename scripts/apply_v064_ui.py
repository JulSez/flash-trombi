from pathlib import Path


APP = Path("app.py")
text = APP.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"Expected app.py fragment not found: {old[:80]!r}")
    text = text.replace(old, new, 1)


replace_once("MAIN_PHOTO_WIDTH = 300", "MAIN_PHOTO_WIDTH = 270")
replace_once(
    '        st.markdown(f"## {student_display_name(student)}")',
    '        st.markdown(f"### {student_display_name(student)}")',
)

training_start = text.index("def page_training(")
training_end = text.index("\ndef page_random(", training_start)
training = text[training_start:training_end]
training = training.replace('        st.markdown("### Quel est son nom ?")', '        st.markdown("**Quel est son nom ?**")')
training = training.replace("                use_container_width=True,\n", "")
training = training.replace("            use_container_width=True,\n", "")
training = training.replace(
    '        st.divider()\n        if st.button("⏹️ Arrêter la session"):',
    '        if st.button("⏹️ Arrêter"): ',
)
# Normalize the compact stop button line if the replacement above matched.
training = training.replace('if st.button("⏹️ Arrêter"): \n', 'if st.button("⏹️ Arrêter"):\n')
text = text[:training_start] + training + text[training_end:]

progress_start = text.index("def page_progress(")
progress_end = text.index("\ndef page_add_class(", progress_start)
new_progress = '''def page_progress(classes: list[dict], active_ids: list[int]) -> None:
    st.title("📈 Mon avancée")
    if not classes:
        st.info("Ajoute une classe pour commencer.")
        return

    all_ids = [int(row["id"]) for row in classes]
    students, daily_ratio, done, total = daily_progress_values(all_ids)
    mastery = mastery_ratio(students)
    st.caption("Vue d'ensemble · toutes les classes")

    a, b = st.columns(2)
    with a:
        st.markdown("### Aujourd'hui")
        st.progress(daily_ratio)
        st.caption(f"{done}/{total} mémorisé(s) aujourd'hui ou acquis")
    with b:
        st.markdown("### Maîtrise globale")
        st.progress(mastery)
        st.caption(f"{round(mastery * 100)} % de maîtrise sur toutes les classes")

    counts = stage_counts(students)
    cols = st.columns(5)
    for col, stage in zip(cols, STAGE_ORDER):
        col.metric(STAGE_LABELS[stage], counts[stage])

    st.divider()
    st.subheader("Par classe")
    for row in classes:
        class_id = int(row["id"])
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

'''
text = text[:progress_start] + new_progress + text[progress_end + 1:]

APP.write_text(text, encoding="utf-8")
