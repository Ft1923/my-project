"""Offline tests. All papers and analyses below are synthetic fixtures, not real publications."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from sei_trends import cli
from sei_trends.llm import ClaudeClient, LLMError
from sei_trends.schemas import FutureOutlook, Highlight, Limitation, Paper, PaperAnalysis, ResearchPriority
from sei_trends.search import (
    SearchStats,
    _openalex_abstract,
    filter_and_dedupe,
    is_probably_review,
    load_papers_file,
    make_paper_id,
    parse_arxiv_feed,
)
from sei_trends.store import AnalyzedPaper, KnowledgeBase
from sei_trends.trend_model import ModelParams, compute_trends

# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,abstract,work_type,expected",
    [
        ("Recent advances in SEI engineering for Li metal anodes", "", "article", True),
        ("SEI on silicon: challenges and opportunities", "", "article", True),
        ("A fluorinated additive forms LiF-rich SEI", "In this review, we summarize ...", "article", True),
        ("A fluorinated additive forms LiF-rich SEI", "We design an additive ...", "review", True),
        ("A fluorinated additive forms LiF-rich SEI", "We design an additive that ...", "article", False),
        ("Cryo-EM reveals SEI nanostructure on sodium", "Here we image the SEI ...", "preprint", False),
    ],
)
def test_review_filter(title, abstract, work_type, expected):
    assert is_probably_review(title, abstract, work_type) is expected


def test_openalex_abstract_reconstruction():
    inv = {"SEI": [0, 3], "forms": [1], "fast": [2]}
    assert _openalex_abstract(inv) == "SEI forms fast SEI"


def test_paper_ids():
    assert make_paper_id("https://doi.org/10.1/ABC", None, "x") == "doi:10.1/abc"
    assert make_paper_id(None, "2501.00001v2", "x") == "arxiv:2501.00001"
    assert make_paper_id(None, None, "A Title!") == make_paper_id(None, None, "a title")


ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2601.01234v1</id>
    <published>2026-01-15T00:00:00Z</published>
    <title>Machine-learned potentials for SEI growth</title>
    <summary>We simulate solid electrolyte interphase growth ...</summary>
    <author><name>A. Author</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.05678v1</id>
    <published>2026-01-20T00:00:00Z</published>
    <title>Interphases in batteries</title>
    <summary>A broad look at interphases.</summary>
    <arxiv:comment>Review article, 40 pages</arxiv:comment>
    <author><name>B. Author</name></author>
  </entry>
</feed>"""


def test_arxiv_parse_and_filter():
    papers = parse_arxiv_feed(ARXIV_XML)
    assert [p.id for p in papers] == ["arxiv:2601.01234", "arxiv:2601.05678"]
    assert papers[0].year == 2026
    stats = SearchStats()
    kept = filter_and_dedupe(papers + papers[:1], stats=stats)
    assert [p.id for p in kept] == ["arxiv:2601.01234"]
    assert stats.duplicates == 1 and stats.reviews_removed == 1


def test_filter_drops_off_topic_and_known():
    a = Paper(id="x1", title="Cathode coating", abstract="NMC cathode particles coated with alumina.")
    b = Paper(id="x2", title="SEI on graphite", abstract="The SEI on graphite ...")
    c = Paper(id="x3", title="LiF SEI", abstract="solid electrolyte interphase rich in LiF")
    stats = SearchStats()
    kept = filter_and_dedupe([a, b, c], known_ids={"x3"}, stats=stats)
    assert [p.id for p in kept] == ["x2"]
    assert stats.off_topic_removed == 1 and stats.already_known == 1


def test_load_csv(tmp_path):
    f = tmp_path / "wos.csv"
    f.write_text("Title,Abstract,Year,DOI,Authors\nT1 SEI,abs about SEI,2025,10.1/x,A; B\n", encoding="utf-8")
    [p] = load_papers_file(f)
    assert p.id == "doi:10.1/x" and p.year == 2025 and p.authors == ["A", "B"]


