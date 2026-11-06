"""Static facts about the org and its repos.

Any repo in the org can be on a train; nothing in Tracky is limited to a
fixed list. ``COMMON_REPOS`` is the handful most trains touch: the declare
page shows them first, and they are the test fixtures. The live list comes
from ``GitHub.org_repos``.

The order module reads ``.gitmodules`` live; the submodule map here is the
fallback and the test fixture. Repos are referred to by full name
(``owner/name``) everywhere in Tracky; :func:`full` and :func:`short`
convert.
"""

from __future__ import annotations

from dataclasses import dataclass

ORG = "rammp-org"
TRACKY_REPO = f"{ORG}/tracky"

#: The repos most trains touch, suggested first on the declare page. Not a limit.
COMMON_REPOS: tuple[str, ...] = (
    "rammp-rtps",
    "rammp-interfaces-ros2",
    "RAMMP-mib-fw",
    "pace-hmi-fw",
)

#: Label on a feature issue; the only thing that makes an issue a feature.
LABEL_TRAIN = "train"
#: Label on Tracky's own issues.
LABEL_TRACKY = "tracky"

#: Marks the block Tracky keeps in a feature issue body and its sticky comments.
MARKER = "<!-- tracky -->"
MARKER_END = "<!-- /tracky -->"


@dataclass(frozen=True)
class Submodule:
    """A member repo vendored inside another member repo."""

    path: str  #: path of the submodule in the vendoring repo
    of: str  #: full name of the vendored repo


def full(repo: str) -> str:
    """``rammp-rtps`` -> ``rammp-org/rammp-rtps``; a full name passes through."""
    return repo if "/" in repo else f"{ORG}/{repo}"


def short(repo: str) -> str:
    """``rammp-org/rammp-rtps`` -> ``rammp-rtps``; a short name passes through."""
    return repo.rsplit("/", 1)[-1]


#: Vendoring repo (full name) -> the submodule it carries, as known today (the fixture).
SUBMODULES: dict[str, Submodule] = {
    full("RAMMP-mib-fw"): Submodule("external/rammp-rtps", full("rammp-rtps")),
    full("pace-hmi-fw"): Submodule("external/rammp-rtps", full("rammp-rtps")),
}

#: Lower-cased common repo name -> its full name, for offline canonicalisation.
KNOWN: dict[str, str] = {name.lower(): full(name) for name in COMMON_REPOS}


def canon(name: str, known: dict[str, str] | None = None) -> str:
    """Resolve a repo name a person typed (any case, with or without org) to its full name.

    ``known`` maps lower-cased names to full names; the default covers only the
    common repos, so an unknown name comes back as ``ORG/name`` in the case typed.
    ``GitHub.resolve`` does the same against the org's live repo list.
    """
    known = KNOWN if known is None else known
    name = name.strip()
    if "/" in name:
        owner, rest = name.split("/", 1)
        return known.get(rest.lower(), f"{owner}/{rest}")
    return known.get(name.lower(), full(name))
