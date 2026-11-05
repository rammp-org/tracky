"""The GitHub API client: REST and GraphQL, pagination, compare, sticky comments.

Lifted from the prototype's ``gh()`` / ``gh_paginate()`` / ``compare()`` /
sticky-comment code, without shelling out to ``gh``. The token comes from
``TRACKY_TOKEN``, ``GITHUB_TOKEN`` or ``GH_TOKEN``, else from ``gh auth token``
for local use.

The HTTP layer is one injectable callable (``send``), so tests drive the client
with canned responses and never touch the network.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

from . import config

API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "tracky (https://github.com/rammp-org/tracky)"

#: What ``send`` returns: HTTP status, response headers (case-insensitive keys), body text.
Response = tuple[int, dict[str, str], str]
Send = Callable[[str, str, dict[str, str], bytes | None], Response]


class GitHubError(RuntimeError):
    """An API call that did not succeed. ``status`` is the HTTP status, 0 when no response came."""

    def __init__(self, method: str, url: str, status: int, message: str):
        super().__init__(f"{method} {url}: {status} {message}".rstrip())
        self.method = method
        self.url = url
        self.status = status
        self.message = message


def token(env: dict[str, str] | None = None) -> str | None:
    """The token to use: ``TRACKY_TOKEN``, ``GITHUB_TOKEN``, ``GH_TOKEN``, else ``gh auth token``."""
    env = os.environ if env is None else env
    for name in ("TRACKY_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if env.get(name):
            return env[name]
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def urllib_send(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
    """The real transport: one request, the response or the error response."""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        raise GitHubError(method, url, 0, str(e.reason)) from e


_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


def next_link(link_header: str | None) -> str | None:
    """The ``rel="next"`` URL from a ``Link`` header, or None on the last page."""
    if not link_header:
        return None
    for url, rel in _LINK_RE.findall(link_header):
        if rel == "next":
            return url
    return None


def find_marked(comments: list[dict], marker: str = config.MARKER) -> dict | None:
    """The first comment whose body carries ``marker``."""
    return next((c for c in comments if marker in (c.get("body") or "")), None)


def same_text(a: str | None, b: str | None) -> bool:
    """Whether two comment bodies are the same once GitHub's line-ending and whitespace noise is ignored."""
    norm = lambda s: (s or "").replace("\r\n", "\n").strip()  # noqa: E731
    return norm(a) == norm(b)


