"""Step 3: the trend model.

Two stages:

1. `compute_trends` — a transparent, deterministic scoring model. Each paper's
   extracted highlights/limitations are the input parameters; they are weighted
   by recency and severity and aggregated per topic and per (topic x limitation
   category) "gap cell". A topic's priority rises when it has many severe,
   unresolved limitations, is gaining share of recent papers, and is rarely
   tested under practical conditions.

2. `synthesize_outlook` — Claude reads the scores, the top gap cells (with the
   limitation texts and paper IDs behind them) and the condensed paper list, and
   writes the ranked future research priorities.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date

from .llm import ClaudeClient
from .schemas import LIMITATION_CATEGORIES, TOPICS, FutureOutlook
from .store import AnalyzedPaper

SEVERITY_WEIGHT = {"minor": 1.0, "moderate": 2.0, "major": 3.0}
INFERRED_DISCOUNT = 0.7  # limitations inferred by the reader count a bit less than author-stated ones


@dataclass
class ModelParams:
    half_life_years: float = 2.0
    w_pressure: float = 0.30  # severity-weighted unresolved limitations
    w_openness: float = 0.20  # limitations relative to highlights
    w_momentum: float = 0.20  # growth in share of recent papers
    w_practicality: float = 0.15  # share of papers not tested under practical conditions
    w_activity: float = 0.15  # recency-weighted paper volume
    min_support: int = 2  # topics with fewer papers are flagged low-confidence
    top_gap_cells: int = 12


@dataclass
class TopicScore:
    topic: str
    n_papers: int
    activity: float
    limitation_pressure: float
    highlight_mass: float
    openness: float
    momentum: float
    practicality_gap: float
    priority: float
    low_support: bool
    delta_vs_last_run: float | None = None


@dataclass
class GapCell:
    topic: str
    category: str
    pressure: float
    n_papers: int
    examples: list[dict] = field(default_factory=list)  # {"paper_id", "point", "severity"}


@dataclass
class TrendSnapshot:
    reference_date: str
    n_papers: int
    year_range: tuple[int | None, int | None]
    split_date: str
    topics: list[TopicScore]
    gap_cells: list[GapCell]
    limitation_categories: list[dict]
    rising_methods: list[dict]
    systems: dict[str, int]
    params: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _paper_date(item: AnalyzedPaper) -> date:
    p = item.paper
    if p.publication_date:
        try:
            return date.fromisoformat(p.publication_date[:10])
        except ValueError:
            pass
    return date(p.year, 7, 1) if p.year else date.today()


def _recency_weight(d: date, ref: date, half_life_years: float) -> float:
    age_years = max((ref - d).days, 0) / 365.25
    return 0.5 ** (age_years / half_life_years)


def _norm(values: dict[str, float]) -> dict[str, float]:
    hi = max(values.values(), default=0.0)
    return {k: (v / hi if hi > 0 else 0.0) for k, v in values.items()}


def _paper_topics(item: AnalyzedPaper) -> set[str]:
    a = item.analysis
    return set(a.topics) | {h.topic for h in a.highlights} | {lim.topic for lim in a.limitations}


def compute_trends(
    items: list[AnalyzedPaper],
    params: ModelParams | None = None,
    reference_date: date | None = None,
    previous_scores: dict | None = None,
) -> TrendSnapshot:
    params = params or ModelParams()
    ref = reference_date or date.today()
    dates = {it.paper.id: _paper_date(it) for it in items}
    weights = {pid: _recency_weight(d, ref, params.half_life_years) for pid, d in dates.items()}

    # Split the corpus at its median date to measure momentum (share of recent vs. earlier papers).
    # Using the median keeps both halves populated regardless of how wide the search window was.
    sorted_dates = sorted(dates.values())
    split = sorted_dates[len(sorted_dates) // 2] if sorted_dates else ref
    recent_ids = {pid for pid, d in dates.items() if d >= split}
    early_ids = set(dates) - recent_ids

    activity: dict[str, float] = defaultdict(float)
    pressure: dict[str, float] = defaultdict(float)
    highlight_mass: dict[str, float] = defaultdict(float)
    impractical: dict[str, float] = defaultdict(float)
    n_papers: Counter[str] = Counter()
    n_recent: Counter[str] = Counter()
    n_early: Counter[str] = Counter()
    cells: dict[tuple[str, str], GapCell] = {}
    cell_papers: dict[tuple[str, str], set[str]] = defaultdict(set)
    cat_pressure: dict[str, float] = defaultdict(float)
    cat_papers: dict[str, set[str]] = defaultdict(set)
    methods_recent: Counter[str] = Counter()
    methods_early: Counter[str] = Counter()
    systems: Counter[str] = Counter()

    for it in items:
        pid, a = it.paper.id, it.analysis
        w = weights[pid]
        topics = _paper_topics(it)
        for t in topics:
            n_papers[t] += 1
            activity[t] += w
            (n_recent if pid in recent_ids else n_early)[t] += 1
            if not a.practical_conditions_tested:
                impractical[t] += w
        for h in a.highlights:
            highlight_mass[h.topic] += w
        for lim in a.limitations:
            s = SEVERITY_WEIGHT[lim.severity] * w * (INFERRED_DISCOUNT if lim.inferred else 1.0)
            pressure[lim.topic] += s
            cat_pressure[lim.category] += s
            cat_papers[lim.category].add(pid)
            key = (lim.topic, lim.category)
            cell = cells.setdefault(key, GapCell(topic=lim.topic, category=lim.category, pressure=0.0, n_papers=0))
            cell.pressure += s
            cell_papers[key].add(pid)
            cell.examples.append({"paper_id": pid, "point": lim.point, "severity": lim.severity})
        for m in {m.strip().lower() for m in a.methods if m.strip()}:
            (methods_recent if pid in recent_ids else methods_early)[m] += 1
        systems.update(set(a.battery_systems))

    total_recent, total_early = max(len(recent_ids), 1), max(len(early_ids), 1)
    momentum: dict[str, float] = {}
    for t in TOPICS:
        # Laplace-smoothed log ratio of topic share in recent vs. earlier papers.
        share_r = (n_recent[t] + 0.5) / (total_recent + 1)
        share_e = (n_early[t] + 0.5) / (total_early + 1)
        momentum[t] = math.log(share_r / share_e) if early_ids else 0.0

    pressure_n = _norm({t: pressure[t] for t in TOPICS})
    activity_n = _norm({t: activity[t] for t in TOPICS})
    mom_hi = max((abs(v) for v in momentum.values()), default=0.0) or 1.0

    scores = []
    prev = {s["topic"]: s["priority"] for s in (previous_scores or {}).get("topics", [])}
    for t in TOPICS:
        if n_papers[t] == 0:
            continue
        openness = pressure[t] / (pressure[t] + highlight_mass[t]) if (pressure[t] + highlight_mass[t]) else 0.0
        practicality_gap = impractical[t] / activity[t] if activity[t] else 0.0
        mom_n = 0.5 + 0.5 * momentum[t] / mom_hi  # map [-hi, hi] -> [0, 1]
        priority = (
            params.w_pressure * pressure_n[t]
            + params.w_openness * openness
            + params.w_momentum * mom_n
            + params.w_practicality * practicality_gap
            + params.w_activity * activity_n[t]
        )
        scores.append(
            TopicScore(
                topic=t,
                n_papers=n_papers[t],
                activity=round(activity[t], 3),
                limitation_pressure=round(pressure[t], 3),
                highlight_mass=round(highlight_mass[t], 3),
                openness=round(openness, 3),
                momentum=round(momentum[t], 3),
                practicality_gap=round(practicality_gap, 3),
                priority=round(priority, 4),
                low_support=n_papers[t] < params.min_support,
                delta_vs_last_run=round(priority - prev[t], 4) if t in prev else None,
            )
        )
    scores.sort(key=lambda s: (s.low_support, -s.priority))

    for key, cell in cells.items():
        cell.n_papers = len(cell_papers[key])
        cell.pressure = round(cell.pressure, 3)
        order = {"major": 0, "moderate": 1, "minor": 2}
        cell.examples = sorted(cell.examples, key=lambda e: order[e["severity"]])[:5]
    gap_cells = sorted(cells.values(), key=lambda c: -c.pressure)[: params.top_gap_cells]

    n = max(len(items), 1)
    categories = sorted(
        (
            {"category": c, "pressure": round(cat_pressure[c], 3), "paper_share": round(len(cat_papers[c]) / n, 3)}
            for c in LIMITATION_CATEGORIES
            if cat_pressure[c] > 0
        ),
        key=lambda d: -d["pressure"],
    )

    rising = []
    for m, r in methods_recent.items():
        e = methods_early.get(m, 0)
        if r >= 2 and r > e:
            rising.append({"method": m, "recent": r, "earlier": e})
    rising.sort(key=lambda d: (-(d["recent"] - d["earlier"]), -d["recent"]))

    years = [it.paper.year for it in items if it.paper.year]
    return TrendSnapshot(
        reference_date=ref.isoformat(),
        n_papers=len(items),
        year_range=(min(years, default=None), max(years, default=None)),
        split_date=split.isoformat(),
        topics=scores,
        gap_cells=gap_cells,
        limitation_categories=categories,
        rising_methods=rising[:15],
        systems=dict(systems.most_common()),
        params=asdict(params),
    )


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM = """\
You are a senior battery scientist writing a forward-looking research agenda on the solid electrolyte
interphase (SEI). You are given the output of a quantitative trend model built from critical readings of
recent original research papers (reviews were excluded), plus condensed per-paper highlights and limitations.

