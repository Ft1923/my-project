# SEI 研究趋势模型 (sei-trends)

每次运行都会:

1. **检索**最新的电池 SEI(固体电解质界面膜)研究论文 —— OpenAlex + arXiv,**自动剔除综述**;
2. 用 Claude 逐篇**提取亮点与不足**(结构化输出:主题、不足类型、严重程度、是否在实用条件下测试……);
3. 把这些结构化结果作为参数输入**趋势模型**,对各研究主题和“主题 × 不足类型”空白打分;
4. 由 Claude 基于模型打分和论文证据,输出**未来该领域的研究重点**(排序、理由、建议方法、证据论文)。

每次新分析的论文都会存入本地知识库 `data/analyses.jsonl`,下次运行只分析新论文,模型基于不断增长的语料更新,并与上一次结果对比变化。

```
检索(OpenAlex/arXiv/本地导入)
   │  去重 · 规则剔除综述 · 剔除非SEI
   ▼
逐篇分析 (Claude, 结构化输出)  ──► 亮点[] / 不足[](类型·主题·严重度) / 实用化条件 / 方法
   │  LLM 二次判定综述/无关 → 记入 rejected.jsonl
   ▼
知识库 data/analyses.jsonl (跨运行累积)
   ▼
趋势模型 (确定性打分)  ──► 主题优先级 · 研究空白矩阵 · 共性不足 · 上升方法 · 与上次对比
   ▼
前景综合 (Claude)       ──► 未来研究重点 (report.md / outlook.json)
```

## 安装

```bash
pip install -r requirements.txt        # 或: pip install -e .[dev]
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使用

```bash
# 完整运行: 检索 2025-01-01 以来的论文, 最多分析 40 篇新论文
python -m sei_trends run --from-date 2025-01-01 --max-papers 40 --mailto you@example.com

# 从 Web of Science(制表符分隔 .txt)/ Scopus(.csv)导出文件导入, 或自制 csv(需含 Title, Abstract 列)
python -m sei_trends run --no-search --import my_export.csv

# 不检索, 仅用已有知识库重新运行模型
python -m sei_trends run --no-search

# 只输出定量打分, 不调用 Claude 生成前景(已有知识库时可用)
python -m sei_trends run --no-search --no-synthesis

# 自定义检索词(每行一条)、英文输出
python -m sei_trends run --queries-file queries.txt --lang en
```

每次运行的结果在 `data/runs/<时间戳>/`:

| 文件 | 内容 |
|---|---|
| `report.md` | 完整报告: 结论摘要、未来研究重点、模型打分表、研究空白、新增论文亮点与不足 |
| `outlook.json` | 未来研究重点(结构化) |
| `trend_scores.json` | 趋势模型全部打分,下次运行用于对比 |

想要“每次”自动运行,可以用 cron 定时,例如每周一早上:

```cron
0 8 * * 1 cd /path/to/my-project && python -m sei_trends run --mailto you@example.com >> data/cron.log 2>&1
```

## 趋势模型怎么算

每篇论文被 Claude 转成结构化参数(见 `sei_trends/schemas.py`):

- `highlights[]`:每条带 `topic`(16 个固定主题之一,如电解液溶剂化设计、人工 SEI、先进表征、机器学习……)
- `limitations[]`:每条带 `topic`、`category`(机理不清 / 仅实验室尺度 / 表征局限 / 模型验证缺失 / 工况窗口窄 ……)、`severity`(minor/moderate/major)、`inferred`(是作者承认的还是审稿视角推断的)
- `practical_conditions_tested`:是否在软包、贫液、高载量等实用条件下验证

对每个主题,模型计算(均按时间衰减加权,默认半衰期 2 年):

| 指标 | 含义 |
|---|---|
| 限制压力 (pressure) | Σ 不足 × 严重度权重(1/2/3) × 时间权重;推断出的不足 × 0.7 |
| 开放度 (openness) | 压力 / (压力 + 亮点);越接近 1 说明问题产生得比解决得快 |
| 动量 (momentum) | 该主题在较新一半论文中的占比 vs 较早一半的对数比 |
| 实用化缺口 | 该主题中未在实用条件下测试的论文比例 |
| 活跃度 | 时间加权论文数 |

**优先级 = 0.30·压力 + 0.20·开放度 + 0.20·动量 + 0.15·实用化缺口 + 0.15·活跃度**(权重在 `ModelParams` 中可调)。
同时统计“主题 × 不足类型”空白矩阵中压力最高的格子,以及上升中的研究方法。
最后 Claude 读取这些打分、空白格子背后的原文不足和论文列表,输出排序后的研究重点,每条都要引用知识库中的论文 ID 作为证据。

## 综述如何剔除

三层过滤:
1. OpenAlex 只取 `type:article|preprint`(排除 review 类型);arXiv 看 comment 中是否标注 review;
2. 规则:标题含 review / perspective / progress in / recent advances / challenges and opportunities / roadmap 等,或摘要开头含 “In this review / we summarize” 等;
3. Claude 逐篇判定 `is_original_research`,判为综述或与 SEI 无关的论文记入 `rejected.jsonl`,以后不再处理。

## 注意事项

- 默认模型 `claude-opus-5`(`--model` 可改),开启自适应思考;逐篇分析用 `medium` effort,前景综合用 `high`(`--analysis-effort` / `--synthesis-effort` 可调)。已启用服务器端 refusal fallback(`fallbacks: "default"`)。
- 分析只基于**标题+摘要**。不足中的 `inferred=true` 条目是根据摘要未提及的内容推断的,报告中标为“推断”,请结合全文判断。
- 论文较少时(如首次运行只有十几篇),分数波动大,表中标 ⚠️ 的主题样本不足。多运行几次、放宽 `--from-date` 可让模型更稳定。
- OpenAlex 建议用 `--mailto` 填写邮箱以进入 polite pool,速率限制更宽松。

## 测试

```bash
pip install pytest && python -m pytest
```

测试使用合成数据并模拟检索与 Claude 调用,不需要网络或 API key。
