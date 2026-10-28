# 电池 / SEI 论文批判性阅读检查表

第三遍阅读时逐项过一遍。不是每项都适用；只把真正影响结论的问题写进笔记的「不足」。

## 1. 实用条件（最常见的问题）

漂亮的循环数据经常来自"宽松条件"。对照以下数值判断结论能否外推到实用电池：

| 参数 | 常见宽松条件 | 接近实用的条件 |
|---|---|---|
| 负极锂 | 250–750 μm 厚锂 | ≤ 50 μm，或无负极 |
| N/P 比 | > 10 | ≤ 3 |
| 电解液 | > 50 μL / 纽扣电池（富液） | ≤ 3 g Ah⁻¹（贫液） |
| 正极面载量 | < 2 mAh cm⁻² | ≥ 3–4 mAh cm⁻² |
| 电池形式 | 纽扣 | 多层软包（≥ 1 Ah 更有说服力） |
| 对称电池 | 1 mA cm⁻²、1 mAh cm⁻² | ≥ 3 mAh cm⁻²，并有全电池验证 |

任何一项没报告，记为"未报告"，而不是默认它是实用条件。

## 2. 电化学数据

- 库伦效率怎么测的？Aurbach 法 / 直接循环 CE？平均 CE 是否 ≥ 99.5%？
- 容量保持率的基准是第几圈？（以第 1 圈还是活化后的第 3 圈为基准差别很大）
- 只展示了一个电池吗？有没有误差棒、重复电池数？
- 倍率测试和长循环用的是不是同一个条件？
- 对照组是否合理（同样条件下的常规电解液，而不是被刻意弱化的对照）？

## 3. 表征与 SEI 归因

- XPS 是否做了深度剖析？只有表面谱时不能代表整个 SEI。溅射是否会引起还原假象？
- 样品转移是否隔绝空气？锂金属 SEI 对空气和电子束都极敏感。
- cryo-EM 的视场是否有代表性（单个区域 vs 统计）？
- "富 LiF 所以性能好"——是相关还是因果？有没有排除其他组分 / 形貌 / 溶剂化结构变化的影响？
- 是否有原位 / operando 证据，还是全靠循环后的 ex situ 测试？
- 定量了吗（SEI 厚度、组分比例、离子电导、杨氏模量），还是只有定性描述？

## 4. 计算模拟

- DFT 只算了还原电位 / LUMO？LUMO 不等于实际还原顺序，要看是否考虑了溶剂化结构和界面。
- MD 体系大小、时长、力场是否可靠？溶剂化结构的配位数是否有实验（Raman / NMR）佐证？
- 模拟结论有没有被实验验证，或者反过来？

## 5. 通用性与可扩展性

- 只用了一种正极 / 一种负极 / 一个温度？
- 关键材料（如氟化溶剂、锂盐）的成本、毒性、可得性？
- 高温 / 低温 / 高电压 / 快充下还成立吗？
- 产气、热稳定性、安全性有没有评估？

## 6. 论述

- 摘要和结论是否夸大了正文数据？（例如正文只有纽扣电池，摘要写"实用化"）
- 机理图是否有数据支撑，还是示意性的推测？
- 引用的对比数据是否在相同条件下？"性能对比雷达图/表"尤其要检查条件是否一致。

---

## 受控词表（与 `sei_trends/schemas.py` 保持一致）

**topic**：
`electrolyte_solvation_design`, `electrolyte_additives`, `artificial_sei_coatings`, `sei_composition_structure`, `sei_formation_mechanism`, `ion_transport_kinetics`, `sei_mechanics_stability`, `sei_aging_degradation`, `advanced_characterization`, `computation_simulation`, `machine_learning_data`, `solid_state_interphases`, `extreme_conditions`, `beyond_lithium`, `practical_cells_scaleup`, `safety_gas_evolution`

**limitation category**：
`mechanism_unclear`, `characterization_artifacts`, `lab_scale_only`, `insufficient_cycle_life`, `narrow_operating_window`, `cost_scalability`, `limited_generality`, `lacks_quantification`, `model_validation_gap`, `reproducibility_statistics`, `safety_not_assessed`, `other`

**battery system**：
`li_metal`, `anode_free`, `graphite`, `silicon`, `lithium_sulfur`, `solid_state`, `sodium`, `potassium`, `zinc`, `multivalent_other`, `other`

**severity**：`minor`（不影响主要结论）/ `moderate`（限制结论适用范围）/ `major`（核心结论可能不成立）
