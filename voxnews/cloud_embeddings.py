"""Cached OpenAI embeddings for the cloud-only demo. No local model runtime."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from time import perf_counter
from urllib.request import Request, urlopen

from . import providers
from .official_releases import digest


class CloudEncoder:
    def __init__(self, cache: Path, *, transport=None):
        self.cache = cache
        self.transport = transport or self.request
        self.name = providers.model("embedding")
        self.usage = {"model": self.name, "provider": "openai", "calls": 0,
                      "input_tokens": 0, "output_tokens": 0, "cache_hits": 0}

    def request(self, texts):
        providers.require_requests()
        key = providers.api_key()
        if not key:
            raise ValueError("Configure OPENAI_API_KEY in .env to prepare the cloud demo.")
        request = Request("https://api.openai.com/v1/embeddings",
            data=json.dumps({"model": self.name, "input": texts, "dimensions": 384,
                             "encoding_format": "float"}).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urlopen(request, timeout=120) as response:
            return json.load(response)

    def __call__(self, articles):
        import numpy as np

        start = perf_counter()
        texts = [(a.headline + "\n" + a.excerpt)[:2000] for a in articles]
        keys = [digest([self.name, 384, text]) for text in texts]
        vectors = [None] * len(texts)
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.cache, timeout=60)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS embedding(key TEXT PRIMARY KEY, vector TEXT NOT NULL)")
            missing = []
            for i, key in enumerate(keys):
                old = db.execute("SELECT vector FROM embedding WHERE key=?", (key,)).fetchone()
                if old:
                    vectors[i] = json.loads(old[0])
                    self.usage["cache_hits"] += 1
                else:
                    missing.append(i)
            for offset in range(0, len(missing), 64):
                batch = missing[offset:offset+64]
                result = self.transport([texts[i] for i in batch])
                self.usage["calls"] += 1
                self.usage["input_tokens"] += result.get("usage", {}).get("prompt_tokens", 0)
                if "prompt_tokens" not in result.get("usage", {}):
                    self.usage["unmetered_calls"] = self.usage.get("unmetered_calls", 0) + 1
                rows = result["data"]
                if (len(rows) != len(batch) or any(type(r.get("index")) is not int for r in rows)
                        or {r["index"] for r in rows} != set(range(len(batch)))):
                    raise ValueError("Cloud embeddings returned invalid indexes")
                checked = []
                for row in rows:
                    i = batch[row["index"]]
                    vector = np.asarray(row["embedding"], dtype=np.float32)
                    if vector.shape != (384,) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                        raise ValueError("Cloud embeddings returned an invalid vector")
                    vectors[i] = (vector / np.linalg.norm(vector)).tolist()
                    checked.append((keys[i], json.dumps(vectors[i])))
                with db:
                    db.executemany("INSERT OR IGNORE INTO embedding VALUES (?,?)", checked)
        self.usage["seconds"] = round(perf_counter()-start, 3)
        return np.asarray(vectors, dtype=np.float32).reshape(len(texts), 384)