def test_load_wos_tab_export(tmp_path):
    f = tmp_path / "savedrecs.txt"
    f.write_text("PT\tAU\tTI\tSO\tAB\tPY\tDI\tDT\n"
                 "J\tX, Y\tSEI study\tJ. Chem\tabout SEI\t2026\t10.2/y\tReview\n", encoding="utf-8")
    [p] = load_papers_file(f)
    assert (p.title, p.venue, p.year, p.doi, p.work_type) == ("SEI study", "J. Chem", 2026, "10.2/y", "Review")
    assert filter_and_dedupe([p]) == []  # WoS document type "Review" is filtered out


# ---------------------------------------------------------------------------
# trend model
# ---------------------------------------------------------------------------


def _item(pid, pub, topics, lims, highs=(), practical=False, methods=()):
    return AnalyzedPaper(
        paper=Paper(id=pid, title=f"paper {pid}", abstract="SEI", year=int(pub[:4]), publication_date=pub),
        analysis=PaperAnalysis(
            is_original_research=True,
            sei_relevance="core",
            battery_systems=["li_metal"],
            topics=list(topics),
            methods=list(methods),
            key_finding="f",
            highlights=[Highlight(point=f"h-{pid}", topic=t) for t in highs],
            limitations=[
                Limitation(point=f"l-{pid}-{c}", category=c, topic=t, severity=s, inferred=False)
                for t, c, s in lims
            ],
            practical_conditions_tested=practical,
            key_metrics="",
        ),
        analyzed_at="2026-01-01T00:00:00+00:00",
        model="test",
    )


def _corpus():
    return [
        # Early papers: additives, well solved (highlights, few limitations).
        _item("e1", "2024-02-01", ["electrolyte_additives"], [("electrolyte_additives", "other", "minor")],
              highs=["electrolyte_additives"] * 2, practical=True, methods=["XPS"]),
        _item("e2", "2024-05-01", ["electrolyte_additives"], [], highs=["electrolyte_additives"], methods=["XPS"]),
        # Recent papers: ML / characterization rising, with severe open limitations.
        _item("r1", "2026-03-01", ["machine_learning_data", "computation_simulation"],
              [("machine_learning_data", "model_validation_gap", "major"),
               ("machine_learning_data", "lab_scale_only", "moderate")], methods=["ML potential", "cryo-EM"]),
        _item("r2", "2026-04-01", ["machine_learning_data"],
              [("machine_learning_data", "model_validation_gap", "major")], methods=["ML potential", "cryo-EM"]),
        _item("r3", "2026-05-01", ["advanced_characterization"],
              [("advanced_characterization", "characterization_artifacts", "moderate")],
              highs=["advanced_characterization"], methods=["cryo-EM"]),
    ]


def test_trend_model_ranks_open_rising_topic_first():
    snap = compute_trends(_corpus(), ModelParams(), reference_date=date(2026, 6, 1))
    by_topic = {s.topic: s for s in snap.topics}
    assert snap.topics[0].topic == "machine_learning_data"
    ml, add = by_topic["machine_learning_data"], by_topic["electrolyte_additives"]
    assert ml.momentum > 0 > add.momentum
    assert ml.openness == 1.0 and add.openness < 0.5
    assert ml.practicality_gap == 1.0 and add.practicality_gap < 1.0
    assert snap.gap_cells[0].topic == "machine_learning_data"
    assert snap.gap_cells[0].category == "model_validation_gap"
    assert snap.gap_cells[0].n_papers == 2
    assert snap.limitation_categories[0]["category"] == "model_validation_gap"
    assert {m["method"] for m in snap.rising_methods} == {"ml potential", "cryo-em"}
    assert by_topic["computation_simulation"].low_support


def test_trend_model_delta_vs_previous_run():
    first = compute_trends(_corpus(), reference_date=date(2026, 6, 1))
    corpus = _corpus() + [_item("r4", "2026-05-15", ["electrolyte_additives"],
                                [("electrolyte_additives", "mechanism_unclear", "major")])]
    second = compute_trends(corpus, reference_date=date(2026, 6, 1), previous_scores=first.to_dict())
    add = next(s for s in second.topics if s.topic == "electrolyte_additives")
    assert add.delta_vs_last_run is not None and add.delta_vs_last_run > 0
    json.dumps(second.to_dict())  # snapshot must be JSON-serialisable


