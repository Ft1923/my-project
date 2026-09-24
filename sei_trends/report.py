"""Render a run into Markdown."""

from __future__ import annotations

from .schemas import FutureOutlook
from .search import SearchStats
from .store import AnalyzedPaper
from .trend_model import TrendSnapshot

TOPIC_ZH = {
    "electrolyte_solvation_design": "电解液溶剂化结构设计",
    "electrolyte_additives": "电解液添加剂",
    "artificial_sei_coatings": "人工SEI/界面涂层",
    "sei_composition_structure": "SEI组分与结构",
    "sei_formation_mechanism": "SEI形成机理",
    "ion_transport_kinetics": "离子传输与动力学",
    "sei_mechanics_stability": "SEI力学与稳定性",
    "sei_aging_degradation": "SEI老化与衰减",
    "advanced_characterization": "先进表征",
    "computation_simulation": "计算模拟",
    "machine_learning_data": "机器学习/数据驱动",
    "solid_state_interphases": "固态电池界面",
    "extreme_conditions": "极端工况(低温/高温/快充)",
    "beyond_lithium": "非锂体系(Na/K/Zn等)",
    "practical_cells_scaleup": "实用化电芯与放大",
    "safety_gas_evolution": "安全与产气",
}
CATEGORY_ZH = {
    "mechanism_unclear": "机理不清",
    "characterization_artifacts": "表征局限/假象",
    "lab_scale_only": "仅实验室尺度",
    "insufficient_cycle_life": "循环寿命不足",
    "narrow_operating_window": "工况窗口窄",
    "cost_scalability": "成本/放大",
    "limited_generality": "普适性有限",
    "lacks_quantification": "缺乏定量",
    "model_validation_gap": "模型验证缺失",
    "reproducibility_statistics": "重复性/统计不足",
    "safety_not_assessed": "未评估安全",
    "other": "其他",
}
HORIZON_ZH = {"near_term_1_2y": "近期(1-2年)", "mid_term_3_5y": "中期(3-5年)", "long_term_5y_plus": "长期(5年+)"}


def _t(name: str, lang: str) -> str:
    return f"{TOPIC_ZH.get(name, name)} (`{name}`)" if lang == "zh" else f"`{name}`"


def _c(name: str, lang: str) -> str:
    return CATEGORY_ZH.get(name, name) if lang == "zh" else name


