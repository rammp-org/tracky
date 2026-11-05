"""Static facts about the org and its member repos.

The order module reads ``.gitmodules`` live; the submodule map here is the
fallback and the test fixture. Repos are referred to by full name
(``owner/name``) everywhere in Tracky; :func:`full` and :func:`short`
convert.
"""

from __future__ import annotations

from dataclasses import dataclass

ORG = "rammp-org"
TRACKY_REPO = f"{ORG}/tracky"

#: Member repos, in the order the declare form lists them.
REPOS: tuple[str, ...] = (
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


#: Vendoring repo (full name) -> the submodule it carries.
SUBMODULES: dict[str, Submodule] = {
    full("RAMMP-mib-fw"): Submodule("external/rammp-rtps", full("rammp-rtps")),
    full("pace-hmi-fw"): Submodule("external/rammp-rtps", full("rammp-rtps")),
}

#: A repo name as it may be typed by a person -> its full name. Case-insensitive.
KNOWN: dict[str, str] = {name.lower(): full(name) for name in REPOS}


def canon(name: str) -> str:
    """Resolve a repo name a person typed (any case, with or without org) to its full name.

    Unknown names are returned as ``ORG/name`` so a new member repo still works.
    """
    name = name.strip()
    if "/" in name:
        owner, rest = name.split("/", 1)
        return KNOWN.get(rest.lower(), f"{owner}/{rest}")
    return KNOWN.get(name.lower(), full(name))
