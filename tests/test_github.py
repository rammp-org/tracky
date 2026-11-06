import json
import unittest

from tracky import config, github
from tracky.github import GitHub, GitHubError, find_marked, next_link, same_text

from .fake import FakeSend, pr_json

R = "rammp-org/rammp-rtps"


def client(send: FakeSend, **kw) -> GitHub:
    kw.setdefault("log", lambda s: None)
    return GitHub("t0ken", send=send, **kw)


class TokenTest(unittest.TestCase):
    def test_env_order(self):
        self.assertEqual(github.token({"GH_TOKEN": "c", "GITHUB_TOKEN": "b", "TRACKY_TOKEN": "a"}), "a")
        self.assertEqual(github.token({"GH_TOKEN": "c", "GITHUB_TOKEN": "b"}), "b")
        self.assertEqual(github.token({"GH_TOKEN": "c", "GITHUB_TOKEN": ""}), "c")


class RequestTest(unittest.TestCase):
    def test_headers_and_url(self):
        seen = {}

        def spy(method, url, headers, data):
            seen.update(url=url, headers=headers, data=data)
            return 200, {}, "{}"

        gh = GitHub("abc", send=spy)
        gh.get("repos/x/y", params={"ref": "main", "none": None})
        self.assertEqual(seen["url"], "https://api.github.com/repos/x/y?ref=main")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer abc")
        self.assertEqual(seen["headers"]["Accept"], "application/vnd.github+json")
        self.assertIn("User-Agent", seen["headers"])
        self.assertIsNone(seen["data"])

    def test_leading_slash_and_full_url(self):
        gh = client(FakeSend())
        self.assertEqual(gh.url("/repos/x"), "https://api.github.com/repos/x")
        self.assertEqual(gh.url("https://api.github.com/repos/x?page=2"), "https://api.github.com/repos/x?page=2")
        self.assertEqual(gh.url("https://api.github.com/repos/x?page=2", {"a": 1}), "https://api.github.com/repos/x?page=2&a=1")

    def test_json_body_round_trip(self):
        send = FakeSend()
        send.route("POST", "/repos/x/y/issues", {"number": 7}, status=201)
        gh = client(send)
        self.assertEqual(gh.post("repos/x/y/issues", {"title": "hi"}), {"number": 7})
        self.assertEqual(send.calls, [("POST", "/repos/x/y/issues", {"title": "hi"})])

    def test_404_as_none_only_when_asked(self):
        gh = client(FakeSend())
        self.assertIsNone(gh.get("repos/x/y/pulls/1", ok404=True))
        with self.assertRaises(GitHubError) as cm:
            gh.get("repos/x/y/pulls/1")
        self.assertEqual(cm.exception.status, 404)
        self.assertIn("Not Found", str(cm.exception))

    def test_error_message_from_body(self):
        send = FakeSend()
        send.route("PATCH", "/repos/x/y/issues/1", {"message": "Validation Failed", "errors": [{"field": "title"}]}, status=422)
        with self.assertRaises(GitHubError) as cm:
            client(send).patch("repos/x/y/issues/1", {"title": ""})
        self.assertEqual(cm.exception.status, 422)
        self.assertIn("Validation Failed", cm.exception.message)
        self.assertIn("title", cm.exception.message)

    def test_empty_body_is_none(self):
        send = FakeSend()
        send.route("DELETE", "/repos/x/y/issues/1/labels/a", None, status=204)
        self.assertIsNone(client(send).delete("repos/x/y/issues/1/labels/a"))

    def test_dry_run_skips_writes_but_reads(self):
        send = FakeSend()
        send.route("GET", "/repos/x/y", {"default_branch": "dev"})
        lines = []
        gh = client(send, dry_run=True, log=lines.append)
        self.assertEqual(gh.default_branch("x/y"), "dev")
        self.assertIsNone(gh.post("repos/x/y/issues", {"title": "t"}))
        self.assertIsNone(gh.delete("repos/x/y/labels/a"))
        self.assertEqual([m for m, _, _ in send.calls], ["GET"])
        self.assertEqual(len(lines), 2)
        self.assertIn("POST", lines[0])


