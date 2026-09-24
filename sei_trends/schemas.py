"""Data models shared by the pipeline.

`Paper` is what search returns. `PaperAnalysis` is Claude's structured
extraction of one paper (the "parameters" fed into the trend model).
`FutureOutlook` is the final model output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Controlled vocabularies. Keeping these closed lets the trend model aggregate
# across papers; free text lives alongside them in `point` fields.
# ---------------------------------------------------------------------------

Topic = Literal[
    "electrolyte_solvation_design",  # solvents, salts, LHCE, solvation structure
    "electrolyte_additives",
    "artificial_sei_coatings",  # ex situ / pre-formed interlayers, polymer/inorganic coatings
    "sei_composition_structure",  # LiF, Li2O, organic/inorganic, mosaic vs. layered
    "sei_formation_mechanism",  # reduction pathways, nucleation, formation protocols
    "ion_transport_kinetics",  # Li+ transport through SEI, desolvation, fast charge
    "sei_mechanics_stability",  # mechanical properties, cracking, volume change
    "sei_aging_degradation",  # growth, calendar aging, capacity fade, dissolution
    "advanced_characterization",  # cryo-EM, operando, XPS, ToF-SIMS, NMR, synchrotron
    "computation_simulation",  # DFT, MD, reactive force fields, continuum models
    "machine_learning_data",  # ML potentials, data-driven screening, autonomous labs
    "solid_state_interphases",  # SSE|anode interphases
    "extreme_conditions",  # low/high temperature, high voltage coupling, fast charge
    "beyond_lithium",  # Na, K, Zn, Mg, Ca interphases
    "practical_cells_scaleup",  # pouch cells, lean electrolyte, formation at scale
    "safety_gas_evolution",
]

LimitationCategory = Literal[
    "mechanism_unclear",  # correlation shown, causality/mechanism not proven
    "characterization_artifacts",  # ex situ only, beam damage, air exposure, surface-only
    "lab_scale_only",  # coin cells, thick Li, flooded electrolyte, low loading
    "insufficient_cycle_life",
    "narrow_operating_window",  # temperature, rate, voltage
    "cost_scalability",
    "limited_generality",  # one chemistry/one condition only
    "lacks_quantification",  # qualitative, no quantitative SEI metrics
    "model_validation_gap",  # simulation not validated experimentally (or vice versa)
    "reproducibility_statistics",  # few cells, no error bars
    "safety_not_assessed",
    "other",
]

BatterySystem = Literal[
    "li_metal",
    "anode_free",
    "graphite",
    "silicon",
    "lithium_sulfur",
    "solid_state",
    "sodium",
    "potassium",
    "zinc",
    "multivalent_other",
    "other",
]

Severity = Literal["minor", "moderate", "major"]

TOPICS: tuple[str, ...] = Topic.__args__  # type: ignore[attr-defined]
LIMITATION_CATEGORIES: tuple[str, ...] = LimitationCategory.__args__  # type: ignore[attr-defined]


class Paper(BaseModel):
    id: str
    title: str
    abstract: str = ""
    year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    authors: list[str] = Field(default_factory=list)
    cited_by: int | None = None
    source: str = "manual"
    work_type: str | None = None  # as reported by the source (article, preprint, review, ...)


# ---------------------------------------------------------------------------
# Claude structured outputs. `extra="forbid"` makes pydantic emit
# additionalProperties: false, which structured outputs requires.
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Highlight(_Strict):
    point: str = Field(description="One concrete innovation or result, with numbers where the abstract gives them.")
    topic: Topic


class Limitation(_Strict):
    point: str = Field(description="One concrete weakness, unresolved question, or untested condition.")
    category: LimitationCategory
    topic: Topic
    severity: Severity
    inferred: bool = Field(
        description="True if not stated by the authors but inferred from what the abstract omits "
        "(e.g. only coin cells, no lean-electrolyte test)."
    )


class PaperAnalysis(_Strict):
    is_original_research: bool = Field(
        description="False for reviews, perspectives, tutorials, roadmaps, editorials, or meta-analyses."
    )
    sei_relevance: Literal["core", "partial", "none"]
    battery_systems: list[BatterySystem]
    topics: list[Topic]
    methods: list[str] = Field(description="Key experimental/computational techniques, short names.")
    key_finding: str = Field(description="One-sentence summary of the main claim.")
    highlights: list[Highlight]
    limitations: list[Limitation]
    practical_conditions_tested: bool = Field(
        description="True only if tested under practically relevant conditions "
        "(e.g. pouch cell, lean electrolyte, high areal loading, thin Li, N/P control)."
    )
    key_metrics: str = Field(description="Headline performance metrics (CE, cycles, rate, temperature), or ''.")


class ResearchPriority(_Strict):
    rank: int
    title: str
    rationale: str = Field(description="Why this matters now, grounded in the trend statistics and paper evidence.")
    gaps_addressed: list[str]
    suggested_approaches: list[str]
    key_questions: list[str]
    evidence_paper_ids: list[str]
    related_topics: list[Topic]
    time_horizon: Literal["near_term_1_2y", "mid_term_3_5y", "long_term_5y_plus"]
    confidence: Literal["low", "medium", "high"]


class FutureOutlook(_Strict):
    executive_summary: str
    field_state: str = Field(description="Where the field stands: what is converging, what is saturating.")
    priorities: list[ResearchPriority]
    emerging_signals: list[str] = Field(description="Weak but rising signals worth watching.")
    declining_or_saturated: list[str]
    methodological_recommendations: list[str] = Field(
        description="Cross-cutting fixes to how SEI studies are done/reported."
    )
    changes_since_last_run: str = Field(description="How the outlook shifted versus the previous run, or ''.")
