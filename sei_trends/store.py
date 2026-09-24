"""On-disk knowledge base. Every run appends newly analysed papers, so the trend
model sees a growing corpus and never pays to re-analyse a paper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .schemas import FutureOutlook, Paper, PaperAnalysis


class AnalyzedPaper(BaseModel):
    paper: Paper
    analysis: PaperAnalysis
    analyzed_at: str
    model: str


@dataclass
class KnowledgeBase:
    root: Path

    @property
    def analyses_path(self) -> Path:
        return self.root / "analyses.jsonl"

    @property
    def rejected_path(self) -> Path:
        return self.root / "rejected.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def load(self) -> list[AnalyzedPaper]:
        if not self.analyses_path.exists():
            return []
        items: dict[str, AnalyzedPaper] = {}
        for line in self.analyses_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = AnalyzedPaper.model_validate_json(line)
                items[item.paper.id] = item  # later lines win
        return list(items.values())

    def known_ids(self) -> set[str]:
        ids = {a.paper.id for a in self.load()}
        if self.rejected_path.exists():
            for line in self.rejected_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ids.add(json.loads(line)["id"])
        return ids

    def add(self, items: list[AnalyzedPaper]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.analyses_path.open("a", encoding="utf-8") as f:
            for item in items:
                f.write(item.model_dump_json() + "\n")

    def add_rejected(self, paper: Paper, reason: str) -> None:
        """Papers Claude judged to be reviews / off-topic, so later runs skip them."""
        self.root.mkdir(parents=True, exist_ok=True)
        with self.rejected_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": paper.id, "title": paper.title, "reason": reason}, ensure_ascii=False) + "\n")

    def new_run_dir(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.runs_dir / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def previous_run(self, exclude: Path | None = None) -> tuple[dict | None, FutureOutlook | None]:
        """Latest earlier run's (trend_scores, outlook), for run-over-run comparison."""
        if not self.runs_dir.exists():
            return None, None
        for run in sorted(self.runs_dir.iterdir(), reverse=True):
            if run == exclude or not (run / "trend_scores.json").exists():
                continue
            scores = json.loads((run / "trend_scores.json").read_text(encoding="utf-8"))
            outlook_path = run / "outlook.json"
            outlook = (
                FutureOutlook.model_validate_json(outlook_path.read_text(encoding="utf-8"))
                if outlook_path.exists()
                else None
            )
            return scores, outlook
        return None, None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
