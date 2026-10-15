"""Normalize the German job export and filter only employment types in SQLite.

Listing text is untrusted data. HTML is reduced to plain text and script/style
content is discarded. Contract labels (e.g. Befristet) stay separate from job
categories (e.g. Werkstudierendenstelle und HiWi-Stellen). Location, work model
and hours remain job information for contextual matching, never SQL exclusions.
"""

from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from urllib.parse import urlsplit


EMPLOYMENT_TYPES = frozenset({
    "werkstudent", "praktikum", "vollzeit", "teilzeit", "ausbildung",
    "trainee", "abschlussarbeit", "sonstige",
})
REMOTE_TYPES = frozenset({"onsite", "hybrid", "remote", "unknown"})


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if not self.hidden_depth and tag in {
            "p", "br", "div", "li", "ul", "ol", "section", "tr", "td",
            "h1", "h2", "h3", "h4", "h5", "h6",
        }:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        if not self.hidden_depth:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def plain_text(value: Any) -> str:
    """Return compact plain text without turning NULL into the word 'None'."""
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    parser = _PlainTextParser()
    parser.feed(str(value))
    parser.close()
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", "".join(parser.parts))
    return " ".join(cleaned.split())


def _labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return []
    labels = [plain_text(item.get("bezeichnung") if isinstance(item, dict) else item)
              for item in value]
    return list(dict.fromkeys(label for label in labels if label))


def _employment_types(categories: list[str], contracts: list[str], title: str) -> list[str]:
    # Explicit source categories are authoritative for student placements. A
    # permanent contract is not evidence of full-time hours, nor is a generic
    # Berufseinstieg label. Only explicit full-/part-time wording adds those.
    category_text = " ".join(categories).casefold()
    all_text = " ".join([category_text, *contracts, title]).casefold()
    found: list[str] = []
    patterns = {
        "werkstudent": r"werkstudent|werkstudierend|\bhiwi\b|working student",
        "praktikum": r"praktikum|praktika|praktikant|\binternship\b",
        "abschlussarbeit": r"abschlussarbeit|bachelorarbeit|masterarbeit|\bthesis\b",
        "ausbildung": r"\bausbildung\b|\bauszubildend\w*|\bazubi\b",
        "trainee": r"trainee",
        "vollzeit": r"\bvollzeit\b|\bfull[ -]?time\b",
        "teilzeit": r"\bteilzeit\b|\bpart[ -]?time\b",
    }
    for canonical, pattern in patterns.items():
        if re.search(pattern, all_text):
            found.append(canonical)
    return found or ["sonstige"]


