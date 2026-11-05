"""A canned transport for ``tracky.github.GitHub``: no network in tests."""

from __future__ import annotations

import json
import urllib.parse


class FakeSend:
    """Answers requests from a table of ``(method, path) -> (status, body[, headers])``.

    ``path`` is the URL path plus query as the client sends it (``/repos/o/r/pulls/1?per_page=100``).
    Every call is recorded in ``calls`` as ``(method, path, body)``. Unknown routes get a 404
    with GitHub's shape of error body.
    """

    def __init__(self, routes: dict[tuple[str, str], tuple] | None = None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str, object]] = []

    def route(self, method: str, path: str, body, status: int = 200, headers: dict | None = None) -> None:
        self.routes[(method, path)] = (status, body, headers or {})

    def __call__(self, method: str, url: str, headers: dict, data: bytes | None):
        u = urllib.parse.urlsplit(url)
        path = u.path + (f"?{u.query}" if u.query else "")
        self.calls.append((method, path, json.loads(data) if data else None))
        entry = self.routes.get((method, path))
        if entry is None:
            return 404, {}, json.dumps({"message": "Not Found"})
        status, body, hdrs = (entry + ({},))[:3]
        text = body if isinstance(body, str) else ("" if body is None else json.dumps(body))
        return status, {k.lower(): v for k, v in hdrs.items()}, text


def pr_json(repo: str = "rammp-org/rammp-rtps", number: int = 21, **over) -> dict:
    """A PR object with the fields ``PullRequest.from_api`` reads, open and draft by default."""
    d = {
        "number": number,
        "title": "Drop EStopBroadcast",
        "state": "open",
        "draft": True,
        "body": "Closes #20\n\nPart of rammp-org/tracky#3",
        "merged_at": None,
        "merge_commit_sha": "abc1234abc1234abc1234abc1234abc1234abc12",
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "labels": [{"name": "train"}],
        "auto_merge": None,
        "base": {"ref": "main", "repo": {"full_name": repo}},
        "head": {"ref": "feat/20-estop", "sha": "e5eb267e3ece0000000000000000000000000000"},
    }
    d.update(over)
    return d
