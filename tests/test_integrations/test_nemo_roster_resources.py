"""Offline mechanical resource contract; Gym SDK tests are opt-in."""

import importlib.util
import unittest
from unittest.mock import MagicMock

from healthcraft.integrations.nemo_roster import (
    FIXTURE_KEY,
    MECHANICAL_PROMPT,
    RosterSessions,
    SessionError,
    response_completion,
)


def completed_response():
    return {
        "id": "offline-response",
        "created_at": 0,
        "model": "no-model",
        "object": "response",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Done.", "annotations": []}],
            }
        ],
    }


class TestRosterSessions(unittest.TestCase):
    def setUp(self):
        self.sessions = RosterSessions()
        self.seed = self.sessions.seed("cookie-a", FIXTURE_KEY, "episode-a")

    def retrieve_all(self, session="cookie-a"):
        search = self.sessions.call(session, "searchEncounters", {})
        self.assertEqual(search["status"], "ok")
        self.assertEqual(len(search["data"]), 4)
        self.assertNotIn("authored_observations", search["data"][0])
        for row in search["data"]:
            detail = self.sessions.call(session, "getEncounterDetails", {"encounter_id": row["id"]})
            self.assertEqual(set(detail["data"]["authored_observations"]), {"bed", "summary"})
            history = self.sessions.call(
                session, "getPatientHistory", {"patient_id": row["patient_id"]}
            )
            self.assertEqual(history["data"]["encounter_ids"], [row["id"]])
        return search["data"]

    def test_discovery_real_handlers_and_independent_mechanical_verification(self):
        self.assertNotIn("roster", self.seed)
        self.assertNotIn("PAT-", MECHANICAL_PROMPT)
        self.assertNotIn("ENC-", MECHANICAL_PROMPT)
        self.retrieve_all()
        result = self.sessions.verify("cookie-a", "episode-a", "complete")
        self.assertEqual(result["reward"], 1.0)
        self.assertTrue(result["mechanical_passed"])
        self.assertTrue(result["execution_completed"])
        self.assertFalse(result["benchmark_comparable"])
        self.assertIsNone(result["benchmark_score"])
        self.assertEqual(result["certificate"]["coverage"]["measured_clinical_criteria"], 0)
        self.assertEqual(len(self.sessions.snapshot("cookie-a")["calls"]), 9)

    def test_duplicate_missing_wrong_identity_and_incomplete_execution_do_not_pass(self):
        rows = self.sessions.call("cookie-a", "searchEncounters", {})["data"]
        for _ in rows:
            self.sessions.call("cookie-a", "getEncounterDetails", {"encounter_id": rows[0]["id"]})
        wrong = self.sessions.call(
            "cookie-a", "getEncounterDetails", {"encounter_id": "ENC-FFFFFFFFFFFF"}
        )
        self.assertEqual(wrong["status"], "error")
        result = self.sessions.verify("cookie-a", "episode-a", "complete")
        self.assertEqual(result["reward"], 0.0)
        self.assertEqual(result["certificate"]["coverage"]["retrieved_members"], 1)
        self.retrieve_all()
        interrupted = self.sessions.verify("cookie-a", "episode-a", "incomplete")
        self.assertTrue(interrupted["certificate"]["mechanical_passed"])
        self.assertFalse(interrupted["mechanical_passed"])
        self.assertEqual(interrupted["reward"], 0.0)
        self.assertFalse(interrupted["mask_sample"])

    def test_sessions_seed_identity_close_and_snapshots_are_isolated(self):
        before = self.sessions.seed("cookie-a", FIXTURE_KEY, "episode-a")
        self.retrieve_all()
        self.assertEqual(self.sessions.seed("cookie-a", FIXTURE_KEY, "episode-a"), before)
        with self.assertRaises(SessionError):
            self.sessions.seed("cookie-a", FIXTURE_KEY, "different-episode")
        self.sessions.seed("cookie-b", FIXTURE_KEY, "episode-b")
        self.assertEqual(self.sessions.snapshot("cookie-b")["calls"], [])
        copy = self.sessions.snapshot("cookie-a")
        copy["calls"][0]["response"]["data"].clear()
        self.assertEqual(len(self.sessions.snapshot("cookie-a")["calls"][0]["response"]["data"]), 4)
        with self.assertRaises(SessionError):
            self.sessions.close("cookie-b", "cookie-a", "episode-a")
        self.sessions.close("cookie-a", "cookie-a", "episode-a")
        self.assertEqual(self.sessions.active_count, 1)
        with self.assertRaises(SessionError):
            self.sessions.call("cookie-a", "searchEncounters", {})
        with self.assertRaises(SessionError):
            self.sessions.seed("cookie-a", FIXTURE_KEY, "episode-a")
        self.assertEqual(self.sessions.call("cookie-b", "searchEncounters", {})["status"], "ok")
        with self.assertRaises(SessionError):
            self.sessions.call("never-seeded", "searchEncounters", {})

    def test_changed_final_facts_fail_and_mutation_routes_are_not_exposed(self):
        rows = self.retrieve_all()
        session = self.sessions._sessions["cookie-a"]
        encounter = session.world.get_entity("encounter", rows[0]["id"])
        encounter["authored_observations"]["summary"] = "Altered source facts"
        result = self.sessions.verify("cookie-a", "episode-a", "complete")
        self.assertEqual(result["reward"], 0.0)
        self.assertFalse(result["certificate"]["checks"]["final_world_source_concordant"])
        with self.assertRaises(SessionError):
            self.sessions.call(
                "cookie-a", "updateEncounter", {"encounter_id": rows[0]["id"], "notes": "no"}
            )

    def test_completion_is_distinct_from_retrieval(self):
        self.assertEqual(response_completion(completed_response())[0], "complete")
        response = completed_response()
        response.pop("status")
        self.assertEqual(response_completion(response)[0], "unknown")
        response = completed_response()
        response["status"] = "incomplete"
        self.assertEqual(response_completion(response)[0], "incomplete")
        response = completed_response()
        response["output"].insert(
            0,
            {
                "type": "function_call",
                "name": "searchEncounters",
                "arguments": "{}",
                "call_id": "call-1",
                "status": "completed",
            },
        )
        self.assertEqual(response_completion(response)[0], "incomplete")

    def test_invalid_server_evidence_is_masked_as_infrastructure_failure(self):
        self.retrieve_all()
        self.sessions._sessions["cookie-a"].recorder._calls[0]["audit_index"] = 999
        result = self.sessions.verify("cookie-a", "episode-a", "complete")
        self.assertEqual(result["reward"], 0.0)
        self.assertTrue(result["mask_sample"])
        self.assertEqual(result["failure_kind"], "verifier_error")
        self.assertIsNone(result["certificate"])


