"""Local job-search assistant. Python 3.10+, no third-party dependencies."""

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from arbeitnow import DEFAULT_KEYWORDS, search

ROOT = Path(__file__).resolve().parent
STATUSES = ("saved", "reviewing", "applied", "interview", "rejected", "offer", "withdrawn")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def contains(text, term):
    return re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text.lower()) is not None


def assess(job, profile):
    """Transparent keyword heuristic; score is not a hiring probability."""
    title = job["title"].lower()
    description = job["description"]
    text = title + " " + description.lower()
    reasons, flags = [], []
    groups = profile.get("skills", {})
    professional = groups.get("software_and_automation", []) + groups.get("cloud_and_operations", []) + groups.get("data_and_ml", [])
    matched = sorted({s for s in professional if contains(text, s)})
    academic = sorted({s for s in groups.get("security_academic_exposure", []) if contains(text, s)})
    role_match = any(contains(title, s) for s in ("python", "software", "machine learning", "ai", "ml", "security", "cybersecurity"))
    score = 25 if role_match else 0
    if role_match:
        reasons.append("Title matches a target role family")
    score += min(45, len(matched) * 5)
    if matched:
        reasons.append("Documented skill keywords: " + ", ".join(matched))
    if academic:
        flags.append("Academic exposure only: " + ", ".join(academic))
    if re.search(r"\b(junior|graduate|entry[- ]level|berufseinsteiger)\b", title):
        score += 15
        reasons.append("Title explicitly targets early-career applicants")
    if re.search(r"\b(senior|lead|principal|head|staff)\b", title):
        score -= 30
        flags.append("Title suggests seniority above the target level")
    language = job.get("german_requirement", "unknown").upper()
    own_level = profile.get("languages", {}).get("German", "A2").upper()
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    if language in levels and own_level in levels:
        if levels.index(language) > levels.index(own_level):
            score -= 35
            flags.append(f"Required German {language} exceeds profile level {own_level}")
        else:
            reasons.append("Structured German requirement fits profile")
    elif language != "NONE":
        flags.append("German requirement needs review")
    if re.search(r"\b(german|deutsch\w*)\b", text):
        flags.append("German mentioned in advert: check exact wording and whether mandatory")
    if job.get("english_accepted") is True:
        score += 10
        reasons.append("Imported record explicitly marks English as accepted")
    else:
        flags.append("English acceptance not confirmed")
    country = job.get("country", "").lower()
    target_country = profile.get("preferences", {}).get("country", "Germany").lower()
    if country == target_country:
        score += 5
        reasons.append("Country matches preference")
    elif country:
        score -= 40
        flags.append("Country differs from preference")
    else:
        flags.append("Country not confirmed")
    employment = job.get("employment_type", "unknown").lower()
    if employment not in ("full-time", "full time", "vollzeit"):
        flags.append("Full-time employment not confirmed")
        if employment in ("internship", "part-time", "working student"):
            score -= 30
    if any(contains(title, s) for s in ("security", "cybersecurity")):
        flags.append("Check security requirements against academic knowledge; do not claim professional security experience")
    for key in ("work_authorization", "requires_sponsorship"):
        if profile.get(key) is None:
            flags.append(key.replace("_", " ") + " is missing from profile")
    return {"score": max(0, min(100, score)), "reasons": reasons, "flags": flags, "matched_skills": matched}


def validate_jobs(items):
    if not isinstance(items, list):
        raise ValueError("Job import must contain a JSON array")
    validated = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Job {index} must be an object")
        for field in ("title", "company", "description"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Job {index}: non-empty {field} is required")
        for field in ("url", "location", "country", "employment_type", "german_requirement"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"Job {index}: {field} must be text")
        if "english_accepted" in item and not isinstance(item["english_accepted"], bool):
            raise ValueError(f"Job {index}: english_accepted must be true or false")
        identity = item.get("url", "").strip() or "|".join(item.get(f, "").strip().lower() for f in ("company", "title", "location"))
        validated.append((hashlib.sha256(identity.encode()).hexdigest()[:12], item))
    return validated


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'saved', updated_at TEXT NOT NULL)")
    return db


