---
name: paper-reading
description: 精读或速读一篇科研论文（尤其是电池 / SEI / 电解液 / 界面方向），产出结构化读书笔记：研究问题、核心结论、声明-证据对照、方法与实验条件、亮点、不足（区分作者承认 vs 推断）、可借鉴点和后续问题。Use this skill whenever the user gives a paper (PDF path, DOI, arXiv link, title, or pasted abstract/full text) and wants to read, summarize, critique, take notes on, or extract information from it — even if they just say "帮我看看这篇", "读一下", "这篇文章讲了什么", "总结这篇论文", "这篇有什么问题", "paper notes", or "summarize this paper". Not for searching many papers or writing a full literature review across papers.
---

# 读文献 (Paper Reading)

目标不是把论文"翻译一遍"，而是帮用户在最短时间内判断：**这篇文章说了什么、证据撑不撑得住、对我的研究有什么用**。笔记会被用户长期保存、反复检索，所以结构要稳定，每条结论都要能追溯回原文位置。

## 0. 先确定输入和深度

- **输入**：PDF 路径 / DOI / arXiv 号 / 标题 / 粘贴的文本。只有标题或 DOI 时，先找摘要和全文（OpenAlex、arXiv、Unpaywall）；找不到全文就明说"以下仅基于摘要"，不要假装读过正文。
- **深度**（用户没说时按此默认）：
  - **速读**：只有摘要，或用户一次给了多篇、或说"快速看下"。输出模板里的「一句话总结」「研究问题」「核心结论」「亮点/不足」即可。
  - **精读**：给了单篇全文。走完下面全部步骤。
- 如果有 Supporting Information，一并读：电池论文的关键条件（载量、电解液用量、N/P 比、循环倍率）经常只写在 SI 里。

## 1. 读取 PDF

不要直接 `cat` PDF。按这个顺序：

```bash
pdfinfo paper.pdf                         # 页数、大小
pdffonts paper.pdf                        # 没有字体 = 扫描版，需要栅格化看图
pdftotext -layout paper.pdf work/paper.txt  # 双栏论文用 -layout
```

文字提取看不到图。**电池论文的核心证据几乎都在图里**（循环曲线、XPS、cryo-EM、EIS），所以对承载核心结论的那几页做栅格化再看图：

```bash
pdftoppm -png -r 150 -f 3 -l 3 paper.pdf work/page
ls work/page-*.png    # 文件名按总页数补零，不要猜
```

只栅格化关键页（每页约 1600 tokens），不要整篇全转。

## 2. 三遍阅读

借鉴 Keshav 的 "How to Read a Paper" 三遍法：

1. **第一遍（5 分钟）**：标题、摘要、引言最后一段、所有图的标题、结论。回答：这是什么类型的文章（原创研究 / 综述 / 方法）？要解决什么问题？声称的主要贡献是什么？
2. **第二遍（抓证据）**：逐个核心结论，找到支撑它的图/表/数据，填进「声明-证据对照表」。记录实验条件和对照组。
3. **第三遍（批判）**：假设自己是审稿人。逐条过 [references/battery-checklist.md](references/battery-checklist.md) 中的检查项，写出不足。

## 3. 声明-证据对照（精读必做）

这是整份笔记最有价值的部分。对每个核心结论记录：

| 结论 | 证据位置 | 证据类型 | 强度 | 备注 |
|---|---|---|---|---|
| LiF 富集的 SEI 抑制枝晶 | Fig. 3c, Fig. S12 | XPS 深度剖析 + SEM | 中 | 只有相关性，没有排除其他组分的作用 |

- **证据位置**写到图号/表号/页码，用户要能回去核对。
- **强度**：强 = 多种独立手段 + 合理对照 + 统计；中 = 单一手段或缺对照；弱 = 只有推测或文字论证。
- 区分"作者展示了 X"和"作者认为 X"——机理解释往往属于后者。

## 4. 写笔记

严格按 [assets/note-template.md](assets/note-template.md) 的结构输出，这样多篇笔记之间可以横向对比、可以被脚本解析。

写作原则：
- **数字优先**：写"0.5C 下 500 圈容量保持 92%（Fig. 2b）"，不要写"循环性能优异"。
- **不足分两类**：作者自己承认的，和你推断的（例如"只测了纽扣电池、厚锂、富液"），后者标注「推断」。推断要有依据，不要为了凑数挑刺。
- **不编造**：原文没给的数据写"未报告"，不要用常识补。不确定的地方直接说不确定。
- **对用户有用**：「可借鉴点」写具体到能用的方法、表征手段、实验设计；「后续问题」写可以验证或继续追的问题。
- 用户用中文提问就用中文写；专业术语保留英文原词（如 LHCE、solvation sheath、N/P ratio）。

## 5. 保存

如果在项目目录中工作，把笔记保存到 `papers/notes/<第一作者姓>-<年份>-<关键词>.md`（例：`papers/notes/zhang-2025-lhce-sei.md`），并告诉用户路径。用户另有约定时以用户为准。

笔记末尾的 JSON 块使用和本项目 `sei_trends/schemas.py` 一致的受控词表（topic、limitation category、battery system），方便以后导入知识库做趋势分析。词表见 [references/battery-checklist.md](references/battery-checklist.md) 末尾。

## 多篇对比

用户给了 2–5 篇要对比时：每篇先按速读模板各写一份，然后加一张对比表（体系、关键策略、核心指标、测试条件、主要不足），最后写"这几篇放在一起说明了什么"。超过 5 篇或需要检索文献时，这已经是文献综述，不在本 skill 范围内，告诉用户。