class PaginateTest(unittest.TestCase):
    def test_next_link(self):
        h = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
        self.assertEqual(next_link(h), "https://api.github.com/x?page=2")
        self.assertIsNone(next_link('<https://api.github.com/x?page=1>; rel="prev", <https://api.github.com/x?page=1>; rel="first"'))
        self.assertIsNone(next_link(None))
        self.assertIsNone(next_link(""))

    def test_follows_link_header(self):
        send = FakeSend()
        send.route("GET", "/repos/x/y/pulls?per_page=2&state=open", [{"n": 1}, {"n": 2}],
                   headers={"Link": '<https://api.github.com/repos/x/y/pulls?per_page=2&state=open&page=2>; rel="next"'})
        send.route("GET", "/repos/x/y/pulls?per_page=2&state=open&page=2", [{"n": 3}],
                   headers={"Link": '<https://api.github.com/repos/x/y/pulls?per_page=2&state=open&page=1>; rel="prev"'})
        items = list(client(send).paginate("repos/x/y/pulls", params={"state": "open"}, per_page=2))
        self.assertEqual([i["n"] for i in items], [1, 2, 3])
        self.assertEqual(len(send.calls), 2)

    def test_single_page_and_search_shape(self):
        send = FakeSend()
        send.route("GET", "/search/issues?per_page=100&q=label%3Atrain", {"total_count": 1, "items": [{"n": 1}]})
        self.assertEqual(list(client(send).paginate("search/issues", params={"q": "label:train"})), [{"n": 1}])


class GraphQLTest(unittest.TestCase):
    def test_data_and_errors(self):
        send = FakeSend()
        send.route("POST", "/graphql", {"data": {"viewer": {"login": "tracky"}}})
        gh = client(send)
        self.assertEqual(gh.graphql("query { viewer { login } }"), {"viewer": {"login": "tracky"}})
        self.assertEqual(send.calls[0][2]["query"], "query { viewer { login } }")
        send.route("POST", "/graphql", {"errors": [{"message": "boom"}]})
        with self.assertRaises(GitHubError) as cm:
            gh.graphql("query { x }")
        self.assertIn("boom", str(cm.exception))


class HelpersTest(unittest.TestCase):
    def test_compare_cached_and_unknown(self):
        send = FakeSend()
        send.route("GET", f"/repos/{R}/compare/main...e5eb267", {"status": "behind", "ahead_by": 0})
        gh = client(send)
        self.assertEqual(gh.compare("rammp-rtps", "main", "e5eb267"), "behind")
        self.assertEqual(gh.compare(R, "main", "e5eb267"), "behind")
        self.assertEqual(gh.compare(R, "main", "0000000"), "unknown")
        self.assertEqual(gh.compare(R, "main", "0000000"), "unknown")
        self.assertEqual(len(send.calls), 2)

    def test_default_branch_cached(self):
        send = FakeSend()
        send.route("GET", "/repos/rammp-org/rammp-interfaces-ros2", {"default_branch": "dev"})
        gh = client(send)
        self.assertEqual(gh.default_branch("rammp-interfaces-ros2"), "dev")
        self.assertEqual(gh.default_branch("rammp-org/rammp-interfaces-ros2"), "dev")
        self.assertEqual(len(send.calls), 1)

    def test_org_repos_and_resolve(self):
        send = FakeSend()
        send.route("GET", "/orgs/rammp-org/repos?per_page=100&type=all", [
            {"name": "rammp-rtps", "full_name": "rammp-org/rammp-rtps", "archived": False, "private": False},
            {"name": "Sheppy", "full_name": "rammp-org/Sheppy", "archived": False, "private": True},
            {"name": "old-fw", "full_name": "rammp-org/old-fw", "archived": True, "private": False},
        ])
        gh = client(send)
        self.assertEqual([r["name"] for r in gh.org_repos()], ["rammp-rtps", "Sheppy"])
        self.assertEqual([r["name"] for r in gh.org_repos(archived=True)], ["rammp-rtps", "Sheppy", "old-fw"])
        self.assertEqual(gh.resolve("sheppy"), "rammp-org/Sheppy")
        self.assertEqual(gh.resolve("RAMMP-ORG/old-fw"), "rammp-org/old-fw")
        self.assertEqual(gh.resolve("rammp-mib-fw"), "rammp-org/RAMMP-mib-fw")  # common, not in the fake list
        self.assertEqual(gh.resolve("nope"), "rammp-org/nope")
        self.assertTrue(gh.is_org_repo("rammp-org/SHEPPY"))
        self.assertFalse(gh.is_org_repo("rammp-org/nope"))
        self.assertEqual(len(send.calls), 1)  # one listing serves every call

    def test_submodule_sha(self):
        send = FakeSend()
        send.route("GET", "/repos/rammp-org/pace-hmi-fw/contents/external/rammp-rtps?ref=0349c1f",
                   {"type": "submodule", "sha": "87b78ea000", "submodule_git_url": "https://github.com/rammp-org/rammp-rtps"})
        send.route("GET", "/repos/rammp-org/pace-hmi-fw/contents/README.md?ref=0349c1f", {"type": "file", "sha": "x"})
        gh = client(send)
        self.assertEqual(gh.submodule_sha("pace-hmi-fw", "external/rammp-rtps", "0349c1f"), "87b78ea000")
        self.assertIsNone(gh.submodule_sha("pace-hmi-fw", "README.md", "0349c1f"))
        self.assertIsNone(gh.submodule_sha("pace-hmi-fw", "nope", "0349c1f"))

    def test_pull(self):
        send = FakeSend()
        send.route("GET", f"/repos/{R}/pulls/21", pr_json())
        gh = client(send)
        self.assertEqual(gh.pull("rammp-rtps", 21)["number"], 21)
        self.assertIsNone(gh.pull("rammp-rtps", 22))