def render_report(
    snapshot: TrendSnapshot,
    outlook: FutureOutlook | None,
    new_items: list[AnalyzedPaper],
    search_stats: SearchStats | None,
    lang: str = "zh",
) -> str:
    zh = lang == "zh"
    L = []
    L.append("# SEI 研究趋势报告" if zh else "# SEI Research Trend Report")
    L.append("")
    L.append(
        (f"生成日期 {snapshot.reference_date} · 知识库论文 {snapshot.n_papers} 篇(本次新增 {len(new_items)} 篇)"
         f" · 年份 {snapshot.year_range[0]}–{snapshot.year_range[1]} · 动量分割日期 {snapshot.split_date}")
        if zh
        else (f"Generated {snapshot.reference_date} · {snapshot.n_papers} papers in knowledge base "
              f"({len(new_items)} new) · years {snapshot.year_range[0]}–{snapshot.year_range[1]} "
              f"· momentum split {snapshot.split_date}")
    )
    if search_stats:
        L.append("")
        L.append(
            (f"检索: 获取 {search_stats.fetched} 条, 去重 {search_stats.duplicates}, 剔除综述 "
             f"{search_stats.reviews_removed}, 剔除非SEI {search_stats.off_topic_removed}, 已分析过 "
             f"{search_stats.already_known}")
            if zh
            else (f"Search: fetched {search_stats.fetched}, duplicates {search_stats.duplicates}, reviews removed "
                  f"{search_stats.reviews_removed}, off-topic {search_stats.off_topic_removed}, already known "
                  f"{search_stats.already_known}")
        )
        for err in search_stats.errors:
            L.append(f"- ⚠️ {err}")

    if outlook:
        L += ["", "## 1. 结论摘要" if zh else "## 1. Executive summary", "", outlook.executive_summary, ""]
        L += ["**领域现状:** " if zh else "**State of the field:** ", outlook.field_state, ""]
        if outlook.changes_since_last_run:
            L += ["**相比上次运行的变化:** " if zh else "**Changes since last run:** ", outlook.changes_since_last_run, ""]
        L += ["## 2. 未来研究重点" if zh else "## 2. Future research priorities", ""]
        for p in sorted(outlook.priorities, key=lambda p: p.rank):
            horizon = HORIZON_ZH.get(p.time_horizon, p.time_horizon) if zh else p.time_horizon
            L.append(f"### {p.rank}. {p.title}")
            L.append("")
            L.append(f"*{horizon} · {'置信度' if zh else 'confidence'}: {p.confidence} · "
                     + ", ".join(_t(t, lang) for t in p.related_topics) + "*")
            L += ["", p.rationale, ""]
            for label_zh, label_en, values in (
                ("填补的空白", "Gaps addressed", p.gaps_addressed),
                ("建议方法", "Suggested approaches", p.suggested_approaches),
                ("关键科学问题", "Key questions", p.key_questions),
            ):
                if values:
                    L.append(f"**{label_zh if zh else label_en}:**")
                    L += [f"- {v}" for v in values]
                    L.append("")
            if p.evidence_paper_ids:
                L.append(("**证据论文:** " if zh else "**Evidence:** ") + ", ".join(f"`{i}`" for i in p.evidence_paper_ids))
                L.append("")
        for title_zh, title_en, values in (
            ("新兴信号", "Emerging signals", outlook.emerging_signals),
            ("趋于饱和/降温的方向", "Declining or saturated", outlook.declining_or_saturated),
            ("研究方法与报告规范建议", "Methodological recommendations", outlook.methodological_recommendations),
        ):
            if values:
                L += [f"### {title_zh if zh else title_en}", ""] + [f"- {v}" for v in values] + [""]

    L += ["", "## 3. 趋势模型打分" if zh else "## 3. Trend model scores", ""]
    L.append("| 主题 | 论文数 | 优先级 | 限制压力 | 开放度 | 动量 | 实用化缺口 | 较上次 |" if zh
             else "| Topic | Papers | Priority | Pressure | Openness | Momentum | Practicality gap | Δ last run |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in snapshot.topics:
        delta = "" if s.delta_vs_last_run is None else f"{s.delta_vs_last_run:+.3f}"
        flag = " ⚠️" if s.low_support else ""
        L.append(f"| {_t(s.topic, lang)}{flag} | {s.n_papers} | {s.priority:.3f} | {s.limitation_pressure:.2f} | "
                 f"{s.openness:.2f} | {s.momentum:+.2f} | {s.practicality_gap:.2f} | {delta} |")
    L.append("")
    L.append("⚠️ = 样本不足, 分数仅供参考" if zh else "⚠️ = low support, treat score with caution")

    L += ["", "### 主要研究空白 (主题 × 不足类型)" if zh else "### Top gap cells (topic × limitation category)", ""]
    for c in snapshot.gap_cells:
        L.append(f"- **{_t(c.topic, lang)} × {_c(c.category, lang)}** — "
                 f"{'压力' if zh else 'pressure'} {c.pressure:.2f}, {c.n_papers} {'篇' if zh else 'papers'}")
        for e in c.examples[:3]:
            L.append(f"  - [{e['severity']}] {e['point']} (`{e['paper_id']}`)")

    L += ["", "### 共性不足类型" if zh else "### Cross-cutting limitation categories", ""]
    for c in snapshot.limitation_categories:
        L.append(f"- {_c(c['category'], lang)}: {'压力' if zh else 'pressure'} {c['pressure']:.2f}, "
                 f"{'涉及论文比例' if zh else 'paper share'} {c['paper_share']:.0%}")
    if snapshot.rising_methods:
        L += ["", "### 上升中的方法" if zh else "### Rising methods", ""]
        L += [f"- {m['method']}: {m['earlier']} → {m['recent']}" for m in snapshot.rising_methods]

    L += ["", "## 4. 本次新增论文的亮点与不足" if zh else "## 4. Highlights and limitations of new papers", ""]
    for it in new_items or []:
        p, a = it.paper, it.analysis
        link = f" [{p.doi or 'link'}]({p.url})" if p.url else ""
        L.append(f"### {p.title}")
        L.append(f"*{p.venue or ''} {p.year or ''}*{link} · `{p.id}`")
        L += ["", f"**{'核心发现' if zh else 'Key finding'}:** {a.key_finding}"]
        if a.key_metrics:
            L.append(f"**{'关键指标' if zh else 'Metrics'}:** {a.key_metrics}")
        L.append("")
        L.append(f"**{'亮点' if zh else 'Highlights'}:**")
        L += [f"- {h.point}" for h in a.highlights]
        L.append(f"**{'不足' if zh else 'Limitations'}:**")
        L += [f"- [{lim.severity}{'·推断' if zh and lim.inferred else ('·inferred' if lim.inferred else '')}] "
              f"{lim.point}" for lim in a.limitations]
        L.append("")
    return "\n".join(L).rstrip() + "\n"