class GitHub:
    """A small REST/GraphQL client with the helpers Tracky needs.

    ``dry_run`` makes every write (POST/PATCH/PUT/DELETE) a log line that returns None,
    so a pass can be rehearsed with a read-only token or none at all.
    """

    def __init__(
        self,
        token_: str | None = None,
        *,
        api: str = API,
        send: Send = urllib_send,
        dry_run: bool = False,
        log: Callable[[str], None] | None = None,
    ):
        self.token = token_ if token_ is not None else token()
        self.api = api.rstrip("/")
        self.send = send
        self.dry_run = dry_run
        self.log = log or (lambda s: print(s, file=sys.stderr))
        self._compare: dict[str, str] = {}
        self._default_branch: dict[str, str] = {}
        self.calls = 0

    # ----------------------------------------------------------------- transport

    def _headers(self, body: bool) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if body:
            h["Content-Type"] = "application/json"
        return h

    def url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """``repos/x/y`` or ``/repos/x/y`` or a full URL -> the full URL, with ``params`` as the query."""
        u = path if path.startswith("http") else f"{self.api}/{path.lstrip('/')}"
        if params:
            sep = "&" if "?" in u else "?"
            u += sep + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return u

    def request(
        self,
        method: str,
        path: str,
        body: dict | list | None = None,
        *,
        params: dict[str, Any] | None = None,
        ok404: bool = False,
        raw: bool = False,
    ) -> Any:
        """One call. JSON in, JSON out; None for an empty body or, with ``ok404``, a 404.

        ``raw`` returns ``(status, headers, text)`` instead, for callers that need headers.
        """
        method = method.upper()
        url = self.url(path, params)
        if self.dry_run and method != "GET":
            self.log(f"dry run: {method} {url} {json.dumps(body) if body is not None else ''}".rstrip())
            return None
        data = json.dumps(body).encode() if body is not None else None
        self.calls += 1
        status, headers, text = self.send(method, url, self._headers(data is not None), data)
        if status == 404 and ok404:
            return None
        if status >= 400:
            raise GitHubError(method, url, status, _message(text))
        if raw:
            return status, headers, text
        return json.loads(text) if text.strip() else None

    def get(self, path: str, *, params: dict[str, Any] | None = None, ok404: bool = False) -> Any:
        return self.request("GET", path, params=params, ok404=ok404)

    def post(self, path: str, body: dict | list | None = None, *, ok404: bool = False) -> Any:
        return self.request("POST", path, body, ok404=ok404)

    def patch(self, path: str, body: dict | list | None = None, *, ok404: bool = False) -> Any:
        return self.request("PATCH", path, body, ok404=ok404)

    def put(self, path: str, body: dict | list | None = None, *, ok404: bool = False) -> Any:
        return self.request("PUT", path, body, ok404=ok404)

    def delete(self, path: str, body: dict | list | None = None, *, ok404: bool = False) -> Any:
        return self.request("DELETE", path, body, ok404=ok404)

    def paginate(self, path: str, *, params: dict[str, Any] | None = None, per_page: int = 100) -> Iterator[dict]:
        """Every item of a list endpoint, following the ``Link`` header until there is no next page."""
        params = {"per_page": per_page, **(params or {})}
        url: str | None = self.url(path, params)
        while url:
            status, headers, text = self.request("GET", url, raw=True)
            page = json.loads(text) if text.strip() else []
            if isinstance(page, dict):  # search endpoints wrap the list
                page = page.get("items", [])
            yield from page
            url = next_link(headers.get("link"))

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        """One GraphQL call; raises on errors in the response, returns ``data``."""
        r = self.request("POST", "graphql", {"query": query, "variables": variables or {}})
        if r is None:
            return {}
        if r.get("errors"):
            raise GitHubError("POST", self.url("graphql"), 200, "; ".join(e.get("message", "") for e in r["errors"]))
        return r.get("data") or {}

    # ------------------------------------------------------------------ helpers

    def default_branch(self, repo: str) -> str:
        repo = config.full(repo)
        if repo not in self._default_branch:
            self._default_branch[repo] = self.get(f"repos/{repo}")["default_branch"]
        return self._default_branch[repo]

    def compare(self, repo: str, base: str, head: str) -> str:
        """``identical`` | ``behind`` | ``ahead`` | ``diverged``, or ``unknown`` when a ref is missing. Cached per run."""
        repo = config.full(repo)
        k = f"{repo}:{base}...{head}"
        if k not in self._compare:
            d = self.get(f"repos/{repo}/compare/{base}...{head}", ok404=True)
            self._compare[k] = d["status"] if d else "unknown"
        return self._compare[k]

    def submodule_sha(self, repo: str, path: str, ref: str) -> str | None:
        """The commit a submodule points at in ``repo`` at ``ref``; None if there is no submodule there."""
        d = self.get(f"repos/{config.full(repo)}/contents/{path}", params={"ref": ref}, ok404=True)
        if not d or not isinstance(d, dict) or d.get("type") != "submodule":
            return None
        return d["sha"]

    def pull(self, repo: str, number: int) -> dict | None:
        """A PR as the API gives it, or None if ``number`` is an issue or does not exist."""
        return self.get(f"repos/{config.full(repo)}/pulls/{number}", ok404=True)

    def comments(self, repo: str, number: int) -> list[dict]:
        """All comments on an issue or PR."""
        return list(self.paginate(f"repos/{config.full(repo)}/issues/{number}/comments"))

    def sticky_comment(
        self, repo: str, number: int, text: str, *, marker: str = config.MARKER
    ) -> tuple[str, dict | None]:
        """Keep one comment carrying ``marker`` on an issue or PR equal to ``text``.

        Returns ``("unchanged" | "updated" | "posted", comment)``. The marker is
        prepended if ``text`` lacks it. Edits only when the text differs, so
        nobody is notified for nothing.
        """
        repo = config.full(repo)
        if marker not in text:
            text = f"{marker}\n{text}"
        existing = find_marked(self.comments(repo, number), marker)
        if existing and same_text(existing.get("body"), text):
            return "unchanged", existing
        if existing:
            updated = self.patch(f"repos/{repo}/issues/comments/{existing['id']}", {"body": text})
            return "updated", updated if updated is not None else {**existing, "body": text}
        posted = self.post(f"repos/{repo}/issues/{number}/comments", {"body": text})
        return "posted", posted


def _message(text: str) -> str:
    try:
        d = json.loads(text)
    except ValueError:
        return text.strip()[:200]
    if isinstance(d, dict):
        msg = d.get("message", "")
        errs = d.get("errors")
        if errs:
            msg += " " + json.dumps(errs)
        return msg.strip()
    return text.strip()[:200]
