from __future__ import annotations

import unittest
from pathlib import Path


class V064UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app.py").read_text(encoding="utf-8")

    def test_training_photo_and_ctas_are_compact(self):
        self.assertIn("MAIN_PHOTO_WIDTH = 270", self.source)
        start = self.source.index("def page_training(")
        end = self.source.index("\ndef page_random(", start)
        training = self.source[start:end]
        self.assertIn('st.markdown("**Quel est son nom ?**")', training)
        self.assertNotIn("use_container_width=True", training)
        self.assertIn('st.button("⏹️ Arrêter")', training)

    def test_progress_page_uses_all_classes(self):
        start = self.source.index("def page_progress(")
        end = self.source.index("\ndef page_add_class(", start)
        progress = self.source[start:end]
        self.assertIn('all_ids = [int(row["id"]) for row in classes]', progress)
        self.assertIn("daily_progress_values(all_ids)", progress)
        self.assertIn("Vue d'ensemble · toutes les classes", progress)
        self.assertNotIn("if class_id not in active_ids", progress)


if __name__ == "__main__":
    unittest.main()
