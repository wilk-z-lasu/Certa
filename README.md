# VoxNews

## Personalized news audio

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the project’s `.env`, then run `python3 generate_news_audio.py` to narrate `user_data/script.md`. The app uses the same renderer in `md_to_speech.py` when it displays a newly generated script. Listener preferences shape the script, and ElevenLabs narrates it with the configured voice.

Listen in the app or open `user_data/news.wav`. The companion `news.manifest.json` records the script hashes, voice and model, request IDs, and measured duration. The renderer reuses the saved WAV when the script, voice, and model match.

## Markdown to speech with ElevenLabs

`md_to_speech.py` converts a Markdown file to an MP3 with ElevenLabs Text to Speech. It uses Python's standard library, so no Python packages are needed.

### Set up

1. Create an ElevenLabs API key and choose a voice in your ElevenLabs account.
2. Copy `.env.example` to `.env` and set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`.
3. Run the converter with Python 3.10 or newer:

```powershell
Copy-Item .env.example .env
# Edit .env and replace the example values.
python .\md_to_speech.py .\briefing.md
```

For a first run, use `examples\speech-sample.md` as the input.

By default this creates `briefing.mp3` and `briefing.manifest.json` beside the input file. The manifest records the input and spoken-text SHA-256 hashes, voice/model settings, generation time, and any request IDs returned by ElevenLabs.

### Options

```powershell
python .\md_to_speech.py .\briefing.md --output .\audio\morning.mp3
python .\md_to_speech.py .\briefing.md --voice-id VOICE_ID --model-id eleven_multilingual_v2
python .\md_to_speech.py .\long-briefing.md --keep-segments
```

The default model is `eleven_multilingual_v2`; override it with `ELEVENLABS_MODEL_ID` or `--model-id`. Markdown headings, lists, emphasis, and links are made readable for speech. Link labels are spoken and raw URLs are omitted. Code and math blocks are skipped. Text is split into chunks of up to 4,500 characters at paragraph or sentence boundaries. For one combined MP3 from a long document, install FFmpeg; otherwise use `--keep-segments` and play the numbered MP3 files in order.

The converter narrates the Markdown text; it does not fact-check or rewrite it. For the briefing pipeline, pass only the final validated script to speech generation, include the required synthetic-voice disclosure in that script, and keep claim-to-source links in the application records. The sidecar manifest fingerprints the input but does not replace claim-level provenance.

Both commands use the [ElevenLabs Text to Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert/).