def import_jobs(db, items):
    records = validate_jobs(items)  # Validate whole batch before writing.
    with db:
        for identifier, job in records:
            db.execute("INSERT INTO jobs(id,data,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                       (identifier, json.dumps(job, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return len(records)


def application_notes(job, profile, assessment):
    lines = [f"# Application preparation: {job['title']}", f"Company: {job['company']}",
             f"Source: {job.get('url', 'Not provided')}", "", "Draft preparation notes - review before use.",
             "Score is a keyword heuristic, not eligibility confirmation.", "", "## Relevant CV evidence"]
    selected = []
    for exp in profile.get("experience", []):
        for evidence in exp.get("evidence", []):
            if any(contains(evidence, skill) for skill in assessment["matched_skills"]):
                selected.append(f"- {exp['employer']} ({exp['role']}): {evidence}")
    lines += selected[:8] or ["- No keyword-linked evidence selected. Review the CV manually."]
    lines += ["", "## Questions to resolve"] + ["- " + flag for flag in assessment["flags"]]
    lines += ["", "## Candidate preferences", json.dumps(profile.get("preferences", {}), ensure_ascii=False, indent=2),
              "", "These notes do not submit an application or generate a tailored CV/cover letter."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "profile.json")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "jobs.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="Import a JSON array of job records")
    imp.add_argument("file", type=Path)
    discover = sub.add_parser("search", help="Fetch and save matching Arbeitnow vacancies")
    discover.add_argument("--source", choices=("arbeitnow",), default="arbeitnow")
    discover.add_argument("--location", action="append", help="City to match; repeat for nearby cities (default: Stuttgart)")
    discover.add_argument("--keyword", action="append", help="Title keyword; repeat for alternatives (default: target role keywords)")
    discover.add_argument("--all-roles", action="store_true", help="Disable title filtering")
    discover.add_argument("--pages", type=int, default=5, help="Maximum feed pages to scan (1-100; default: 5)")
    rank = sub.add_parser("rank", help="Rank saved jobs with reasons and review flags")
    rank.add_argument("--limit", type=int, default=10)
    rank.add_argument("--status", choices=STATUSES)
    show = sub.add_parser("show", help="Show a saved job and assessment")
    show.add_argument("id")
    draft = sub.add_parser("prepare", help="Save CV evidence and application review notes")
    draft.add_argument("id")
    status = sub.add_parser("status", help="Manually record application progress")
    status.add_argument("id")
    status.add_argument("value", choices=STATUSES)
    args = parser.parse_args(argv)
    try:
        profile = read_json(args.profile)
        if args.command == "search":
            if args.all_roles and args.keyword:
                raise ValueError("Use either --all-roles or --keyword")
            jobs, stats = search(args.location or ["Stuttgart"], [] if args.all_roles else (args.keyword or DEFAULT_KEYWORDS), args.pages)
            with connect(args.db) as db:
                count = import_jobs(db, jobs)
            print(f"Arbeitnow (https://www.arbeitnow.com): scanned {stats['scanned']} vacancies across {stats['pages']} pages; saved/updated {count} matches.")
            if stats["skipped_invalid"]:
                print(f"Skipped {stats['skipped_invalid']} invalid records.")
            if stats["page_limit_reached"]:
                print("More feed pages are available. Increase --pages to search further.")
            if not jobs:
                print("No matches in the scanned pages. Try more pages, additional locations, or --all-roles.")
            print("Run: python main.py rank")
            return 0
        with connect(args.db) as db:
            if args.command == "import":
                print(f"Imported/updated {import_jobs(db, read_json(args.file))} records.")
                return 0
            if args.command == "rank":
                rows = db.execute("SELECT * FROM jobs").fetchall()
                results = []
                for row in rows:
                    if args.status and row["status"] != args.status:
                        continue
                    job = json.loads(row["data"])
                    results.append((assess(job, profile), row, job))
                results.sort(key=lambda result: (-result[0]["score"], result[2]["title"]))
                if not results:
                    print("No jobs found. Run search or import a jobs JSON file first.")
                for assessment, row, job in results[:max(0, args.limit)]:
                    print(f"\n{row['id']} | {assessment['score']}/100 | {row['status']} | {job['title']} at {job['company']}")
                    for reason in assessment["reasons"]:
                        print("  + " + reason)
                    for flag in assessment["flags"]:
                        print("  ? " + flag)
                return 0
            row = db.execute("SELECT * FROM jobs WHERE id=?", (args.id,)).fetchone()
            if row is None:
                raise ValueError("Unknown job ID. Use rank to find IDs.")
            job = json.loads(row["data"])
            assessment = assess(job, profile)
            if args.command == "show":
                print(json.dumps({"id": row["id"], "status": row["status"], "job": job, "assessment": assessment}, ensure_ascii=False, indent=2))
            elif args.command == "prepare":
                folder = ROOT / "applications" / row["id"]
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / "preparation.md"
                target.write_text(application_notes(job, profile, assessment), encoding="utf-8")
                print(f"Saved {target}")
            elif args.command == "status":
                db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (args.value, datetime.now(timezone.utc).isoformat(), args.id))
                print(f"Recorded {args.value} for {args.id}. No external action performed.")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
