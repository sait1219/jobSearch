"""Read Arbeitnow's public feed; all search filtering is local."""

import json
import re
import unicodedata
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://www.arbeitnow.com/api/job-board-api"
DEFAULT_KEYWORDS = ("python", "software", "machine learning", "ai", "ml", "security", "cybersecurity", "ki", "softwareentwicklung", "softwareentwickler")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = TextExtractor()
    # The feed includes both HTML and entity-encoded HTML.
    parser.feed(unescape(value))
    return " ".join("".join(parser.parts).split())


def folded(value):
    value = value.casefold().replace("oe", "o").replace("ue", "u").replace("ae", "a")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def phrase_in(text, term):
    return re.search(r"(?<!\w)" + re.escape(folded(term)) + r"(?!\w)", folded(text)) is not None


def normalize(item):
    if not isinstance(item, dict):
        raise ValueError("Arbeitnow returned a non-object job")
    for field in ("title", "company_name", "description", "url", "location"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"Arbeitnow job is missing {field}")
    job_types = item.get("job_types") or []
    if not isinstance(job_types, list) or not all(isinstance(t, str) for t in job_types):
        raise ValueError("Arbeitnow returned invalid job_types")
    types = {t.casefold().replace("_", "-") for t in job_types}
    employment = "unknown"
    for label, aliases in (
        ("working student", {"working student", "werkstudent", "working-student"}),
        ("internship", {"internship", "praktikum"}),
        ("part-time", {"part-time", "part time", "teilzeit"}),
        ("full-time", {"full-time", "full time", "vollzeit"}),
    ):
        if types & aliases:
            employment = label
            break
    description = plain_text(item["description"])
    if not description:
        raise ValueError("Arbeitnow returned an empty job description")
    return {
        "title": item["title"], "company": item["company_name"],
        "description": description, "url": item["url"], "location": item["location"],
        "employment_type": employment, "german_requirement": "unknown",
        "source": "Arbeitnow", "source_url": "https://www.arbeitnow.com",
        "source_id": item.get("slug"), "created_at": item.get("created_at"),
        "remote": item.get("remote") is True,
        # A city alone does not prove a country; no language inference from advert text.
    }


def fetch_page(page):
    request = Request(f"{API}?page={page}", headers={"Accept": "application/json", "User-Agent": "LocalJobSearch/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValueError(f"Arbeitnow HTTP {exc.code}; try again later") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Could not connect to Arbeitnow: {exc}") from exc


def search(locations, keywords, max_pages=10, fetcher=None):
    """Return matches and scan statistics, without writing partial results on failure."""
    if not 1 <= max_pages <= 100:
        raise ValueError("pages must be between 1 and 100")
    fetcher = fetcher or fetch_page
    jobs, seen = [], set()
    stats = {"pages": 0, "scanned": 0, "matched": 0, "skipped_invalid": 0, "page_limit_reached": False}
    for page in range(1, max_pages + 1):
        payload = fetcher(page)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Unexpected Arbeitnow response: expected a data array")
        stats["pages"] += 1
        for item in payload["data"]:
            stats["scanned"] += 1
            try:
                job = normalize(item)
            except ValueError:
                stats["skipped_invalid"] += 1
                continue
            if locations and not any(phrase_in(job["location"], city) for city in locations):
                continue
            if keywords and not any(phrase_in(job["title"], term) for term in keywords):
                continue
            if job["url"] in seen:
                continue
            seen.add(job["url"])
            if any(phrase_in(job["location"], country) for country in ("Germany", "Deutschland")):
                job["country"] = "Germany"
            jobs.append(job)
        links = payload.get("links")
        if not isinstance(links, dict) or "next" not in links:
            raise ValueError("Unexpected Arbeitnow response: missing pagination links.next")
        if not links["next"] or not payload["data"]:
            break
        if page == max_pages:
            stats["page_limit_reached"] = True
    stats["matched"] = len(jobs)
    return jobs, stats