# ---------------------------------------------------------------------------
# LLM wrapper
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


def _fake_anthropic(response, calls):
    def stream(**kwargs):
        calls.append(kwargs)
        return _FakeStream(response)

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def test_llm_structured_passes_expected_params():
    calls = []
    out = FutureOutlook(executive_summary="s", field_state="f", priorities=[], emerging_signals=[],
                        declining_or_saturated=[], methodological_recommendations=[], changes_since_last_run="")
    client = ClaudeClient(client=_fake_anthropic(SimpleNamespace(stop_reason="end_turn", parsed_output=out), calls))
    assert client.structured(system="s", prompt="p", output_type=FutureOutlook) is out
    kw = calls[0]
    assert kw["model"] == "claude-opus-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_format"] is FutureOutlook
    assert kw["fallbacks"] == "default"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_llm_structured_raises_on_bad_stop(stop_reason):
    client = ClaudeClient(client=_fake_anthropic(SimpleNamespace(stop_reason=stop_reason, parsed_output=None), []))
    with pytest.raises(LLMError):
        client.structured(system="s", prompt="p", output_type=FutureOutlook)


# ---------------------------------------------------------------------------
# end to end (search and Claude both mocked)
# ---------------------------------------------------------------------------


def test_cli_end_to_end(tmp_path, monkeypatch):
    fixtures = [it.paper for it in _corpus()]
    fixtures.append(Paper(id="rev", title="Some SEI paper", abstract="SEI study"))  # LLM will flag as review
    analyses = {it.paper.id: it.analysis for it in _corpus()}

    def fake_search(**kwargs):
        known = kwargs["known_ids"]
        return [p for p in fixtures if p.id not in known], SearchStats(fetched=len(fixtures))

    def fake_structured(self, *, system, prompt, output_type, effort="high", max_tokens=16000):
        if output_type is PaperAnalysis:
            pid = prompt.split("\n", 1)[0].removeprefix("ID: ")
            if pid == "rev":
                return analyses["e1"].model_copy(update={"is_original_research": False})
            return analyses[pid]
        assert "machine_learning_data" in prompt
        return FutureOutlook(
            executive_summary="summary", field_state="state",
            priorities=[ResearchPriority(
                rank=1, title="Validate ML-predicted SEI chemistry", rationale="r", gaps_addressed=["g"],
                suggested_approaches=["a"], key_questions=["q"], evidence_paper_ids=["r1", "r2"],
                related_topics=["machine_learning_data"], time_horizon="near_term_1_2y", confidence="medium")],
            emerging_signals=[], declining_or_saturated=[], methodological_recommendations=[],
            changes_since_last_run="",
        )

    monkeypatch.setattr(cli, "search_papers", fake_search)
    monkeypatch.setattr(ClaudeClient, "__init__", lambda self, model="m", client=None: setattr(self, "model", model))
    monkeypatch.setattr(ClaudeClient, "structured", fake_structured)

    data = tmp_path / "data"
    assert cli.main(["run", "--data-dir", str(data), "--workers", "1"]) == 0
    kb = KnowledgeBase(data)
    assert len(kb.load()) == 5
    assert "rev" in kb.known_ids()
    run = next((data / "runs").iterdir())
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "Validate ML-predicted SEI chemistry" in report
    assert "机器学习" in report

    # Second run: nothing new to analyse, outlook still produced and deltas recorded.
    monkeypatch.setattr("sei_trends.store.datetime", _LaterDatetime)
    assert cli.main(["run", "--data-dir", str(data)]) == 0
    runs = sorted((data / "runs").iterdir())
    assert len(runs) == 2
    scores = json.loads((runs[-1] / "trend_scores.json").read_text(encoding="utf-8"))
    assert all(s["delta_vs_last_run"] is not None for s in scores["topics"])


class _LaterDatetime:
    """Makes the second run's directory name sort after the first."""

    @staticmethod
    def now(tz=None):
        from datetime import datetime, timedelta

        return datetime.now(tz) + timedelta(hours=1)
