"""One-time ElevenLabs Voice Design setup. Resume by running again."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from md_to_speech import load_dotenv

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "journalist_voices.json"


def post(endpoint, payload, key):
    req = Request("https://api.elevenlabs.io/v1/text-to-voice" + endpoint,
                  data=json.dumps(payload).encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"ElevenLabs HTTP {error.code}: {error.read(1600).decode(errors='replace')}") from None


def provision():
    load_dotenv(ROOT / ".env")
    key = os.environ["ELEVENLABS_API_KEY"]
    roster = json.loads(CATALOG.read_text(encoding="utf-8"))
    def save():
        temp = CATALOG.with_suffix(".json.tmp")
        temp.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")
        temp.replace(CATALOG)
    for voice in roster:
        if voice.get("voice_id"):
            continue
        print(f"Designing {voice['name']}", flush=True)
        prompt = (f"Professional {voice['gender']} broadcast journalist speaking English with a distinct "
                  f"{voice['accent']} accent. {voice['style']} Clean studio recording, natural newsroom delivery.")
        if not voice.get("preview_id"):
            result = post("/design", {"voice_description": prompt, "model_id": "eleven_multilingual_ttv_v2",
                          "text": "Good morning. Here is what we know so far. Our reporters have been looking at the figures, and one detail stands out."}, key)
            voice["preview_id"] = result["previews"][0]["generated_voice_id"]
            save()
        result = post("", {"voice_name": "Certa Desk - " + voice["name"], "voice_description": prompt,
                           "generated_voice_id": voice["preview_id"]}, key)
        voice["voice_id"] = result["voice_id"]
        del voice["preview_id"]
        save()


if __name__ == "__main__":
    try:
        provision()
    except (OSError, RuntimeError, KeyError) as error:
        raise SystemExit(str(error))
