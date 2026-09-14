import unittest
from unittest.mock import patch

from blrec.cli.main import main
from scripts.release_version import release_version


class ReleaseTests(unittest.TestCase):
    def test_version_tag(self):
        version = release_version()
        self.assertEqual(release_version('v' + version), version)
        with self.assertRaises(ValueError):
            release_version('v0.0.0')

    def test_cli_exit_status(self):
        for code, expected in ((0, 0), (2, 2), (None, 0), ('error', 1)):
            with self.subTest(code=code):
                with patch('blrec.cli.main.cli', side_effect=SystemExit(code)):
                    self.assertEqual(main(), expected)
