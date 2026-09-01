from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_streamlit_args_force_production_mode_before_custom_port(self):
        args = launcher.streamlit_args(Path("app.py"), 8765)
        self.assertIn("--global.developmentMode=false", args)
        self.assertIn("--server.port=8765", args)
        self.assertLess(
            args.index("--global.developmentMode=false"),
            args.index("--server.port=8765"),
        )

    def test_streamlit_args_hide_deploy_toolbar(self):
        args = launcher.streamlit_args(Path("app.py"), 8765)
        self.assertIn("--client.toolbarMode=minimal", args)

    def test_selected_port_can_be_fixed_for_packaged_smoke_test(self):
        with patch.dict(os.environ, {"FLASH_TROMBI_PORT": "8765"}, clear=False):
            self.assertEqual(8765, launcher.selected_port())


if __name__ == "__main__":
    unittest.main()