def _hours(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _remote(value: Any) -> str:
    raw = plain_text(value).casefold()
    if raw in REMOTE_TYPES:
        return raw
    if re.fullmatch(r"100\s*%\s*(homeoffice|home office|remote)?", raw):
        return "remote"
    if re.fullmatch(r"0\s*%\s*(homeoffice|home office|remote)?", raw):
        return "onsite"
    if re.fullmatch(r"(?:0\s*[-–]\s*49|50\s*[-–]\s*100)\s*%\s*home\s*office", raw):
        return "hybrid"
    return "unknown"


def _safe_application_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if any(ord(character) < 32 or character.isspace() for character in url):
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username:
            return url
    except ValueError:
        pass
    return ""


def normalize_job(source: dict[str, Any]) -> dict[str, Any]:
    """Convert one export record to the public job representation."""
    if not isinstance(source, dict):
        raise ValueError("Each job must be a JSON object.")
    source_id = source.get("jobId")
    if isinstance(source_id, bool) or not isinstance(source_id, (str, int)) or not str(source_id).strip():
        raise ValueError("Each job needs a non-empty string or integer jobId.")
    title = plain_text(source.get("angebotstitel"))
    if not title:
        raise ValueError(f"Job {source_id} needs an angebotstitel.")
    categories = _labels(source.get("jobKategorie"))
    contracts = _labels(source.get("anstellungsart"))
    professional_fields = _labels(source.get("berufsfeld"))
    requirements = plain_text(source.get("erwartungenTitelText"))
    tasks = plain_text(source.get("aufgabenTitelText"))
    summary = plain_text(source.get("kurzbeschreibung"))
    introduction = plain_text(source.get("einleitungTitelText"))
    benefits = plain_text(source.get("angebotTitelText"))
    company = plain_text(source.get("prsFirma"))
    location = plain_text(source.get("arbeitsort"))
    employment = _employment_types(categories, contracts, title)
    hours_min, hours_max = _hours(source.get("arbeitszeitMin")), _hours(source.get("arbeitszeitMax"))
    if hours_min is not None and hours_max is not None and hours_min > hours_max:
        # An invalid interval cannot support a reliable scheduling comparison.
        hours_min = hours_max = None
    description = "\n\n".join(part for part in [summary, introduction, tasks, requirements, benefits] if part)
    search_text = "\n".join(part for part in [
        f"Anforderungen: {requirements}" if requirements else "",
        f"Aufgaben: {tasks}" if tasks else "",
        f"Stelle: {title}",
        f"Berufsfelder: {', '.join(professional_fields)}" if professional_fields else "",
        f"Kategorien: {', '.join(categories)}" if categories else "",
        f"Firma: {company}" if company else "",
        f"Ort: {location}" if location else "",
        summary, introduction, benefits,
    ] if part)
    return {
        "id": str(source_id).strip(), "title": title, "company": company,
        "location": location, "employment_types": employment,
        "contract_types": contracts, "categories": categories,
        "professional_fields": professional_fields, "summary": summary,
        "tasks": tasks, "requirements": requirements, "benefits": benefits,
        "description": description, "search_text": search_text,
        "remote": _remote(source.get("homeOffice")), "hours_min": hours_min,
        "hours_max": hours_max,
        "application_url": _safe_application_url(source.get("bewerberportal")),
    }


class JobStore:
    """File-backed SQLite store; one short-lived connection per operation."""

    def __init__(self, db_path: str | Path):
        if str(db_path) == ":memory:":
            raise ValueError("Use a SQLite file path; :memory: does not persist across connections.")
        self.db_path = Path(db_path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    location_fold TEXT NOT NULL,
                    remote TEXT NOT NULL,
                    hours_min REAL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_employment_types (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    employment_type TEXT NOT NULL,
                    PRIMARY KEY (job_id, employment_type)
                );
                CREATE INDEX IF NOT EXISTS idx_job_employment_type
                    ON job_employment_types(employment_type, job_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_remote ON jobs(remote);
                CREATE INDEX IF NOT EXISTS idx_jobs_hours_min ON jobs(hours_min);
            """)

    @staticmethod
    def _read_jobs(path: str | Path, allow_control_characters: bool) -> list[dict[str, Any]]:
        def reject_nonfinite(value: str) -> None:
            raise ValueError(f"Non-standard JSON number: {value}")

        with Path(path).expanduser().open(encoding="utf-8-sig") as handle:
            raw_jobs = json.load(handle, strict=not allow_control_characters,
                                 parse_constant=reject_nonfinite)
        if not isinstance(raw_jobs, list):
            raise ValueError("The job import must be a JSON list of job objects.")
        normalized = []
        for index, raw_job in enumerate(raw_jobs):
            try:
                normalized.append(normalize_job(raw_job))
            except ValueError as error:
                raise ValueError(f"Invalid job at index {index}: {error}") from error
        return normalized

    @staticmethod
    def _upsert(connection: sqlite3.Connection, jobs: list[dict[str, Any]]) -> dict[str, int]:
        inserted = updated = 0
        for job in jobs:
            exists = connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job["id"],)).fetchone()
            inserted += not bool(exists)
            updated += bool(exists)
            connection.execute("""
                INSERT INTO jobs (id, location_fold, remote, hours_min, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    location_fold=excluded.location_fold, remote=excluded.remote,
                    hours_min=excluded.hours_min, payload=excluded.payload
            """, (job["id"], job["location"].casefold(), job["remote"], job["hours_min"],
                  json.dumps(job, ensure_ascii=False, allow_nan=False)))
            connection.execute("DELETE FROM job_employment_types WHERE job_id = ?", (job["id"],))
            connection.executemany(
                "INSERT INTO job_employment_types (job_id, employment_type) VALUES (?, ?)",
                [(job["id"], kind) for kind in job["employment_types"]],
            )
        total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        return {"imported": len(jobs), "inserted": inserted, "updated": updated, "total": total}

    def import_json(self, path: str | Path, allow_control_characters: bool = False) -> dict[str, Any]:
        """Atomically validate and upsert an export; malformed JSON stays strict by default."""
        if not isinstance(allow_control_characters, bool):
            raise ValueError("allow_control_characters must be a boolean.")
        jobs = self._read_jobs(path, allow_control_characters)
        with self._connection() as connection:
            stats = self._upsert(connection, jobs)
        return {**stats, "control_characters_allowed": allow_control_characters}

    def seed_if_empty(self, path: str | Path) -> dict[str, Any]:
        # Lock before the emptiness check so simultaneous Gunicorn workers do
        # not both seed the store. The five-row fixture is read only if needed.
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if total:
                return {"imported": 0, "inserted": 0, "updated": 0, "total": total,
                        "control_characters_allowed": False}
            jobs = self._read_jobs(path, allow_control_characters=False)
            return {**self._upsert(connection, jobs), "control_characters_allowed": False}

    def count(self) -> int:
        with self._connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def filter_jobs(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Strictly filter employment types with OR semantics; [] includes all types.

        The legacy ``filters`` container also carries locations, remote and
        max_hours for API/session compatibility. Those values are ignored here:
        they are preferences for the LLM, including when job details are unknown.
        CV content belongs to the profile and never becomes a SQL restriction.
        """
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object.")
        unsupported = set(filters) - {"employment_types", "locations", "remote", "max_hours"}
        if unsupported:
            raise ValueError(f"Unsupported filter-container field(s): {', '.join(sorted(unsupported))}")
        employment = filters.get("employment_types", [])
        if not isinstance(employment, list) or any(not isinstance(item, str) or not item.strip() for item in employment):
            raise ValueError("employment_types must be a list of non-empty strings.")
        employment = list(dict.fromkeys(item.strip().casefold() for item in employment))
        if any(item not in EMPLOYMENT_TYPES for item in employment):
            raise ValueError(f"Invalid employment_types; allowed values: {', '.join(sorted(EMPLOYMENT_TYPES))}")
        sql = "SELECT j.payload FROM jobs j"
        if employment:
            sql += (" WHERE EXISTS (SELECT 1 FROM job_employment_types e WHERE e.job_id=j.id "
                    "AND e.employment_type IN (" + ",".join("?" for _ in employment) + "))")
        sql += " ORDER BY j.id"
        with self._connection() as connection:
            return [json.loads(row["payload"]) for row in connection.execute(sql, employment)]
