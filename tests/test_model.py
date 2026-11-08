import unittest

from tracky import config
from tracky.model import Car, Feature, PullRequest, Repoint, State, branch_name, parse_branch

from .fake import pr_json


class ConfigTest(unittest.TestCase):
    def test_full_short_canon(self):
        self.assertEqual(config.full("rammp-rtps"), "rammp-org/rammp-rtps")
        self.assertEqual(config.full("rammp-org/rammp-rtps"), "rammp-org/rammp-rtps")
        self.assertEqual(config.short("rammp-org/rammp-rtps"), "rammp-rtps")
        self.assertEqual(config.short("rammp-rtps"), "rammp-rtps")
        self.assertEqual(config.canon("rammp-mib-fw"), "rammp-org/RAMMP-mib-fw")
        self.assertEqual(config.canon(" RAMMP-org/rammp-MIB-fw "), "rammp-org/RAMMP-mib-fw")
        self.assertEqual(config.canon("new-repo"), "rammp-org/new-repo")
        self.assertEqual(config.canon("other/thing"), "other/thing")
        live = {**config.KNOWN, "sheppy": "rammp-org/Sheppy"}
        self.assertEqual(config.canon("SHEPPY", live), "rammp-org/Sheppy")
        self.assertEqual(config.canon("rammp-org/sheppy", live), "rammp-org/Sheppy")

    def test_submodule_map(self):
        for repo in ("RAMMP-mib-fw", "pace-hmi-fw"):
            sub = config.SUBMODULES[config.full(repo)]
            self.assertEqual(sub.path, "external/rammp-rtps")
            self.assertEqual(sub.of, "rammp-org/rammp-rtps")
        self.assertNotIn(config.full("rammp-rtps"), config.SUBMODULES)
        self.assertEqual(len(config.COMMON_REPOS), 4)


class BranchTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(branch_name(12, "estop"), "feat/12-estop")
        self.assertEqual(parse_branch("feat/12-estop"), (12, "estop"))
        self.assertEqual(parse_branch("feat/3-arm-driver.v2"), (3, "arm-driver.v2"))

    def test_rejects_others(self):
        for b in ("main", "feat/estop", "feat/12-", "feature/12-estop", "ewang360/drop-estop", "feat/12-estop/x"):
            self.assertIsNone(parse_branch(b), b)


class StateTest(unittest.TestCase):
    def test_ten_in_design_order(self):
        self.assertEqual([s.value for s in State], [
            "scaffolded", "in development", "testing", "ready for review", "waiting",
            "needs repoint", "repointed", "ready to merge", "merged", "closed",
        ])

    def test_lowest_and_order(self):
        self.assertIs(State.lowest([State.MERGED, State.WAITING, State.REPOINTED]), State.WAITING)
        self.assertIsNone(State.lowest([]))
        self.assertLess(State.SCAFFOLDED, State.CLOSED)
        self.assertEqual(sorted([State.CLOSED, State.TESTING]), [State.TESTING, State.CLOSED])

    def test_parse_and_str(self):
        self.assertIs(State.parse("in development"), State.IN_DEVELOPMENT)
        self.assertIs(State.parse("Ready To Merge"), State.READY_TO_MERGE)
        self.assertIs(State.parse("NEEDS_REPOINT"), State.NEEDS_REPOINT)
        self.assertEqual(str(State.WAITING), "waiting")
        with self.assertRaises(ValueError):
            State.parse("not scaffolded")

    def test_repoint(self):
        self.assertIs(Repoint.parse("auto"), Repoint.AUTO)
        self.assertIs(Repoint.parse("On request"), Repoint.ON_REQUEST)
        with self.assertRaises(ValueError):
            Repoint.parse("maybe")