How to read the model output:
- priority: composite score (limitation pressure, openness, momentum, practicality gap, activity).
- limitation_pressure: recency- and severity-weighted count of unresolved limitations in that topic.
- openness: pressure / (pressure + highlights); near 1 means the topic is producing problems faster than solutions.
- momentum: log ratio of the topic's share in the more recent half of the corpus vs. the earlier half.
- practicality_gap: share of papers in that topic never tested under practical cell conditions.
- gap cells: (topic x limitation category) combinations with the most pressure, with the underlying limitation
  statements and paper IDs.
- low_support topics have too few papers to trust their scores.

Your task: derive 5-8 ranked research priorities for the next years. Each priority must
- follow from the evidence: cite the paper IDs whose limitations or highlights motivate it (evidence_paper_ids
  must be IDs that appear in the input);
- name concrete gaps it closes and concrete approaches (techniques, protocols, cell formats, metrics);
- not simply restate a topic name: combine signals (e.g. a rising method + a persistent limitation category).
Use the scores as a guide, not a mandate: you may re-rank when the paper evidence clearly justifies it, and say
so in the rationale. Distinguish genuine scientific gaps from reporting gaps (e.g. missing lean-electrolyte data).
If a previous outlook is provided, explain in changes_since_last_run what moved and why; otherwise leave it ''.
Write all free-text fields in {lang}."""


def _condensed_papers(items: list[AnalyzedPaper], limit: int) -> list[dict]:
    items = sorted(items, key=_paper_date, reverse=True)[:limit]
    return [
        {
            "id": it.paper.id,
            "year": it.paper.year,
            "title": it.paper.title,
            "systems": it.analysis.battery_systems,
            "finding": it.analysis.key_finding,
            "highlights": [h.point for h in it.analysis.highlights],
            "limitations": [f"[{lim.severity}/{lim.category}] {lim.point}" for lim in it.analysis.limitations],
            "practical": it.analysis.practical_conditions_tested,
        }
        for it in items
    ]


def synthesize_outlook(
    llm: ClaudeClient,
    snapshot: TrendSnapshot,
    items: list[AnalyzedPaper],
    *,
    lang: str = "zh",
    previous_outlook: FutureOutlook | None = None,
    max_papers_in_prompt: int = 300,
    effort: str = "high",
) -> FutureOutlook:
    from .analyze import LANG_NAMES

    payload = {
        "trend_model": snapshot.to_dict(),
        "papers": _condensed_papers(items, max_papers_in_prompt),
    }
    prompt = (
        "<trend_model_and_papers>\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + "\n</trend_model_and_papers>\n"
    )
    if previous_outlook is not None:
        prompt += (
            "\n<previous_outlook>\n"
            + previous_outlook.model_dump_json(include={"executive_summary", "priorities"})
            + "\n</previous_outlook>\n"
        )
    prompt += "\nProduce the research outlook."
    return llm.structured(
        system=SYNTHESIS_SYSTEM.format(lang=LANG_NAMES.get(lang, lang)),
        prompt=prompt,
        output_type=FutureOutlook,
        effort=effort,
        max_tokens=32000,
    )
