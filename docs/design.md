# Tracky: design

2026-11-05. Tracky is the bot that runs a feature's PRs across the RAMMP repos as one train.
This is what it is made of and why. The README says what it does for a user.

## The lifecycle

1. **Declare.** A name (`estop`), the repos the feature touches, a line per repo on what is
   needed there, and the repoint switch. Declared on the Tracky page, which opens a prefilled
   issue in the Tracky repo. That issue is the feature's record for its whole life.
2. **Scaffold.** Tracky creates in each member repo: an issue (the per-repo note, a link back
   to the feature issue), a branch `feat/{issue}-{name}` off the default branch, and a draft PR
   from the repo's PR template with `Closes #{issue}` and `Part of rammp-org/tracky#{feature}`.
   In repos that vendor another member repo as a submodule, the branch's pointer is set to the
   upstream feature branch, so the feature builds as a whole from the start.
3. **Develop.** People push to the branches. Tracky reads, never writes, the PR bodies.
4. **Test.** Each firmware is built from its branch, with the submodule on the upstream branch.
   Nothing here is Tracky's; it only shows that the pointers are on the branches.
5. **Merge in order.** The first step's PRs are approved and merge. Tracky repoints the next
   step's branches to the upstream merge commits, CI runs, and Tracky enables auto-merge. The
   next step is approved and merges on its own, and so on to the last car.
6. **Done.** All PRs merged; the per-repo issues closed by `Closes`; the feature issue closed
   by Tracky with the final table.

## The record: one issue per feature

The feature issue in the Tracky repo is the source of truth. It is opened through an issue form
(`.github/ISSUE_TEMPLATE/train.yml`) with fields: name, repos (checkboxes), note per repo,
repoint (auto / on request), order (optional, overrides the suggestion). The form applies the
label `train`; that label is what makes an issue a feature to Tracky.

Tracky's own development happens in the same repo, so its issues share the list. A second
template, `tracky.yml`, labels those `tracky`, and `config.yml` turns blank issues off so every
issue arrives through one of the two. Every workflow filters on `train`: `scaffold` runs on
`issues: [labeled]` only when the label is `train`; `track` lists issues by `label:train`;
`commands` answers `/tracky` on anything else with "not a train" and does nothing. Removing the
`train` label from an issue is how a declared feature is withdrawn without deleting its history.

Tracky keeps a block in the feature issue's body current:

```
<!-- tracky -->
| step | repo | issue | branch | PR | state |
...
repoint: auto · order: suggested (rtps, interfaces-ros2 · mib, hmi)
```

Why an issue and not a YAML file in the repo: anyone in the org can open and edit an issue from
a browser, it carries its own history and comments, and `/tracky` commands land on it naturally.
A file would be the choice if the record needed review before it took effect; it does not.

The dashboard is built from these issues plus live PR state, into `site/data.json`, by the same
workflow that tracks.

## Order: suggested, then chosen

A fixed tier (rtps, ros2, mib, hmi) is right today and wrong tomorrow. Tracky suggests an order
from evidence it can read from the repos, and the person decides.

Evidence, in the order checked:

1. **Submodule.** `.gitmodules` in repo A names a URL that is member repo B. If the feature's
   PR in A moves that pointer, B goes before A. (mib and hmi vendor rtps at
   `external/rammp-rtps`.)
2. **ROS 2 package dependency.** A `package.xml` in repo A lists a package that lives in member
   repo B. B goes before A. (The arm driver or anything ROS-facing after interfaces-ros2.)
3. **Stated.** `Follows owner/repo#N` in a PR body, or `/tracky order …`, or the order field on
   the feature issue. A stated order wins. If it contradicts rule 1 or 2 Tracky says so on the
   feature issue, once, and follows the stated order anyway.
4. **Otherwise** the repos are the same step, listed in the order they were ticked.

A step is a set of PRs that can merge in any order among themselves. The next step's repoint
happens when every PR it depends on has merged, not when the whole previous step has.

## Per-PR state

Derived on every pass from the GitHub API; nothing is stored.

| state           | meaning and how it is read                                                      |
|-----------------|---------------------------------------------------------------------------------|
| scaffolded      | draft PR exists, no commits beyond the scaffold                                 |
| in development  | commits on the branch; still draft                                              |
| testing         | submodule pointer is on the upstream *branch* (not reachable from its default)   |
| ready for review| PR un-drafted by a person                                                       |
| waiting         | un-drafted, but an upstream PR is not merged yet                                |
| needs repoint   | upstream merged; pointer does not contain the upstream merge commit             |
| repointed       | pointer contains the upstream merge commit and is on its default branch; CI running |
| ready to merge  | repointed, CI green, auto-merge on; waiting for approval                        |
| merged          |                                                                                 |
| closed          | closed without merging; the train stops here until a person says what to do     |

Pointer checks use the compare API: `main...SHA` with status `behind`/`identical` means the
pointer is on main; `MERGE...SHA` with `ahead`/`identical` means it includes the merge.

The feature's state is the lowest state of its PRs, plus "all merged".

## Repoint

