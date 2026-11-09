import unittest

from arbeitnow import normalize, search


def vacancy(**overrides):
    item = {"title": "Junior Python Developer", "company_name": "Test company",
            "description": "&lt;p&gt;Python &amp;amp; APIs&lt;/p&gt;",
            "url": "https://example.com/test-job", "location": "Stuttgart",
            "job_types": ["full_time"], "remote": False}
    item.update(overrides)
    return item


class ArbeitnowTests(unittest.TestCase):
    def test_normalizes_html_without_assuming_language_or_country(self):
        job = normalize(vacancy())
        self.assertEqual(job["description"], "Python & APIs")
        self.assertEqual(job["employment_type"], "full-time")
        self.assertNotIn("english_accepted", job)
        self.assertNotIn("country", job)
        self.assertEqual(job["german_requirement"], "unknown")

    def test_paginates_filters_locations_and_deduplicates(self):
        pages = []
        def fetch(page):
            pages.append(page)
            return {"data": [vacancy(location="Böblingen"), vacancy(location="Berlin", url="https://example.com/berlin")],
                    "links": {"next": "next" if page == 1 else None}}
        jobs, stats = search(["Boeblingen"], ["python"], fetcher=fetch)
        self.assertEqual(pages, [1, 2])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(stats["scanned"], 4)

    def test_short_keyword_does_not_match_inside_words(self):
        jobs, _ = search(["Stuttgart"], ["ai"], fetcher=lambda _: {
            "data": [vacancy(title="Retail assistant")], "links": {"next": None}})
        self.assertEqual(jobs, [])

    def test_cap_and_invalid_record_are_reported(self):
        jobs, stats = search(["Stuttgart"], [], max_pages=1, fetcher=lambda _: {
            "data": [vacancy(), {"title": "broken"}], "links": {"next": "next"}})
        self.assertEqual(len(jobs), 1)
        self.assertTrue(stats["page_limit_reached"])
        self.assertEqual(stats["skipped_invalid"], 1)

    def test_bad_response_and_bad_page_limit_fail(self):
        with self.assertRaises(ValueError):
            search([], [], fetcher=lambda _: {"error": "unavailable"})
        with self.assertRaises(ValueError):
            search([], [], max_pages=0)


if __name__ == "__main__":
    unittest.main()
