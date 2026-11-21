"""HTTP actions for versioned listener profiles and immutable daily deliveries."""

from contextlib import closing
from http.cookies import SimpleCookie, CookieError
import json
import re
from secrets import token_hex
from threading import Lock
from subprocess import SubprocessError
import sqlite3
from urllib.parse import urlsplit

from build_preai import database_path, NoCoverage
from generate_script import ScriptError
from .editions import dates
from .delivery import compose_day
from .listeners import Conflict, check_in, current, revise, storage, unpack
from .official_releases import digest
from .overview_reader import connect, get_event, log_html
from .verify import write_atomic

AUDIO_LOCK = Lock()


def identity(handler):
    cookie = SimpleCookie()
    header = handler.headers.get("Cookie")
    if isinstance(header, str):
        try:
            cookie.load(header)
        except CookieError:
            pass
    token = cookie["voxlistener"].value if "voxlistener" in cookie else ""
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        token = token_hex(32)
        handler.listener_cookie = f"voxlistener={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
    return digest(token)


def available_dates():
    with closing(connect(database_path())) as db:
        return list(dates(db))


def respond(handler, directory, *, post=False):
    path = urlsplit(handler.path).path
    listener = identity(handler)
    try:
        if path.startswith("/evidence/") and not post:
            _, _, eid, revision = path.split("/")
            with closing(connect(database_path())) as db:
                return handler.reply(200, log_html(get_event(db, eid, revision)), "text/html")
        data = {}
        if post:
            if handler.headers.get_content_type() != "application/json":
                return handler.send_error(415)
            length = int(handler.headers.get("Content-Length", 0))
            if not 0 < length <= 65536:
                return handler.send_error(400)
            data = json.loads(handler.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
        with storage(directory) as db:
            if post and path == "/api/narration":
                from .narration import render

                row = db.execute(
                    "SELECT draft,briefing FROM delivery WHERE listener=? AND edition=?",
                    (listener, data.get("edition")),
                ).fetchone()
                if not row:
                    return handler.send_error(404)
                try:
                    with AUDIO_LOCK:
                        result = render(
                            directory / "listeners" / listener,
                            json.loads(row["draft"]),
                            json.loads(row["briefing"]),
                        )
                except (ValueError, RuntimeError, SubprocessError, OSError) as error:
                    handler.log_error("Narration: %s", error)
                    return handler.reply(
                        503, "Audio generation failed. Your verified transcript is available."
                    )
            elif not post and path.startswith("/api/audio/"):
                match = re.fullmatch(r"/api/audio/([a-f0-9]{64})/([a-f0-9]{64}\.mp3)", path)
                if not match:
                    return handler.send_error(404)
                edition, name = match.groups()
                root = directory / "listeners" / listener
                manifest = root / edition / "audio.json"
                if not manifest.exists() or name not in {
                    s["file"] for s in json.loads(manifest.read_text())["segments"]
                }:
                    return handler.send_error(404)
                body = (root / "audio" / name).read_bytes()
                handler.send_response(200)
                handler.send_header("Content-Type", "audio/mpeg")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
                return
            elif not post and path == "/api/profile":
                history = db.execute(
                    "SELECT * FROM profile WHERE listener=? ORDER BY version DESC", (listener,)
                )
                result = {
                    "profile": current(db, listener),
                    "history": [unpack(r) for r in history],
                    "dates": available_dates(),
                    "delivered": [
                        r[0]
                        for r in db.execute(
                            "SELECT day FROM delivery WHERE listener=? ORDER BY day DESC", (listener,)
                        )
                    ],
                }
            elif post and path == "/api/profile":
                db.execute("BEGIN IMMEDIATE")
                result = revise(db, listener, data, "explicit settings", data.get("version"))
            elif post and path == "/api/briefing":
                day = data.get("date")
                if not isinstance(day, str):
                    raise ValueError("Choose a published briefing date.")
                result = compose_day(directory, listener, day, data.get("version"))
                target = directory / "listeners" / listener / result["edition"]
                write_atomic(target / "script.md", result["script"])
            elif post and path in {"/api/feedback", "/api/feedback/undo"}:
                db.execute("BEGIN IMMEDIATE")
                result = check_in(
                    db, listener, data.get("edition"), data.get("answers"), path.endswith("/undo")
                )
            else:
                return handler.send_error(404)
        handler.reply(200, json.dumps(result), "application/json")
    except Conflict as exc:
        handler.reply(409, str(exc))
    except (NoCoverage, ScriptError) as exc:
        handler.reply(422, str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        handler.reply(400, str(exc))
    except (OSError, sqlite3.Error) as exc:
        handler.log_error("Daily service: %s", exc)
        handler.reply(503, "Daily data is unavailable. Check the server log and retry.")
