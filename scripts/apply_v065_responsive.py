from pathlib import Path

path = Path("app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"Missing expected fragment: {label}")
    text = text.replace(old, new, 1)


replace_once(
'''st.markdown(
    """
    <style>
    @media (max-width: 820px) {
      section.main div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
      }
      section.main div[data-testid="column"] {
        flex: 1 1 100% !important;
        width: 100% !important;
        min-width: 100% !important;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
''',
'''st.markdown(
    """
    <style>
    .block-container {
      padding-top: clamp(0.65rem, 1.4vh, 1.25rem);
      padding-bottom: 0.75rem;
    }

    section.main div[data-testid="stImage"] img {
      width: auto !important;
      height: auto !important;
      max-width: min(100%, 270px) !important;
      max-height: min(48vh, 430px) !important;
      object-fit: contain;
    }

    .training-question {
      font-size: clamp(1.35rem, 2vw, 1.85rem);
      font-weight: 750;
      line-height: 1.15;
      margin: 0.35rem 0 0.45rem;
    }

    .training-answer-name {
      font-size: clamp(1.05rem, 1.45vw, 1.35rem);
      font-weight: 650;
      line-height: 1.2;
      margin: 0.35rem 0 0.4rem;
    }

    .st-key-training_answer_buttons {
      gap: 0.45rem !important;
      overflow-x: visible !important;
    }

    .st-key-training_answer_buttons button {
      min-height: 2rem;
      padding: 0.28rem 0.8rem;
    }

    @media (max-height: 820px) {
      .block-container {
        padding-top: 0.4rem;
      }
      section.main div[data-testid="stImage"] img {
        max-height: 43vh !important;
      }
      section.main h1 {
        font-size: clamp(1.8rem, 4.2vh, 2.45rem);
        margin-bottom: 0.2rem;
      }
      section.main [data-testid="stMetricValue"] {
        font-size: 1.65rem;
      }
    }

    @media (max-height: 700px) {
      section.main div[data-testid="stImage"] img {
        max-height: 38vh !important;
      }
      .training-question {
        margin-top: 0.2rem;
      }
    }

    @media (max-width: 720px) {
      section.main div[data-testid="stImage"] img {
        max-width: min(100%, 240px) !important;
        max-height: 40vh !important;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
''',
"responsive stylesheet",
)

replace_once(
'''    if student.get("first_name") or student.get("last_name"):
        st.markdown(f"### {student_display_name(student)}")
        return
''',
'''    if student.get("first_name") or student.get("last_name"):
        st.markdown(
            f'<div class="training-answer-name">{student_display_name(student)}</div>',
            unsafe_allow_html=True,
        )
        return
''',
"compact revealed name",
)

replace_once(
'''    active_names = [str(row["name"]) for row in classes if int(row["id"]) in active_ids]
    st.caption(" · ".join(active_names))

    if st.session_state.pop("memorised_toast", False):
''',
'''    if st.session_state.pop("memorised_toast", False):
''',
"remove training class caption",
)

replace_once(
'''    main_area, analytics = st.columns([2.05, 1], gap="large")
''',
'''    main_area, analytics = st.columns([2, 1], gap="medium")
''',
"balanced training columns",
)

replace_once(
'''        st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)
        st.markdown("**Quel est son nom ?**")
        st.caption(f"{student.get('class_name', '')} · {STAGE_LABELS[display_stage(student)]}")
''',
'''        st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)
        st.markdown(
            '<div class="training-question">Quel est son nom ?</div>',
            unsafe_allow_html=True,
        )
''',
"training question and student caption",
)

replace_once(
'''            show_answer(student)
            st.markdown("#### Tu l'avais ?")
            yes, no = st.columns(2)
            yes.button(
                "✅ Oui",
                type="primary",
                on_click=answer_current,
                args=(True,),
            )
            no.button(
                "❌ Non",
                on_click=answer_current,
                args=(False,),
            )
''',
'''            show_answer(student)
            st.markdown("**Tu l'avais ?**")
            with st.container(
                horizontal=True,
                wrap=False,
                key="training_answer_buttons",
                gap="xsmall",
            ):
                st.button(
                    "✅ Oui",
                    type="primary",
                    on_click=answer_current,
                    args=(True,),
                )
                st.button(
                    "❌ Non",
                    on_click=answer_current,
                    args=(False,),
                )
''',
"nowrap answer buttons",
)

path.write_text(text, encoding="utf-8")
