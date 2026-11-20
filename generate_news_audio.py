"""Narrate user_data/script.md with the ElevenLabs voice configured in .env."""

import argparse
from pathlib import Path

from md_to_speech import generate_news_audio


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-data", type=Path, default=Path(__file__).resolve().parent / "user_data")
    try:
        print(generate_news_audio(parser.parse_args().user_data))
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
