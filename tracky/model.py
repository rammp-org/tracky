"""Tracky's data: a Feature, its Cars, and the per-PR State.

Pure data and pure functions. Nothing here touches the network; the API
client in :mod:`tracky.github` fills these in, and later modules (order,
state, track) compute over them.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

from . import config

BRANCH_RE = re.compile(r"^feat/(?P<issue>\d+)-(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)$")


def branch_name(issue: int, name: str) -> str:
    """The branch convention: ``feat/{issue}-{name}``."""
    return f"feat/{issue}-{name}"


def parse_branch(branch: str) -> tuple[int, str] | None:
    """``feat/12-estop`` -> ``(12, "estop")``; None if the branch is not ours."""
    m = BRANCH_RE.match(branch)
    if not m:
        return None
    return int(m.group("issue")), m.group("name")


class State(enum.Enum):
    """The ten per-PR states from the design, in order from earliest to final.

    The value is the word shown in tables. ``State.lowest`` picks the earliest
    of several, which is how a feature's state is read from its cars.
    """

    SCAFFOLDED = "scaffolded"
    IN_DEVELOPMENT = "in development"
    TESTING = "testing"
    READY_FOR_REVIEW = "ready for review"
    WAITING = "waiting"
    NEEDS_REPOINT = "needs repoint"
    REPOINTED = "repointed"
    READY_TO_MERGE = "ready to merge"
    MERGED = "merged"
    CLOSED = "closed"

    @property
    def rank(self) -> int:
        return list(State).index(self)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, State):
            return NotImplemented
        return self.rank < other.rank

    @classmethod
    def lowest(cls, states: "list[State] | tuple[State, ...]") -> "State | None":
        """The earliest state in the list; None for an empty list."""
        return min(states, key=lambda s: s.rank, default=None)

    @classmethod
    def parse(cls, word: str) -> "State":
        """From the table word (``"in development"``) or the member name."""
        word = word.strip()
        for s in cls:
            if s.value == word.lower() or s.name == word.upper().replace(" ", "_"):
                return s
        raise ValueError(f"not a state: {word!r}")

    def __str__(self) -> str:
        return self.value


class Repoint(enum.Enum):
    """The per-feature switch: repoint downstream branches on merge, or on ``/tracky repoint``."""

    AUTO = "auto"
    ON_REQUEST = "on request"

    @classmethod
    def parse(cls, word: str) -> "Repoint":
        w = word.strip().lower().replace("-", " ").replace("_", " ")
        if w in ("auto", "automatic", "automatically", "on merge"):
            return cls.AUTO
        if w in ("on request", "request", "manual", "ask"):
            return cls.ON_REQUEST
        raise ValueError(f"not a repoint setting: {word!r}")

    def __str__(self) -> str:
        return self.value


@dataclass
class PullRequest:
    """A pull request as the REST API describes it; the fields the prototype's ``PR`` carried."""

    repo: str  #: full name, ``owner/name``
    number: int
    title: str
    state: str  #: ``OPEN`` | ``MERGED`` | ``CLOSED``
    draft: bool
    body: str
    base: str  #: base branch name
    head_ref: str  #: head branch name
    head_sha: str
    merge_commit: str | None  #: set only when merged
    labels: set[str]
    url: str
    merged_at: str | None
    auto_merge: bool = False

    @classmethod
    def from_api(cls, d: dict) -> "PullRequest":
        """Build from a ``GET /repos/{repo}/pulls/{n}`` (or list) response."""
        state = "MERGED" if d.get("merged_at") else ("OPEN" if d["state"] == "open" else "CLOSED")
        return cls(
            repo=d["base"]["repo"]["full_name"],
            number=d["number"],
            title=d["title"],
            state=state,
            draft=bool(d.get("draft")),
            body=d.get("body") or "",
            base=d["base"]["ref"],
            head_ref=d["head"]["ref"],
            head_sha=d["head"]["sha"],
            merge_commit=d.get("merge_commit_sha") if state == "MERGED" else None,
            labels={lb["name"] for lb in d.get("labels", [])},
            url=d["html_url"],
            merged_at=d.get("merged_at"),
            auto_merge=bool(d.get("auto_merge")),
        )

    @property
    def key(self) -> str:
        """``owner/name#N``: unique across repos."""
        return f"{self.repo}#{self.number}"

    @property
    def short(self) -> str:
        """``name#N``: how a PR is named in tables."""
        return f"{config.short(self.repo)}#{self.number}"

    @property
    def is_open(self) -> bool:
        return self.state == "OPEN"

    @property
    def merged(self) -> bool:
        return self.state == "MERGED"


@dataclass
class Car:
    """One repo's part of a feature: its issue, branch and PR there.

    A car with no issue, branch or PR is one scaffold has not reached yet.
    ``state`` and ``reason`` are derived on every pass by the state module; they start empty.
    """

    repo: str  #: full name, ``owner/name``
    issue: int | None = None
    branch: str | None = None
    pr: PullRequest | None = None
    state: State | None = None
    reason: str = ""

    @property
    def short(self) -> str:
        return config.short(self.repo)

    @property
    def pr_number(self) -> int | None:
        return self.pr.number if self.pr else None

    @property
    def issue_url(self) -> str | None:
        return f"https://github.com/{self.repo}/issues/{self.issue}" if self.issue else None

    @property
    def branch_url(self) -> str | None:
        return f"https://github.com/{self.repo}/tree/{self.branch}" if self.branch else None

    @property
    def submodule(self) -> config.Submodule | None:
        """The member repo this car's repo vendors, if any (static map; the order module reads it live)."""
        return config.SUBMODULES.get(self.repo)

    @property
    def scaffolded(self) -> bool:
        return self.branch is not None

    def __hash__(self) -> int:
        return hash(self.repo)


@dataclass
class Feature:
    """A feature as declared on its Tracky issue, plus the cars found for it."""

    number: int  #: the feature issue in the Tracky repo
    name: str  #: slug, as in ``feat/{issue}-{name}``
    repos: list[str] = field(default_factory=list)  #: full names, in ticked order
    notes: dict[str, str] = field(default_factory=dict)  #: full name -> what is needed there
    repoint: Repoint = Repoint.AUTO
    order: list[list[str]] | None = None  #: stated order as steps of full names; None = suggested
    cars: list[Car] = field(default_factory=list)
    title: str = ""
    open: bool = True

    def __post_init__(self) -> None:
        if not self.cars:
            self.cars = [Car(repo) for repo in self.repos]

    @property
    def url(self) -> str:
        return f"https://github.com/{config.TRACKY_REPO}/issues/{self.number}"

    @property
    def ref(self) -> str:
        """``rammp-org/tracky#N``, as written in PR bodies."""
        return f"{config.TRACKY_REPO}#{self.number}"

    def car(self, repo: str) -> Car | None:
        repo = config.full(repo)
        return next((c for c in self.cars if c.repo == repo), None)

    @property
    def state(self) -> State | None:
        """The lowest state of the cars; None until states are derived."""
        states = [c.state for c in self.cars if c.state is not None]
        return State.lowest(states) if len(states) == len(self.cars) and states else None

    @property
    def all_merged(self) -> bool:
        return bool(self.cars) and all(c.state is State.MERGED for c in self.cars)
