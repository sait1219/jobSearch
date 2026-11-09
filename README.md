# AI job-search assistant

A deterministic Python CLI for discovering, assessing and tracking jobs against your profile. Python 3.10+; standard library only. Arbeitnow search requires internet access but no API key. It does not yet use an LLM, generate final application documents, fill forms or submit applications.

## Run

Install Python 3.10+ if unavailable, then use `python` (or `py` on Windows):

```powershell
python main.py --help
python main.py search
python main.py rank
```

Search defaults to Stuttgart and Python/software/AI/ML/security title keywords. Locations and keywords are matched locally against a paginated feed, not sent as API search parameters. By default only the first five pages are scanned; this is not an exhaustive search. Increase the cap to scan older postings (maximum 100 pages). Examples:

```powershell
python main.py search --location Stuttgart --location Boeblingen --location Sindelfingen --pages 20
python main.py search --location Stuttgart --keyword Python --keyword "machine learning" --pages 10
python main.py search --location Stuttgart --all-roles
```

Repeated `--location` values are alternatives, as are repeated `--keyword` values. Location matching uses city names, not a distance radius; Böblingen and Boeblingen are treated alike. Remote jobs outside the selected cities are not automatically included. Full-time status and seniority remain visible to the ranker rather than being hard filters; missing employment data is left unknown. The connector removes HTML, retains source URLs, and does not infer language acceptance from an advert or its promotional footer. A city alone does not confirm country. Network or response failures stop the search before database writes. Invalid individual records are skipped and counted. No candidate profile information is sent to Arbeitnow.

Listings provided by [Arbeitnow](https://www.arbeitnow.com). [Official API information](https://www.arbeitnow.com/blog/job-board-api).

Existing manual imports and tracking commands remain available:

```powershell
python main.py import jobs.example.json
python main.py rank
python main.py show JOB_ID
python main.py prepare JOB_ID
python main.py status JOB_ID reviewing
python -m unittest -v
```

Replace JOB_ID with an ID printed by `rank`. Example jobs are fictional and only demonstrate behavior. Import your own JSON file using the same structure. Required fields: title, company, description. Optional fields: url, location, country, employment_type, german_requirement (none/A1/A2/B1/B2/C1/C2/unknown), english_accepted (boolean). These fields should reflect the advert, not assumptions. For unclear language requirements, omit the field. English-language text alone does not confirm English acceptance.

Repeated imports update a matching URL, or company/title/location when no URL exists, preserving application status. This does not detect the same vacancy posted at different URLs. The full batch is validated before database changes. Ranking re-reads your profile every run.

Scores are explainable keyword heuristics, not probabilities or proof of eligibility. Negations and nuanced requirements need manual review. All flags remain visible, including higher German requirements. Academic security tools are distinguished from professional experience. Salary, relocation and availability are stored but not yet used for scoring. Work authorization and sponsorship are currently null in the profile and must be filled before answering employers.

`prepare` selects existing CV evidence into `applications/JOB_ID/preparation.md`; rerunning replaces those generated notes. `status ... applied` only records a status; it does not send anything. Available statuses: saved, reviewing, applied, interview, rejected, offer, withdrawn.

Candidate data and generated files remain local and are ignored by Git by default. If already tracked, .gitignore does not untrack them. Do not commit private documents or credentials.

## Next milestones

1. Improve search and filtering using feedback from Arbeitnow results.
2. Evaluate matching with real adverts and your feedback.
3. Add optional LLM drafting using approved CV evidence.
4. Add application review and browser-assisted submission.
