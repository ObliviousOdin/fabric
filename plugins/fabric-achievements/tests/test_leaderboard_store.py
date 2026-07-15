"""Unit tests for the leaderboard relay store (pure logic, no sockets).

Loads ``relay/store.py`` by path so the suite runs the same way the engine
tests do, without depending on ``plugins`` being importable as a package.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parents[1] / "relay" / "store.py"
spec = importlib.util.spec_from_file_location("lb_store", STORE_PATH)
store_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store_mod)

LeaderboardStore = store_mod.LeaderboardStore
AuthError = store_mod.AuthError
ValidationError = store_mod.ValidationError
TeamNotFoundError = store_mod.TeamNotFoundError


class TeamLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = LeaderboardStore()

    def _create(self):
        return self.store.create_team(name="Crew", display_name="Owner")

    def test_create_returns_secrets_once_and_hashes_at_rest(self):
        created = self._create()
        self.assertTrue(created["team_id"].startswith("tm_"))
        self.assertTrue(created["member_id"].startswith("mb_"))
        self.assertEqual(created["role"], "owner")
        team = self.store._teams[created["team_id"]]
        # Raw secrets must not be stored anywhere.
        blob = json.dumps(team)
        self.assertNotIn(created["join_secret"], blob)
        self.assertNotIn(created["member_token"], blob)
        self.assertIn("join_secret_hash", team)

    def test_join_with_correct_secret_then_wrong_secret(self):
        created = self._create()
        joined = self.store.join_team(
            team_id=created["team_id"], join_secret=created["join_secret"], display_name="Bob"
        )
        self.assertEqual(joined["role"], "member")
        self.assertNotEqual(joined["member_token"], created["member_token"])
        with self.assertRaises(AuthError):
            self.store.join_team(team_id=created["team_id"], join_secret="nope", display_name="Mallory")

    def test_join_missing_team(self):
        with self.assertRaises(TeamNotFoundError):
            self.store.join_team(team_id="tm_missing", join_secret="x", display_name="Y")

    def test_publish_requires_valid_member_token(self):
        created = self._create()
        profile = {"score": 100, "unlocked_count": 3, "highest_tier": "Gold"}
        self.store.publish(
            team_id=created["team_id"], member_id=created["member_id"],
            member_token=created["member_token"], profile=profile,
        )
        with self.assertRaises(AuthError):
            self.store.publish(
                team_id=created["team_id"], member_id=created["member_id"],
                member_token="wrong", profile=profile,
            )

    def test_leaderboard_requires_membership_proof(self):
        created = self._create()
        with self.assertRaises(AuthError):
            self.store.leaderboard(team_id=created["team_id"])
        board = self.store.leaderboard(team_id=created["team_id"], join_secret=created["join_secret"])
        self.assertEqual(board["member_count"], 1)
        board2 = self.store.leaderboard(
            team_id=created["team_id"], member_id=created["member_id"], member_token=created["member_token"]
        )
        self.assertEqual(board2["member_count"], 1)

    def test_leaderboard_ranks_by_score_then_unlocked(self):
        created = self._create()
        bob = self.store.join_team(team_id=created["team_id"], join_secret=created["join_secret"], display_name="Bob")
        self.store.publish(team_id=created["team_id"], member_id=created["member_id"],
                           member_token=created["member_token"], profile={"score": 50, "unlocked_count": 2})
        self.store.publish(team_id=created["team_id"], member_id=bob["member_id"],
                           member_token=bob["member_token"], profile={"score": 300, "unlocked_count": 9, "highest_tier": "Diamond"})
        board = self.store.leaderboard(team_id=created["team_id"], join_secret=created["join_secret"])["leaderboard"]
        self.assertEqual(board[0]["display_name"], "Bob")
        self.assertEqual(board[0]["rank"], 1)
        self.assertEqual(board[0]["score"], 300)
        self.assertEqual(board[1]["rank"], 2)

    def test_rank_ties_share_a_rank(self):
        rows = [
            {"display_name": "A", "score": 100, "unlocked_count": 5},
            {"display_name": "B", "score": 100, "unlocked_count": 5},
            {"display_name": "C", "score": 10, "unlocked_count": 1},
        ]
        ranked = store_mod.rank_rows(rows)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 1)  # tie
        self.assertEqual(ranked[2]["rank"], 3)  # competition ranking skips 2

    def test_leave_drops_member_and_empty_team(self):
        created = self._create()
        bob = self.store.join_team(team_id=created["team_id"], join_secret=created["join_secret"], display_name="Bob")
        self.store.leave(team_id=created["team_id"], member_id=bob["member_id"], member_token=bob["member_token"])
        board = self.store.leaderboard(team_id=created["team_id"], join_secret=created["join_secret"])
        self.assertEqual(board["member_count"], 1)
        # Last member leaving removes the team entirely.
        self.store.leave(team_id=created["team_id"], member_id=created["member_id"], member_token=created["member_token"])
        with self.assertRaises(TeamNotFoundError):
            self.store.leaderboard(team_id=created["team_id"], join_secret=created["join_secret"])


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        self.store = LeaderboardStore()
        self.owner = self.store.create_team(name="Crew", display_name="Owner")
        self.bob = self.store.join_team(
            team_id=self.owner["team_id"], join_secret=self.owner["join_secret"], display_name="Bob"
        )

    def test_only_owner_can_rotate(self):
        with self.assertRaises(AuthError):
            self.store.rotate_join_secret(
                team_id=self.owner["team_id"], member_id=self.bob["member_id"], member_token=self.bob["member_token"]
            )
        result = self.store.rotate_join_secret(
            team_id=self.owner["team_id"], member_id=self.owner["member_id"], member_token=self.owner["member_token"]
        )
        new_secret = result["join_secret"]
        self.assertNotEqual(new_secret, self.owner["join_secret"])
        # Old invite secret no longer works.
        with self.assertRaises(AuthError):
            self.store.join_team(team_id=self.owner["team_id"], join_secret=self.owner["join_secret"], display_name="Late")
        # New one does.
        self.store.join_team(team_id=self.owner["team_id"], join_secret=new_secret, display_name="Late")

    def test_only_owner_can_kick_and_not_self(self):
        with self.assertRaises(AuthError):
            self.store.kick_member(
                team_id=self.owner["team_id"], member_id=self.bob["member_id"],
                member_token=self.bob["member_token"], target_member_id=self.owner["member_id"],
            )
        with self.assertRaises(ValidationError):
            self.store.kick_member(
                team_id=self.owner["team_id"], member_id=self.owner["member_id"],
                member_token=self.owner["member_token"], target_member_id=self.owner["member_id"],
            )
        self.store.kick_member(
            team_id=self.owner["team_id"], member_id=self.owner["member_id"],
            member_token=self.owner["member_token"], target_member_id=self.bob["member_id"],
        )
        board = self.store.leaderboard(team_id=self.owner["team_id"], join_secret=self.owner["join_secret"])
        self.assertEqual(board["member_count"], 1)


class RetractAndCapTests(unittest.TestCase):
    def test_unpublish_blanks_profile_but_keeps_membership(self):
        store = LeaderboardStore()
        owner = store.create_team(name="Crew", display_name="Owner")
        store.publish(team_id=owner["team_id"], member_id=owner["member_id"],
                     member_token=owner["member_token"], profile={"score": 500, "unlocked_count": 10})
        store.unpublish(team_id=owner["team_id"], member_id=owner["member_id"], member_token=owner["member_token"])
        board = store.leaderboard(team_id=owner["team_id"], join_secret=owner["join_secret"])
        self.assertEqual(board["member_count"], 1)  # still a member
        row = board["leaderboard"][0]
        self.assertFalse(row["has_published"])
        self.assertEqual(row["score"], 0)

    def test_unpublish_requires_valid_token(self):
        store = LeaderboardStore()
        owner = store.create_team(name="Crew", display_name="Owner")
        with self.assertRaises(AuthError):
            store.unpublish(team_id=owner["team_id"], member_id=owner["member_id"], member_token="nope")

    def test_max_teams_cap(self):
        store = LeaderboardStore()
        store_mod.MAX_TEAMS  # ensure attribute exists
        original = store_mod.MAX_TEAMS
        try:
            store_mod.MAX_TEAMS = 2
            store.create_team(name="A", display_name="o")
            store.create_team(name="B", display_name="o")
            with self.assertRaises(ValidationError):
                store.create_team(name="C", display_name="o")
        finally:
            store_mod.MAX_TEAMS = original


class SanitizeProfileTests(unittest.TestCase):
    def test_sanitize_drops_unknown_and_bounds_fields(self):
        raw = {
            "score": "150",  # coerced to int
            "unlocked_count": 3,
            "tier_counts": {"Gold": 2, "Bogus": 9},
            "highest_tier": "Gold",
            "category_counts": {"Agent Autonomy": 4},
            "top_achievements": [
                {"id": "a", "name": "A", "tier": "Gold", "category": "X", "icon": "flame", "SECRET": "leak"}
            ],
            "display_name": "hi",
            "session_id": "sess-SECRET",       # must be dropped
            "raw_transcript": "private stuff",  # must be dropped
            "generated_at": 123,
        }
        clean = store_mod.sanitize_profile(raw)
        self.assertEqual(clean["score"], 150)
        self.assertEqual(clean["tier_counts"], {"Copper": 0, "Silver": 0, "Gold": 2, "Diamond": 0, "Olympian": 0})
        self.assertNotIn("Bogus", clean["tier_counts"])
        self.assertEqual(clean["top_achievements"][0].keys(), {"id", "name", "tier", "category", "icon"})
        blob = json.dumps(clean)
        self.assertNotIn("sess-SECRET", blob)
        self.assertNotIn("private stuff", blob)
        self.assertNotIn("leak", blob)

    def test_sanitize_rejects_non_dict(self):
        with self.assertRaises(ValidationError):
            store_mod.sanitize_profile(["not", "a", "dict"])

    def test_control_chars_stripped_from_display_name(self):
        clean = store_mod._clean_str("Bad\nName\x07here", max_len=64)
        self.assertNotIn("\n", clean)
        self.assertNotIn("\x07", clean)


class PersistenceTests(unittest.TestCase):
    def test_roster_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roster.json"
            store = LeaderboardStore(path=path)
            created = store.create_team(name="Persist", display_name="Owner")
            store.publish(team_id=created["team_id"], member_id=created["member_id"],
                         member_token=created["member_token"], profile={"score": 42})
            # New store instance reading the same file sees the team.
            reopened = LeaderboardStore(path=path)
            board = reopened.leaderboard(team_id=created["team_id"], join_secret=created["join_secret"])
            self.assertEqual(board["member_count"], 1)
            self.assertEqual(board["leaderboard"][0]["score"], 42)


if __name__ == "__main__":
    unittest.main()
