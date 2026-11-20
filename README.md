# VoxNews

## Personalized news audio

Run `python generate_news_audio.py` to narrate `user_data/script.md` using the listener preferences in `user_data/UserInfo.md`. The app also starts narration when it displays a newly generated script. Listen in the app or open `user_data/news.wav`. The companion `news.manifest.json` records the journalist, selection keywords, voice ID, source hashes, and measured duration.

The ten ElevenLabs journalists cover five English accents (American, British, Irish, Indian, and French), with a male and female presenter for each. To request an accent or narrator gender, add a line such as `Accent: Irish` or `Narrator gender: female` to the profile. Selection prioritizes the requested accent, then narrator gender, then topic and style keywords. Ties use catalog order. A listener's own gender does not set the narrator's gender.

Use the ElevenLabs account that owns the IDs in `journalist_voices.json`. Daily narration uses its Text to Speech permission. The one-time `design_journalists.py` command provisions missing IDs with Voice Design and resumes after an interruption. Unchanged narration reuses the saved WAV.

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

The script calls ElevenLabs' synchronous Text to Speech endpoint with MP3 output. See the [ElevenLabs Text to Speech API reference](https://elevenlabs.io/docs/api-reference/text-to-speech/convert/) for current request details.
