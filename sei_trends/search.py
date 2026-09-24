"""Paper search: OpenAlex + arXiv, with review/non-SEI filtering and de-duplication."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

from .schemas import Paper

log = logging.getLogger(__name__)

DEFAULT_QUERIES = (
    '"solid electrolyte interphase"',
    '"solid-electrolyte interphase"',
    "SEI lithium metal anode",
    "SEI electrolyte additive",
    "SEI graphite silicon anode",
    "SEI sodium ion anode",
    "anode interphase LiF inorganic-rich",
)

# Title/abstract markers of non-original work. Checked on the title always, and
# on the first sentence of the abstract (where "In this review, ..." appears).
REVIEW_PATTERNS = re.compile(
    r"\b(review|reviews|reviewing|minireview|mini-review|perspective|perspectives|overview|outlook|"
    r"roadmap|tutorial|progress (?:in|on|of)|recent (?:advances|advancements|developments|progress)|"
    r"state[- ]of[- ]the[- ]art|a critical look|challenges and (?:opportunities|prospects|strategies)|"
    r"research progress|advances in|insights? into recent|editorial|primer|comment on|综述|进展)\b",
    re.IGNORECASE,
)
ABSTRACT_REVIEW_PATTERNS = re.compile(
    r"\b(this|the present|our) (review|perspective|minireview|mini-review|overview|account)\b|"
    r"\bwe (review|summari[sz]e|overview|survey) (the |recent )|\bis reviewed\b|\bare reviewed\b|"
    r"\bcomprehensive(ly)? (review|summary)\b",
    re.IGNORECASE,
)
SEI_PATTERN = re.compile(r"\bSEI\b|solid[- ]electrolyte interphase|\binterphases?\b", re.IGNORECASE)

NON_RESEARCH_TYPES = {"review", "editorial", "letter-to-editor", "erratum", "retraction", "paratext", "book-chapter"}


def is_probably_review(title: str, abstract: str = "", work_type: str | None = None) -> bool:
    if work_type and work_type.lower() in NON_RESEARCH_TYPES:
        return True
    if REVIEW_PATTERNS.search(title or ""):
        return True
    head = (abstract or "")[:600]
    return bool(ABSTRACT_REVIEW_PATTERNS.search(head))


def is_sei_relevant(title: str, abstract: str) -> bool:
    return bool(SEI_PATTERN.search(f"{title} {abstract}"))


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def make_paper_id(doi: str | None, arxiv_id: str | None, title: str) -> str:
    if doi:
        return "doi:" + doi.lower().removeprefix("https://doi.org/")
    if arxiv_id:
        return "arxiv:" + re.sub(r"v\d+$", "", arxiv_id)
    return "title:" + hashlib.sha1(normalize_title(title).encode()).hexdigest()[:16]


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)  # JATS / HTML tags
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = [(i, w) for w, idxs in inverted.items() for i in idxs]
    return " ".join(w for _, w in sorted(positions))


def search_openalex(
    query: str,
    *,
    from_date: str,
    limit: int,
    mailto: str | None = None,
    session: requests.Session | None = None,
) -> list[Paper]:
    http = session or requests.Session()
    params = {
        "search": query,
        # type:article excludes OpenAlex's "review" type; preprints are kept.
        "filter": f"type:article|preprint,from_publication_date:{from_date},has_abstract:true",
        "sort": "publication_date:desc",
        "per-page": str(min(limit, 200)),
    }
    if mailto:
        params["mailto"] = mailto
    resp = http.get("https://api.openalex.org/works", params=params, timeout=30)
    resp.raise_for_status()
    papers = []
    for w in resp.json().get("results", []):
        title = _clean(w.get("display_name") or w.get("title"))
        if not title:
            continue
        doi = (w.get("doi") or "").removeprefix("https://doi.org/") or None
        source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        papers.append(
            Paper(
                id=make_paper_id(doi, None, title),
                title=title,
                abstract=_clean(_openalex_abstract(w.get("abstract_inverted_index"))),
                year=w.get("publication_year"),
                publication_date=w.get("publication_date"),
                venue=source,
                doi=doi,
                url=w.get("doi") or w.get("id"),
                authors=[
                    a["author"]["display_name"]
                    for a in (w.get("authorships") or [])[:8]
                    if a.get("author", {}).get("display_name")
                ],
                cited_by=w.get("cited_by_count"),
                source="openalex",
                work_type=w.get("type"),
            )
        )
    return papers


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _arxiv_query(query: str) -> str:
    # Keep quoted phrases intact; AND the remaining terms over all fields.
    phrases = re.findall(r'"([^"]+)"', query)
    rest = re.sub(r'"[^"]+"', " ", query).split()
    parts = [f'abs:"{p}"' for p in phrases] + [f"all:{t}" for t in rest]
    return " AND ".join(parts) + " AND (cat:cond-mat.mtrl-sci OR cat:physics.chem-ph OR cat:physics.app-ph)"


def parse_arxiv_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers = []
    for e in root.findall("a:entry", _ATOM):
        title = _clean(e.findtext("a:title", "", _ATOM))
        arxiv_url = e.findtext("a:id", "", _ATOM)
        arxiv_id = arxiv_url.rsplit("/abs/", 1)[-1]
        doi = e.findtext("arxiv:doi", None, _ATOM)
        published = e.findtext("a:published", "", _ATOM)[:10] or None
        comment = e.findtext("arxiv:comment", "", _ATOM) or ""
        papers.append(
            Paper(
                id=make_paper_id(doi, arxiv_id, title),
                title=title,
                abstract=_clean(e.findtext("a:summary", "", _ATOM)),
                year=int(published[:4]) if published else None,
                publication_date=published,
                venue="arXiv",
                doi=doi,
                url=arxiv_url,
                authors=[_clean(a.findtext("a:name", "", _ATOM)) for a in e.findall("a:author", _ATOM)][:8],
                source="arxiv",
                work_type="review" if re.search(r"\breview\b", comment, re.I) else "preprint",
            )
        )
    return papers


def search_arxiv(
    query: str, *, from_date: str, limit: int, session: requests.Session | None = None
) -> list[Paper]:
    http = session or requests.Session()
    params = {
        "search_query": _arxiv_query(query),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(limit),
    }
    resp = http.get("https://export.arxiv.org/api/query", params=params, timeout=30)
    resp.raise_for_status()
    return [p for p in parse_arxiv_feed(resp.text) if (p.publication_date or "9999") >= from_date]


# ---------------------------------------------------------------------------
# Local import (for exports from Web of Science / Scopus / Zotero, or offline use)
# ---------------------------------------------------------------------------


# Column names used by Web of Science (tab-delimited/csv) and Scopus exports.
_COLUMN_ALIASES = {
    "article title": "title",
    "ti": "title",
    "ab": "abstract",
    "publication year": "year",
    "py": "year",
    "di": "doi",
    "source title": "venue",
    "so": "venue",
    "author full names": "authors",
    "au": "authors",
    "link": "url",
    "document type": "work_type",
    "dt": "work_type",
}


def load_papers_file(path: Path) -> list[Paper]:
    """Load papers from .json/.jsonl (Paper fields) or .csv/.tsv (title, abstract, year, doi, ...;
    Web of Science and Scopus export column names are also recognised)."""
    rows: list[dict]
    if path.suffix in (".csv", ".tsv", ".txt"):
        with path.open(newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            rows = list(csv.DictReader(f, delimiter="\t" if "\t" in sample.splitlines()[0] else ","))
    elif path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("papers", [])
    papers = []
    for r in rows:
        r = {k.strip().lower(): v for k, v in r.items() if k and v not in (None, "")}
        for alias, canonical in _COLUMN_ALIASES.items():
            if alias in r and canonical not in r:
                r[canonical] = r[alias]
        title = _clean(r.get("title"))
        if not title:
            continue
        year = r.get("year")
        authors = r.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in re.split(r";|\band\b", authors) if a.strip()]
        papers.append(
            Paper(
                id=r.get("id") or make_paper_id(r.get("doi"), r.get("arxiv_id"), title),
                title=title,
                abstract=_clean(r.get("abstract")),
                year=int(year) if year else None,
                publication_date=r.get("publication_date"),
                venue=r.get("venue") or r.get("journal"),
                doi=r.get("doi"),
                url=r.get("url"),
                authors=authors,
                source=r.get("source", f"file:{path.name}"),
                work_type=r.get("work_type") or r.get("type"),
            )
        )
    return papers


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class SearchStats:
    fetched: int = 0
    duplicates: int = 0
    reviews_removed: int = 0
    off_topic_removed: int = 0
    already_known: int = 0
    errors: list[str] = field(default_factory=list)


def filter_and_dedupe(
    papers: list[Paper], known_ids: set[str] = frozenset(), stats: SearchStats | None = None
) -> list[Paper]:
    stats = stats or SearchStats()
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out = []
    for p in papers:
        key = normalize_title(p.title)
        if p.id in seen_ids or key in seen_titles:
            stats.duplicates += 1
            continue
        seen_ids.add(p.id)
        seen_titles.add(key)
        if p.id in known_ids:
            stats.already_known += 1
            continue
        if is_probably_review(p.title, p.abstract, p.work_type):
            stats.reviews_removed += 1
            continue
        if not p.abstract or not is_sei_relevant(p.title, p.abstract):
            stats.off_topic_removed += 1
            continue
        out.append(p)
    return out


def search_papers(
    *,
    queries: tuple[str, ...] | list[str] = DEFAULT_QUERIES,
    from_date: str | None = None,
    per_query: int = 25,
    sources: tuple[str, ...] = ("openalex", "arxiv"),
    mailto: str | None = None,
    known_ids: set[str] = frozenset(),
    max_papers: int = 40,
) -> tuple[list[Paper], SearchStats]:
    from_date = from_date or date(date.today().year - 1, 1, 1).isoformat()
    stats = SearchStats()
    http = requests.Session()
    http.headers["User-Agent"] = f"sei-trends/0.1 (mailto:{mailto})" if mailto else "sei-trends/0.1"
    raw: list[Paper] = []
    for q in queries:
        for src in sources:
            try:
                if src == "openalex":
                    got = search_openalex(q, from_date=from_date, limit=per_query, mailto=mailto, session=http)
                elif src == "arxiv":
                    got = search_arxiv(q, from_date=from_date, limit=per_query, session=http)
                else:
                    raise ValueError(f"unknown source {src!r}")
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                msg = f"{src} query {q!r} failed: {exc}"
                log.warning(msg)
                stats.errors.append(msg)
                continue
            stats.fetched += len(got)
            raw.extend(got)
    kept = filter_and_dedupe(raw, known_ids, stats)
    # Newest first, then most cited, so a capped run still sees the frontier.
    kept.sort(key=lambda p: (p.publication_date or str(p.year or ""), p.cited_by or 0), reverse=True)
    return kept[:max_papers], stats
