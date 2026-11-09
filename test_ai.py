import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agent import run_agent
from ai_jobs import candidate_context, draft_application, evaluate
from llm_client import AIError, Client, load_env
from main import connect, import_jobs, main


PROFILE = {"email": "private@example.com", "phone": "secret", "provenance": {"resume_path": "private"},
           "languages": {"German": "A2"}, "skills": {"software": ["Python"]}, "preferences": {"country": "Germany"}}
JOB = {"title": "Python Developer", "company": "Test", "description": "Develop Python services", "url": "https://example.com/test"}
RESULT = {"score": 70, "recommendation": "consider", "summary": "Review requirements", "role_fit": "Python", "seniority_fit": "unknown",
          "language_fit": "unknown", "missing_requirements": [], "questions": [], "evidence_ids": ["skills.software.0"]}


class AITests(unittest.TestCase):
    def test_context_excludes_private_fields(self):
        context = candidate_context(PROFILE)
        self.assertNotIn("email", context)
        self.assertNotIn("phone", context)
        self.assertNotIn("provenance", context)

    def test_env_does_not_override_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "existing"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('OPENAI_API_KEY="file-key"\nOPENAI_MODEL=gpt-4.1-mini\nUNRELATED=value\n')
            load_env(path)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "existing")
            self.assertNotIn("UNRELATED", os.environ)

    def test_cache_invalidation_and_evidence_validation(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.closing(connect(Path(directory) / "jobs.db")) as db:
            client = Mock(model="test-model")
            client.structured.return_value = RESULT.copy()
            _, cached = evaluate(db, "abc", JOB, PROFILE, client)
            self.assertFalse(cached)
            _, cached = evaluate(db, "abc", JOB, PROFILE, client)
            self.assertTrue(cached)
            self.assertEqual(client.structured.call_count, 1)
            evaluate(db, "abc", dict(JOB, description="Changed requirements"), PROFILE, client)
            self.assertEqual(client.structured.call_count, 2)
            client.structured.return_value = dict(RESULT, evidence_ids=["invented"])
            with self.assertRaises(AIError):
                evaluate(db, "abc", JOB, PROFILE, client, refresh=True)

    def test_drafts_preserve_earlier_files(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.closing(connect(Path(directory) / "jobs.db")) as db:
            client = Mock(model="test-model")
            client.structured.side_effect = [RESULT.copy(), {"subject": "Application", "cover_letter": "Draft", "evidence_ids": ["skills.software.0"], "review_notes": []},
                                           {"subject": "Application", "cover_letter": "Draft 2", "evidence_ids": ["skills.software.0"], "review_notes": []}]
            one = draft_application(db, "abc", JOB, PROFILE, client, Path(directory))
            two = draft_application(db, "abc", JOB, PROFILE, client, Path(directory))
            self.assertNotEqual(one, two)
            self.assertTrue(Path(one).exists())

    def test_agent_returns_tool_outputs_to_model(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.closing(connect(Path(directory) / "jobs.db")) as db:
            import_jobs(db, [JOB])
            client = Mock()
            client.respond.side_effect = [{"output": [{"type": "function_call", "name": "list_jobs", "call_id": "call1", "arguments": "{}"}]},
                {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Found saved job"}]}]}]
            with contextlib.redirect_stdout(io.StringIO()):
                answer = run_agent(db, PROFILE, client, "Show saved jobs", Path(directory), import_jobs)
            self.assertEqual(answer, "Found saved job")
            history = client.respond.call_args.args[1]
            self.assertTrue(any(item.get("type") == "function_call_output" for item in history))

    def test_unknown_tool_cannot_execute(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.closing(connect(Path(directory) / "jobs.db")) as db:
            client = Mock()
            client.respond.side_effect = [{"output": [{"type": "function_call", "name": "delete_files", "call_id": "x", "arguments": "{}"}]}, {"output": []}]
            with contextlib.redirect_stdout(io.StringIO()):
                run_agent(db, PROFILE, client, "test", Path(directory), import_jobs)
            self.assertIn("Unknown tool", json.dumps(client.respond.call_args.args[1]))

    def test_request_budget_stops_before_network(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            client = Client("missing.env", max_requests=0)
            with self.assertRaises(AIError):
                client.respond("test", "test")

    def test_quota_error_does_not_echo_response_secrets(self):
        error = HTTPError("https://api.openai.com/v1/responses", 429, "error", {},
                          io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"secret-message"}}'))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("llm_client.urlopen", side_effect=error):
            client = Client("missing.env")
            with self.assertRaises(AIError) as caught:
                client.respond("test", "test")
            self.assertIn("quota exhausted", str(caught.exception))
            self.assertNotIn("secret-message", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
