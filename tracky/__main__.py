"""``python -m tracky ...``: Tracky's command line.

Commands arrive with their modules (track, scaffold, repoint, ...). For now:
``smoke`` exercises the API client against a real repo with the local login.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, config
from .github import GitHub
from .model import PullRequest


def cmd_smoke(a: argparse.Namespace) -> int:
    gh = GitHub()
    if not gh.token:
        print("no token: set GITHUB_TOKEN or run `gh auth login`", file=sys.stderr)
        return 2
    repo, _, num = a.pr.rpartition("#")
    repo = config.canon(repo)
    d = gh.pull(repo, int(num))
    if d is None:
        print(f"{repo}#{num}: not a pull request")
        return 1
    pr = PullRequest.from_api(d)
    print(f"{pr.short}: {pr.title!r} {pr.state}{' draft' if pr.draft else ''}")
    print(f"  base {pr.base} ({gh.default_branch(repo)} is the default), head {pr.head_ref} @ {pr.head_sha[:7]}")
    if pr.merge_commit:
        print(f"  merged {pr.merged_at} as {pr.merge_commit[:7]}")
    base, head = a.base or pr.base, a.head or pr.head_sha
    print(f"  compare {base}...{head[:12]}: {gh.compare(repo, base, head)}")
    sub = config.SUBMODULES.get(repo)
    if sub:
        sha = gh.submodule_sha(repo, sub.path, pr.head_sha)
        print(f"  submodule {sub.path} at head: {sha[:7] if sha else 'none'}")
    marked = [c for c in gh.comments(repo, pr.number) if config.MARKER in (c.get("body") or "")]
    print(f"  tracky comments: {len(marked)}; API calls: {gh.calls}")
    return 0


def cmd_repos(a: argparse.Namespace) -> int:
    gh = GitHub()
    repos = gh.org_repos(a.org, archived=a.archived)
    common = {config.full(r): i for i, r in enumerate(config.COMMON_REPOS)}
    repos.sort(key=lambda r: (common.get(r["full_name"], len(common)), r["name"].lower()))
    for r in repos:
        flags = " ".join(f for f, on in (("common", r["full_name"] in common), ("private", r.get("private")),
                                         ("archived", r.get("archived"))) if on)
        print(f"{r['name']:<36} {r['default_branch']:<6} {flags}".rstrip())
    print(f"{len(repos)} repos in {a.org}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tracky", description="All aboard the PR train! 🚂💨")
    ap.add_argument("--version", action="version", version=f"tracky {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")
    sp = sub.add_parser("smoke", help="fetch a PR and compare two refs, to check the API client and login")
    sp.add_argument("pr", metavar="repo#N", help="a PR, e.g. rammp-rtps#21")
    sp.add_argument("base", nargs="?", help="compare base (default: the PR's base branch)")
    sp.add_argument("head", nargs="?", help="compare head (default: the PR's head sha)")
    sp.set_defaults(func=cmd_smoke)
    rp = sub.add_parser("repos", help="list the org's repos, the common ones first")
    rp.add_argument("--org", default=config.ORG)
    rp.add_argument("--archived", action="store_true", help="include archived repos")
    rp.set_defaults(func=cmd_repos)
    a = ap.parse_args(argv)
    if not a.command:
        ap.print_help()
        return 0
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
