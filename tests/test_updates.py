from __future__ import annotations

import unittest

from updates import _installer_download_url, _version_tuple


class UpdateTests(unittest.TestCase):
    def test_prefers_versioned_windows_installer(self):
        payload = {
            "assets": [
                {
                    "name": "notes.txt",
                    "browser_download_url": "https://example.test/notes.txt",
                },
                {
                    "name": "FlashTrombi_v0.6.2.exe",
                    "browser_download_url": "https://example.test/FlashTrombi_v0.6.2.exe",
                },
            ]
        }
        self.assertEqual(
            "https://example.test/FlashTrombi_v0.6.2.exe",
            _installer_download_url(payload, "v0.6.2"),
        )

    def test_falls_back_to_an_exe_asset_for_older_releases(self):
        payload = {
            "assets": [
                {
                    "name": "FlashTrombi-Setup.exe",
                    "browser_download_url": "https://example.test/FlashTrombi-Setup.exe",
                }
            ]
        }
        self.assertEqual(
            "https://example.test/FlashTrombi-Setup.exe",
            _installer_download_url(payload, "v0.6.1"),
        )

    def test_version_comparison_is_numeric(self):
        self.assertGreater(_version_tuple("v0.10.0"), _version_tuple("0.9.9"))


if __name__ == "__main__":
    unittest.main()
