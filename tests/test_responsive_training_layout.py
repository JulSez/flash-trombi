from __future__ import annotations

import unittest
from pathlib import Path


class ResponsiveTrainingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app.py").read_text(encoding="utf-8")

    def test_training_photo_adapts_to_viewport_height(self):
        self.assertIn('max-height: min(48vh, 430px) !important;', self.source)
        self.assertIn('@media (max-height: 820px)', self.source)
        self.assertIn('max-height: 43vh !important;', self.source)
        self.assertIn('@media (max-height: 700px)', self.source)
        self.assertIn('max-height: 38vh !important;', self.source)

    def test_training_uses_balanced_two_content_zones(self):
        self.assertIn('main_area, analytics = st.columns([2, 1], gap="medium")', self.source)
        self.assertNotIn('left, center, right = st.columns([0.9, 1.15, 1.1]', self.source)

    def test_question_is_prominent_and_name_is_compact(self):
        self.assertIn('.training-question {', self.source)
        self.assertIn('font-size: clamp(1.35rem, 2vw, 1.85rem);', self.source)
        self.assertIn('.training-answer-name {', self.source)
        self.assertIn('font-size: clamp(1.05rem, 1.45vw, 1.35rem);', self.source)

    def test_training_hides_redundant_class_captions(self):
        training_start = self.source.index("def page_training(")
        training_end = self.source.index("\ndef page_random(", training_start)
        training = self.source[training_start:training_end]
        self.assertNotIn('st.caption(" · ".join(active_names))', training)
        self.assertNotIn("STAGE_LABELS[display_stage(student)]", training)

    def test_yes_no_buttons_never_wrap(self):
        training_start = self.source.index("def page_training(")
        training_end = self.source.index("\ndef page_random(", training_start)
        training = self.source[training_start:training_end]
        self.assertIn('horizontal=True', training)
        self.assertIn('wrap=False', training)
        self.assertIn('key="training_answer_buttons"', training)
        self.assertNotIn('yes, no = st.columns(2)', training)

    def test_question_and_cta_live_with_photo(self):
        training_start = self.source.index("def page_training(")
        training_end = self.source.index("\ndef page_random(", training_start)
        training = self.source[training_start:training_end]
        photo = training.index('st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)')
        question = training.index('training-question', photo)
        cta = training.index('"👀 Afficher le nom"', question)
        analytics = training.index("with analytics:", cta)
        self.assertLess(photo, question)
        self.assertLess(question, cta)
        self.assertLess(cta, analytics)


if __name__ == "__main__":
    unittest.main()