class PullRequestTest(unittest.TestCase):
    def test_open_draft(self):
        pr = PullRequest.from_api(pr_json())
        self.assertEqual((pr.repo, pr.number, pr.state, pr.draft), ("rammp-org/rammp-rtps", 21, "OPEN", True))
        self.assertEqual((pr.base, pr.head_ref), ("main", "feat/20-estop"))
        self.assertTrue(pr.head_sha.startswith("e5eb267"))
        self.assertIsNone(pr.merge_commit)  # only kept once merged
        self.assertIsNone(pr.merged_at)
        self.assertEqual(pr.labels, {"train"})
        self.assertFalse(pr.auto_merge)
        self.assertEqual(pr.key, "rammp-org/rammp-rtps#21")
        self.assertEqual(pr.short, "rammp-rtps#21")
        self.assertTrue(pr.is_open)
        self.assertFalse(pr.merged)

    def test_merged(self):
        pr = PullRequest.from_api(pr_json(state="closed", merged_at="2026-11-03T16:57:27Z", draft=False, body=None))
        self.assertEqual(pr.state, "MERGED")
        self.assertTrue(pr.merged)
        self.assertEqual(pr.merge_commit, "abc1234abc1234abc1234abc1234abc1234abc12")
        self.assertEqual(pr.body, "")

    def test_closed_not_merged(self):
        pr = PullRequest.from_api(pr_json(state="closed"))
        self.assertEqual(pr.state, "CLOSED")
        self.assertIsNone(pr.merge_commit)

    def test_auto_merge_object(self):
        pr = PullRequest.from_api(pr_json(auto_merge={"merge_method": "squash"}))
        self.assertTrue(pr.auto_merge)


class CarAndFeatureTest(unittest.TestCase):
    def test_feature_makes_empty_cars_in_ticked_order(self):
        f = Feature(3, "estop", repos=[config.full("pace-hmi-fw"), config.full("rammp-rtps")])
        self.assertEqual([c.short for c in f.cars], ["pace-hmi-fw", "rammp-rtps"])
        self.assertTrue(all(not c.scaffolded and c.pr is None and c.state is None for c in f.cars))
        self.assertEqual(f.url, "https://github.com/rammp-org/tracky/issues/3")
        self.assertEqual(f.ref, "rammp-org/tracky#3")
        self.assertIs(f.repoint, Repoint.AUTO)
        self.assertIsNone(f.order)
        self.assertIsNone(f.state)
        self.assertFalse(f.all_merged)

    def test_car_lookup_and_urls(self):
        f = Feature(3, "estop", repos=[config.full("RAMMP-mib-fw")])
        car = f.car("RAMMP-mib-fw")
        self.assertIsNotNone(car)
        self.assertIsNone(f.car("rammp-rtps"))
        car.issue, car.branch = 64, branch_name(64, "estop")
        self.assertEqual(car.issue_url, "https://github.com/rammp-org/RAMMP-mib-fw/issues/64")
        self.assertEqual(car.branch_url, "https://github.com/rammp-org/RAMMP-mib-fw/tree/feat/64-estop")
        self.assertTrue(car.scaffolded)
        self.assertEqual(car.submodule, config.SUBMODULES[config.full("RAMMP-mib-fw")])
        self.assertIsNone(Car(config.full("rammp-rtps")).submodule)

    def test_feature_state_is_lowest(self):
        f = Feature(3, "estop", repos=[config.full("rammp-rtps"), config.full("pace-hmi-fw")])
        f.cars[0].state = State.MERGED
        self.assertIsNone(f.state)  # one car not yet derived
        f.cars[1].state = State.NEEDS_REPOINT
        self.assertIs(f.state, State.NEEDS_REPOINT)
        self.assertFalse(f.all_merged)
        f.cars[1].state = State.MERGED
        self.assertTrue(f.all_merged)

    def test_car_with_pr(self):
        pr = PullRequest.from_api(pr_json())
        car = Car(pr.repo, issue=20, branch=pr.head_ref, pr=pr)
        self.assertEqual(car.pr_number, 21)
        self.assertEqual(parse_branch(car.branch), (car.issue, "estop"))


if __name__ == "__main__":
    unittest.main()