class StickyCommentTest(unittest.TestCase):
    TEXT = f"{config.MARKER}\n| step | repo |\n|---|---|\n| 1 | rtps |"

    def setUp(self):
        self.send = FakeSend()
        self.gh = client(self.send)
        self.send.route("POST", f"/repos/{R}/issues/21/comments", {"id": 9, "body": self.TEXT}, status=201)
        self.send.route("PATCH", f"/repos/{R}/issues/comments/5", {"id": 5, "body": self.TEXT})

    def comments(self, *bodies):
        self.send.route("GET", f"/repos/{R}/issues/21/comments?per_page=100",
                        [{"id": i + 1, "body": b} for i, b in enumerate(bodies)])

    def writes(self):
        return [(m, p) for m, p, _ in self.send.calls if m != "GET"]

    def test_find_marked(self):
        cs = [{"id": 1, "body": "hello"}, {"id": 2, "body": None}, {"id": 3, "body": f"x {config.MARKER} y"}]
        self.assertEqual(find_marked(cs)["id"], 3)
        self.assertIsNone(find_marked(cs[:2]))
        self.assertIsNone(find_marked(cs, marker="<!-- other -->"))

    def test_same_text(self):
        self.assertTrue(same_text("a\r\nb\n", "a\nb"))
        self.assertFalse(same_text("a", "b"))
        self.assertTrue(same_text(None, ""))

    def test_posts_when_absent(self):
        self.comments("unrelated", "<!-- pr-train -->\nold bot")
        what, c = self.gh.sticky_comment("rammp-rtps", 21, self.TEXT)
        self.assertEqual(what, "posted")
        self.assertEqual(c["id"], 9)
        self.assertEqual(self.writes(), [("POST", f"/repos/{R}/issues/21/comments")])
        self.assertEqual(self.send.calls[-1][2], {"body": self.TEXT})

    def test_unchanged_when_same(self):
        self.comments("unrelated", self.TEXT.replace("\n", "\r\n") + "\r\n", "another", self.TEXT)
        what, c = self.gh.sticky_comment("rammp-rtps", 21, self.TEXT)
        self.assertEqual(what, "unchanged")
        self.assertEqual(c["id"], 2)
        self.assertEqual(self.writes(), [])

    def test_edits_first_marked_when_different(self):
        self.comments("x", "y", "z", "w", f"{config.MARKER}\nstale", f"{config.MARKER}\nalso stale")
        what, c = self.gh.sticky_comment("rammp-rtps", 21, self.TEXT)
        self.assertEqual(what, "updated")
        self.assertEqual(c["id"], 5)
        self.assertEqual(self.writes(), [("PATCH", f"/repos/{R}/issues/comments/5")])
        self.assertEqual(self.send.calls[-1][2], {"body": self.TEXT})

    def test_marker_is_added(self):
        self.comments()
        what, c = self.gh.sticky_comment("rammp-rtps", 21, "no marker here")
        self.assertEqual(what, "posted")
        self.assertEqual(self.send.calls[-1][2]["body"], f"{config.MARKER}\nno marker here")

    def test_dry_run(self):
        self.comments(f"{config.MARKER}\nstale")
        self.gh.dry_run = True
        what, c = self.gh.sticky_comment("rammp-rtps", 21, self.TEXT)
        self.assertEqual(what, "updated")
        self.assertEqual(c["body"], self.TEXT)
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
