"""Explicit cloud/local model routing, with a cloud-only demo policy."""

import json
import os
from pathlib import Path
from functools import lru_cache
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

LOCAL = {
    "grouping": "qwen3.5:0.8b-mlx",
    "extraction": "qwen3.5:4b-mlx",
    "review": "qwen3.5:4b-mlx",
    "composition": "qwen3.5:4b-mlx",
}
HOSTED = {
    "embedding": "text-embedding-3-small",
    "grouping": "gpt-6-luna",
    "extraction": "gpt-6-luna",
    "review": "gpt-6.2-astra",
    "composition": "gpt-6.2-astra",
}


def setting(name, default=None):
    if name in os.environ:
        return os.environ[name]
    for filename in (".env", ".env.local"):
        path = Path(__file__).resolve().parents[1] / filename
        if path.is_file():
            for line in path.read_text().splitlines():
                key, separator, value = line.strip().removeprefix("export ").partition("=")
                if separator and key.strip() == name:
                    return value.strip().strip('"\'')
    return default


def cloud_only():
    return setting("VOXNEWS_CLOUD_ONLY", "0").lower() in {"1", "true", "yes"}


def requests_paused():
    return setting("VOXNEWS_API_REQUESTS_PAUSED", "0").lower() in {"1", "true", "yes"}


def require_requests():
    if requests_paused():
        raise ValueError("Paid API requests are paused to preserve credits. Cached cloud results remain available.")


def api_key():
    return setting("OPENAI_API_KEY", "").strip() or None


def local():
    value = setting("VOXNEWS_PROVIDER", "openai")
    if value not in {"openai", "ollama"}:
        raise ValueError("VOXNEWS_PROVIDER must be openai or ollama")
    if cloud_only() and value != "openai":
        raise ValueError("Cloud-only demo requires VOXNEWS_PROVIDER=openai. Local models are disabled.")
    return value == "ollama"


def model(role):
    fallback = (LOCAL if local() else HOSTED)[role]
    if role == "composition" and not local():
        fallback = setting("OPENAI_MODEL") or fallback
    name = setting("VOXNEWS_" + role.upper() + "_MODEL") or fallback
    if cloud_only() and (name in LOCAL.values() or name.endswith("-mlx")):
        raise ValueError(f"Cloud-only demo cannot use the local {role} model {name!r}.")
    return name


def cloud_event(event):
    processing = event.get("processing", {})
    versions = event.get("model_versions", {})
    return (processing.get("provider") == "openai" and processing.get("embedding_provider") == "openai"
            and processing.get("grouping_provider") == "openai" and event.get("model_status") == "reviewed"
            and all(versions.get(stage, {}).get("provider") == "openai"
                    for stage in ("extract", "review", "event_review", "overview", "translation")))


class LocalOnly(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError("Unexpected redirect from local model server")


@lru_cache(maxsize=16)
def revision(name):
    if not local():
        return name
    with build_opener(ProxyHandler({}), LocalOnly()).open(
        "http://127.0.0.1:11434/api/tags", timeout=10
    ) as response:
        installed = json.load(response)["models"]
    for entry in installed:
        if entry["name"] == name:
            return entry["digest"] + "/schema-fallback-3"
    raise ValueError(f"Local model {name!r} is not installed")


def local_request(payload):
    if cloud_only():
        raise ValueError("Local inference is disabled in the cloud-only demo.")
    schema = payload.get("text", {}).get("format", {}).get("schema")
    body = {
        "model": payload["model"],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {
            "temperature": 0,
            "seed": 7,
            "num_ctx": 16384,
            "num_predict": payload["max_output_tokens"],
        },
        "messages": [
            {"role": "system", "content": payload["instructions"]},
            {"role": "user", "content": payload["input"]},
        ],
    }
    if schema is None:
        del body["format"]
    req = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    client = build_opener(ProxyHandler({}), LocalOnly())
    try:
        response = client.open(req, timeout=240)
    except HTTPError as exc:
        if exc.code != 501 or schema is None:
            raise
        exc.close()
        # MLX runners may lack constrained decoding. The stage still validates every field.
        del body["format"]
        body["messages"][0]["content"] = (
            "Output a data instance of this JSON schema:\n"
            + json.dumps(schema)
            + "\nNever echo the schema or its keywords. "
            + payload["instructions"]
        )
        examples = {
            "briefing_selection": {"claim_ids": ["c1"]},
            "extract_claims": {
                "claims": [
                    {
                        "kind": "reported_fact",
                        "wording": "A short factual paraphrase.",
                        "refs": [0],
                        "geo": "",
                        "measure": "",
                        "period": "",
                        "basis": "",
                        "value": "",
                    }
                ]
            },
            "review_claims": {
                "decision": "unsupported",
                "support": [],
                "contradict": [],
                "reason": "missing_evidence",
            },
            "overview_claims": {
                "items": [{"claim_id": "c1", "independent_firsthand_sources": [], "nl": "", "de": ""}]
            },
            "event_review_claims": {"issues": []},
        }
        example = examples.get(payload["text"]["format"]["name"])
        if example:
            body["messages"][0]["content"] += (
                "\nExample format only: " + json.dumps(example) + ". Fill values from the input evidence."
            )
        req.data = json.dumps(body).encode()
        response = client.open(req, timeout=240)
    with response:
        result = json.load(response)
    content = result["message"]["content"].strip()
    if content.startswith("```json") and content.endswith("```"):
        content = content[7:-3].strip()
    return {
        "status": "completed"
        if result.get("done") and result.get("done_reason") != "length"
        else "incomplete",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}],
        "usage": {
            "input_tokens": result.get("prompt_eval_count", 0),
            "output_tokens": result.get("eval_count", 0),
        },
    }
