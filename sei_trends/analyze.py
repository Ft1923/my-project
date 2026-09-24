"""Step 2: extract highlights and limitations from each paper with Claude."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from .llm import ClaudeClient, LLMError
from .schemas import Paper, PaperAnalysis
from .store import AnalyzedPaper, KnowledgeBase, now_iso

log = logging.getLogger(__name__)

ANALYSIS_SYSTEM = """\
You are a battery-interface scientist auditing research papers on the solid electrolyte interphase (SEI).
For each paper you receive its metadata and abstract, and you produce a structured critical assessment.

How to judge:
- is_original_research: false for reviews, perspectives, tutorials, roadmaps, editorials, meta-analyses.
  A paper that reports new experiments, simulations, or datasets is original even if its intro surveys the field.
- sei_relevance: "core" if the SEI (or an anode-side interphase in Li/Na/K/Zn/solid-state cells) is the main
  object of study; "partial" if SEI is one factor among several; "none" otherwise (e.g. purely cathode/CEI).
- highlights: the genuinely new contributions (design idea, mechanism, technique, metric), 1-4 items,
  quoting numbers from the abstract when present. Do not restate generic motivation.
- limitations: 2-5 items. Include what the authors concede and what a careful reviewer would flag from what
  the abstract omits (set inferred=true for those). Typical gaps: coin cells with thick Li / flooded
  electrolyte, no lean-electrolyte or high-loading test, ex situ characterization only, correlation claimed
  as mechanism, single chemistry, short cycling, narrow temperature/rate window, no cost assessment,
  simulations without experimental validation. Be specific to this paper; do not pad with boilerplate.
- severity: "major" if it could overturn the main claim or blocks practical use; "moderate" if it limits
  generality; "minor" otherwise.
- Only use information in the provided text. If the abstract is too thin to judge something, say so in the
  limitation rather than guessing numbers.
Write all free-text fields in {lang}."""


def _paper_prompt(p: Paper) -> str:
    meta = [
        f"ID: {p.id}",
        f"Title: {p.title}",
        f"Year: {p.year or 'unknown'}",
        f"Venue: {p.venue or 'unknown'}",
        f"Source type: {p.work_type or 'unknown'}",
    ]
    return "\n".join(meta) + f"\n\nAbstract:\n{p.abstract or '(no abstract available)'}"


LANG_NAMES = {"zh": "Simplified Chinese", "en": "English"}


def analyze_paper(llm: ClaudeClient, paper: Paper, lang: str = "zh", effort: str = "medium") -> PaperAnalysis:
    return llm.structured(
        system=ANALYSIS_SYSTEM.format(lang=LANG_NAMES.get(lang, lang)),
        prompt=_paper_prompt(paper),
        output_type=PaperAnalysis,
        effort=effort,
    )


def analyze_papers(
    llm: ClaudeClient,
    papers: list[Paper],
    kb: KnowledgeBase,
    *,
    lang: str = "zh",
    effort: str = "medium",
    workers: int = 4,
) -> tuple[list[AnalyzedPaper], list[tuple[Paper, str]]]:
    """Analyse papers concurrently. Accepted results are persisted to the knowledge base
    as they arrive, so an interrupted run keeps its progress."""
    accepted: list[AnalyzedPaper] = []
    rejected: list[tuple[Paper, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(analyze_paper, llm, p, lang, effort): p for p in papers}
        for i, fut in enumerate(as_completed(futures), 1):
            paper = futures[fut]
            try:
                analysis = fut.result()
            except (LLMError, anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                # Transient API errors are not recorded as rejections, so the paper is retried next run.
                log.warning("[%d/%d] analysis failed for %s: %s", i, len(papers), paper.id, exc)
                continue
            if not analysis.is_original_research:
                reason = "review/non-original (LLM)"
            elif analysis.sei_relevance == "none":
                reason = "not SEI-related (LLM)"
            else:
                item = AnalyzedPaper(paper=paper, analysis=analysis, analyzed_at=now_iso(), model=llm.model)
                kb.add([item])
                accepted.append(item)
                log.info("[%d/%d] analysed: %s", i, len(papers), paper.title[:80])
                continue
            kb.add_rejected(paper, reason)
            rejected.append((paper, reason))
            log.info("[%d/%d] rejected (%s): %s", i, len(papers), reason, paper.title[:80])
    return accepted, rejected
