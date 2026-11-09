import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from main import ROOT, assess, connect, import_jobs


class JobAssistantTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8-sig"))
        self.jobs = [
            {"title": "Junior Python Developer", "company": "Test company", "description": "Python Docker Linux", "url": "https://example.com/test1", "english_accepted": True},
            {"title": "Security Engineer", "company": "Test company", "description": "Security", "url": "https://example.com/test2"},
        ]

    def test_language_requirement_reduces_same_job_score(self):
        accepted = dict(self.jobs[0], german_requirement="A2")
        higher = dict(accepted, german_requirement="C1")
        self.assertGreater(assess(accepted, self.profile)["score"], assess(higher, self.profile)["score"])
        self.assertTrue(any("exceeds" in flag for flag in assess(higher, self.profile)["flags"]))

    def test_reimport_preserves_status_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.closing(connect(Path(directory) / "jobs.sqlite3")) as db:
                import_jobs(db, self.jobs)
                identifier = db.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
                db.execute("UPDATE jobs SET status='applied' WHERE id=?", (identifier,))
                db.commit()
                import_jobs(db, self.jobs)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()[0], "applied")

    def test_invalid_batch_imports_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.closing(connect(Path(directory) / "jobs.sqlite3")) as db:
                with self.assertRaises(ValueError):
                    import_jobs(db, [self.jobs[0], {"title": "Incomplete"}])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
