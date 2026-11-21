"""Run the backend regression suite with optional ElevenLabs adapter verification."""

import argparse
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def selected_tests(suite, include_audio):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from selected_tests(test, include_audio)
        elif include_audio or not test.id().endswith(".test_elevenlabs_narration_uses_saved_edition"):
            yield test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-audio", action="store_true", help="Include the mocked ElevenLabs adapter test")
    args = parser.parse_args()
    with patch.dict(os.environ, {"VOXNEWS_PROVIDER": "openai", "VOXNEWS_CLOUD_ONLY": "0", "VOXNEWS_API_REQUESTS_PAUSED": "0"}):
        discovered = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        suite = unittest.TestSuite(selected_tests(discovered, args.include_audio))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