When PR U (upstream) merges with merge commit M, for each downstream PR D whose repo vendors U's
repo: Tracky pushes one commit to D's branch moving the pointer to M, with the message
`Point {submodule} at {repo} {default} ({M short}): {U short} merged`. If D's branch has moved
the pointer by hand since, Tracky still sets it to M (M is on the default branch; the hand-set
one was a branch head). Then it enables auto-merge on D (`gh pr merge --auto`), which fires
when branch protection is satisfied: required review and CI.

The repoint switch on the feature issue decides *when*: `auto` is on merge, within a minute of
the event; `on request` waits for `/tracky repoint` and meanwhile comments on D that it is
needed. The switch exists because an automatic repoint starts a CI run and a review request on
a branch that may still be mid-development.

Tracky does not merge, approve, request changes, or dismiss reviews. Branch protection on every
member repo should require one review and the CI check, or auto-merge means nothing.

## Dependabot

Only pace-hmi-fw has a Dependabot config today (`gitsubmodule`, daily), and as of 2026-11-05 it
has never opened a PR there, so version updates may not be enabled in the repo settings.
Dependabot's job is default branch to default branch: when rtps main moves, bump hmi main.
Tracky's job is a feature branch to the commit it needs. They do not overlap except for the hour
after an rtps feature PR merges, when both want the same bump. Either order works: if the
Dependabot PR merges first the feature PR's pointer change is a no-op; if the feature PR merges
first Dependabot closes its own. Tracky comments on the Dependabot PR that a feature PR carries
the bump, and does nothing else to it. Dependabot's daily cadence never gates the train, because
Tracky pushes the pointer itself.

## Components

```
tracky/                    Python 3.11+, stdlib + GitHub REST/GraphQL via a GitHub App token
  model.py                 Feature, Car (one repo's issue/branch/PR), states
  github.py                API client, pagination, compare, sticky comments
  order.py                 evidence rules and the suggested order
  scaffold.py              issues, branches, pointers, draft PRs
  track.py                 one pass: read everything, compute states, write comments and data.json
  repoint.py               the pointer commit and auto-merge
  commands.py              /tracky … on issues and PRs
.github/ISSUE_TEMPLATE/
  train.yml                the declare form; label train
  tracky.yml               bug, idea or task for Tracky itself; label tracky
  config.yml               blank_issues_enabled: false
.github/workflows/
  scaffold.yml             on: issues [labeled] if label == train
  track.yml                on: schedule */15, workflow_dispatch, repository_dispatch [pr-event]
  commands.yml             on: issue_comment [created] matching ^/tracky
  pages.yml                on: push to site/ and after track; deploys site/
site/
  index.html               dashboard: features, trains, states, links; reads data.json
  declare.html             the form; Submit opens the prefilled issue form
  data.json                written by track
```

Member repos each get `.github/workflows/tracky.yml`, about ten lines: on
`pull_request [opened, edited, closed, ready_for_review, synchronize]` send a
`repository_dispatch` to the Tracky repo so a merge is seen within a minute rather than at the
next quarter hour. Optional; the schedule covers it without.

## The page

GitHub Pages from the Tracky repo, at `rammp-org.github.io/tracky`. Static. The dashboard reads
`data.json`. The declare form has no credentials: Submit builds a URL to
`github.com/rammp-org/tracky/issues/new?template=feature.yml&…` with the form's answers as the
template's field values, and the person confirms on GitHub, logged in as themselves. That gives
anyone in the org a declare button, keeps the feature issue as the audit trail, and puts no
secret in a public page.

## Auth

A GitHub App owned by rammp-org, installed on the member repos, with: contents write (branches,
pointer commits), issues write, pull requests write, metadata read, checks read. Workflows mint a
short-lived token from the App's private key (`actions/create-github-app-token`). Comments and
commits then appear as `tracky[bot]`, not as a person's PAT. Creating the App is the one step
that needs an org owner.

Until the App exists, a fine-grained PAT on the same repos with the same permissions works for
trying it out, stored as a repo secret.

## Conventions enforced

- Branch `feat/{issue}-{name}` where `{issue}` is that repo's issue and `{name}` is the feature
  slug. Tracky creates them this way. A train scaffolded by hand is recognised if it follows this.
- Base is the repo's default branch, read from the API: `main` for the firmware repos, `dev` for
  rammp-interfaces-ros2. For interfaces-ros2 "merged" means into `dev`; the `dev → main` release
  is shown on the feature as a note, not tracked as a car.
- PR bodies keep `Closes #{issue}`; Tracky warns in its comment if the line goes missing.

## Out of scope, on purpose

- Merging and approving.
- Rewriting PR descriptions after scaffolding.
- Bumping default branches for their own sake (Dependabot's, or a later Tracky option).
- Releases of rammp-interfaces-ros2.

## Order of work

1. **Record and track, read-only.** Issue form, `track` producing the feature issue's table and
   `data.json`, the dashboard page. No writes to member repos. The existing prototype at
   `~/HERL/pr-train/pr_train.py` has the API plumbing, the compare checks and the sticky comment;
   its linking moves from description lines to the feature issue.
2. **Scaffold.** Issues, branches, pointers, draft PRs. The first feature tried end to end.
3. **Repoint and auto-merge**, with the switch. Branch protection on the member repos.
4. **Declare form** on the page, `/tracky` commands, the GitHub App, the dispatch workflow in
   the member repos.
