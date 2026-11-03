"""A tiny stand-in for Supabase's auth + REST APIs, for tests."""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeSupabase:
    def __init__(self, email="me@example.com", password="pw", anon_key="anon"):
        self.email, self.password, self.anon_key = email, password, anon_key
        self.user_id = str(uuid.uuid4())
        self.tables: dict[str, dict[tuple, dict]] = {}
        self.tokens: dict[str, str] = {}  # access token -> user id
        self.refresh: set[str] = set()
        self.requests = 0
        self.down = False
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None):
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Access-Control-Allow-Origin", "*")  # the hub runs in a browser
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_OPTIONS(self):  # browser preflight
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
                self.end_headers()

            def do_GET(self):
                """Just enough PostgREST for the hub: select, eq filters, order, offset/limit."""
                fake.requests += 1
                u = urlparse(self.path)
                user = fake.tokens.get((self.headers.get("Authorization") or "")[7:])
                if not u.path.startswith("/rest/v1/") or not user:
                    return self._send(401, {"message": "JWT expired"})
                q = parse_qs(u.query)
                rows = [r for r in fake.rows(u.path.rsplit("/", 1)[1]) if r["user_id"] == user]
                for k, (v,) in q.items():
                    if k in ("select", "order", "offset", "limit") or not v.startswith("eq."):
                        continue
                    rows = [r for r in rows if str(r.get(k)).lower() == v[3:].lower()]
                if "order" in q:
                    col, _, direction = q["order"][0].partition(".")
                    rows.sort(key=lambda r: r.get(col), reverse=direction.startswith("desc"))
                off = int(q.get("offset", ["0"])[0])
                rows = rows[off: off + int(q["limit"][0])] if "limit" in q else rows[off:]
                if "select" in q and q["select"][0] != "*":
                    cols = q["select"][0].split(",")
                    rows = [{c: r.get(c) for c in cols} for r in rows]
                if "vnd.pgrst.object" in (self.headers.get("Accept") or ""):
                    if len(rows) != 1:
                        return self._send(406, {"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})
                    return self._send(200, rows[0])
                return self._send(200, rows)

            def do_POST(self):
                fake.requests += 1
                if fake.down:
                    return self._send(503, {"message": "down"})
                if self.headers.get("apikey") != fake.anon_key:
                    return self._send(401, {"message": "No API key"})
                u = urlparse(self.path)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
                if u.path == "/auth/v1/token":
                    grant = parse_qs(u.query)["grant_type"][0]
                    ok = (grant == "password" and body.get("email") == fake.email and body.get("password") == fake.password) or (
                        grant == "refresh_token" and body.get("refresh_token") in fake.refresh)
                    if not ok:
                        return self._send(400, {"error_description": "Invalid login credentials"})
                    if grant == "refresh_token":
                        fake.refresh.discard(body["refresh_token"])  # tokens rotate
                    at, rt = uuid.uuid4().hex, uuid.uuid4().hex
                    fake.tokens[at] = fake.user_id
                    fake.refresh.add(rt)
                    return self._send(200, {"access_token": at, "token_type": "bearer", "refresh_token": rt,
                                            "expires_in": 3600, "expires_at": int(time.time()) + 3600,
                                            "user": {"id": fake.user_id, "aud": "authenticated", "role": "authenticated",
                                                     "email": fake.email}})
                if u.path.startswith("/rest/v1/"):
                    user = fake.tokens.get((self.headers.get("Authorization") or "")[7:])
                    if not user:
                        return self._send(401, {"message": "JWT expired"})
                    table = u.path.rsplit("/", 1)[1]
                    keys = parse_qs(u.query)["on_conflict"][0].split(",")
                    rows = fake.tables.setdefault(table, {})
                    for r in body:
                        if r.get("user_id") not in (None, user):  # row-level security
                            return self._send(403, {"message": "new row violates row-level security policy"})
                        r = {**r, "user_id": user}
                        k = tuple(r[k] for k in keys)
                        r["id"] = rows[k]["id"] if k in rows else len(rows) + 1  # like an identity column
                        rows[k] = r
                    return self._send(201)
                return self._send(404, {"message": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def rows(self, table):
        return list(self.tables.get(table, {}).values())

    def close(self):
        self.server.shutdown()