@unittest.skipUnless(importlib.util.find_spec("nemo_gym"), "Optional pinned Gym SDK unavailable")
class TestGymRosterResources(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from nemo_gym.server_utils import ServerClient

        from integrations.nemo_gym.roster_resources import (
            RosterResourcesConfig,
            RosterResourcesServer,
        )

        self.server = RosterResourcesServer(
            config=RosterResourcesConfig(
                host="127.0.0.1", port=0, entrypoint="roster_resources.py", name="offline-roster"
            ),
            server_client=MagicMock(spec=ServerClient),
        )
        app = self.server.setup_webserver()
        self.a, self.b = TestClient(app), TestClient(app)
        self.seed_body = {"fixture_key": FIXTURE_KEY, "episode_id": "episode-a"}

    def tearDown(self):
        self.a.close()
        self.b.close()

    def verify_body(self, **extra):
        return {
            **self.seed_body,
            "responses_create_params": {"input": MECHANICAL_PROMPT},
            "response": completed_response(),
            **extra,
        }

    def test_cookie_seed_tools_verify_and_cleanup_with_actual_sdk(self):
        seed = self.a.post(
            "/seed_session",
            json={**self.seed_body, "responses_create_params": {"input": MECHANICAL_PROMPT}},
        )
        self.assertEqual(seed.status_code, 200, seed.text)
        rows = self.a.post("/searchEncounters", json={}).json()["data"]
        self.assertEqual(len(rows), 4)
        for row in rows:
            result = self.a.post("/getEncounterDetails", json={"encounter_id": row["id"]})
            self.assertEqual(result.json()["status"], "ok", result.text)
        result = self.a.post(
            "/verify", json=self.verify_body(expected_facts=["forged"], reward=999)
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["reward"], 1.0)
        self.assertFalse(result.json()["benchmark_comparable"])
        self.b.post("/seed_session", json={**self.seed_body, "episode_id": "episode-b"})
        untouched = self.b.post("/verify", json=self.verify_body(episode_id="episode-b")).json()
        self.assertEqual(untouched["reward"], 0.0)
        self.assertEqual(untouched["certificate"]["coverage"]["retrieved_members"], 0)
        self.assertEqual(self.a.get("/reverify_mode").json(), "unsupported")
        close = self.a.post(
            "/close_session",
            json={
                "resources_session_id": seed.json()["resources_session_id"],
                "episode_id": "episode-a",
            },
        )
        self.assertEqual(close.status_code, 200, close.text)
        self.assertEqual(self.server.sessions.active_count, 1)
        self.assertEqual(self.a.post("/searchEncounters", json={}).status_code, 409)
        invalid = self.a.post("/verify", json=self.verify_body()).json()
        self.assertTrue(invalid["mask_sample"])
        self.assertEqual(invalid["reward"], 0.0)

    def test_missing_cookie_conflicting_seed_and_cross_session_close(self):
        self.assertEqual(self.a.post("/searchEncounters", json={}).status_code, 409)
        first = self.a.post("/seed_session", json=self.seed_body).json()
        self.assertEqual(self.a.post("/seed_session", json=self.seed_body).json(), first)
        self.assertEqual(
            self.a.post(
                "/seed_session", json={**self.seed_body, "episode_id": "other"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.b.post(
                "/getEncounterDetails", json={"encounter_id": "ENC-FFFFFFFFFFFF"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.b.post(
                "/close_session",
                json={
                    "resources_session_id": first["resources_session_id"],
                    "episode_id": "episode-a",
                },
            ).status_code,
            409,
        )


if __name__ == "__main__":
    unittest.main()
