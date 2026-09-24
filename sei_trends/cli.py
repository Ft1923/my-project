"""Command-line entry point.

    python -m sei_trends run                      # search -> analyse -> model -> report
    python -m sei_trends run --import papers.csv  # also analyse papers from a local export
    python -m sei_trends run --no-search          # re-run the model on the existing knowledge base
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from .analyze import analyze_papers
from .llm import DEFAULT_MODEL, ClaudeClient
from .report import render_report
from .search import DEFAULT_QUERIES, SearchStats, filter_and_dedupe, load_papers_file, search_papers
from .store import KnowledgeBase
from .trend_model import ModelParams, compute_trends, synthesize_outlook

log = logging.getLogger("sei_trends")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sei-trends", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the full pipeline once")
    run.add_argument("--data-dir", type=Path, default=Path("data"), help="knowledge base directory (default: data)")
    run.add_argument("--from-date", default=None, help="earliest publication date YYYY-MM-DD (default: Jan 1 last year)")
    run.add_argument("--max-papers", type=int, default=40, help="max NEW papers to analyse this run (default: 40)")
    run.add_argument("--per-query", type=int, default=25, help="results requested per query per source")
    run.add_argument("--queries-file", type=Path, help="text file, one search query per line")
    run.add_argument("--sources", default="openalex,arxiv", help="comma-separated: openalex,arxiv")
    run.add_argument("--mailto", help="contact email for the OpenAlex polite pool")
    run.add_argument("--import", dest="import_files", type=Path, action="append", default=[],
                     help="also analyse papers from a .csv/.json/.jsonl export (repeatable)")
    run.add_argument("--no-search", action="store_true", help="skip online search")
    run.add_argument("--no-synthesis", action="store_true", help="skip the Claude outlook (scores only)")
    run.add_argument("--lang", default="zh", choices=["zh", "en"], help="output language (default: zh)")
    run.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    run.add_argument("--analysis-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    run.add_argument("--synthesis-effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    run.add_argument("--workers", type=int, default=4, help="concurrent per-paper analyses")
    run.add_argument("--half-life", type=float, default=ModelParams.half_life_years,
                     help="recency half-life in years for weighting papers")
    run.add_argument("-v", "--verbose", action="store_true")
    return ap


def cmd_run(args: argparse.Namespace) -> int:
    kb = KnowledgeBase(args.data_dir)
    known = kb.known_ids()

    # 1. Collect candidate papers.
    candidates = []
    stats: SearchStats | None = None
    if not args.no_search:
        queries = DEFAULT_QUERIES
        if args.queries_file:
            queries = tuple(q.strip() for q in args.queries_file.read_text(encoding="utf-8").splitlines() if q.strip())
        log.info("searching %d queries on %s ...", len(queries), args.sources)
        candidates, stats = search_papers(
            queries=queries,
            from_date=args.from_date,
            per_query=args.per_query,
            sources=tuple(s.strip() for s in args.sources.split(",") if s.strip()),
            mailto=args.mailto,
            known_ids=known,
            max_papers=args.max_papers,
        )
        log.info("search: %d new candidate papers", len(candidates))
    for f in args.import_files:
        imported = filter_and_dedupe(load_papers_file(f), known | {p.id for p in candidates}, stats or SearchStats())
        log.info("imported %d new candidate papers from %s", len(imported), f)
        candidates.extend(imported)

    # 2. Extract highlights / limitations.
    new_items = []
    llm = ClaudeClient(model=args.model) if candidates or not args.no_synthesis else None
    if candidates:
        new_items, rejected = analyze_papers(
            llm, candidates, kb, lang=args.lang, effort=args.analysis_effort, workers=args.workers
        )
        log.info("analysis: %d accepted, %d rejected by the model", len(new_items), len(rejected))

    items = kb.load()
    if not items:
        log.error("knowledge base is empty; nothing to model (check search errors or use --import)")
        if stats and stats.errors:
            for e in stats.errors:
                log.error("  %s", e)
        return 1

    # 3. Trend model + outlook.
    run_dir = kb.new_run_dir()
    prev_scores, prev_outlook = kb.previous_run(exclude=run_dir)
    params = ModelParams(half_life_years=args.half_life)
    snapshot = compute_trends(items, params, date.today(), prev_scores)
    (run_dir / "trend_scores.json").write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    outlook = None
    if not args.no_synthesis:
        log.info("synthesising outlook from %d papers ...", len(items))
        outlook = synthesize_outlook(
            llm, snapshot, items, lang=args.lang, previous_outlook=prev_outlook, effort=args.synthesis_effort
        )
        (run_dir / "outlook.json").write_text(outlook.model_dump_json(indent=2), encoding="utf-8")

    report = render_report(snapshot, outlook, new_items, stats, args.lang)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"report: {run_dir / 'report.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "run":
        return cmd_run(args)
    return 2
