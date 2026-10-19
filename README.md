# Snake Swarm 🐍

**A Heterogeneous Multi-Agent Architecture for General Task Execution**

[![Zenodo DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21780091.svg)](https://doi.org/10.5281/zenodo.21780091)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

> "我们不追求零错误，追求错误能被快速识别并低成本修正。"

蛇群是一个**异构多智能体协同架构**，用于自动检测与修复代码缺陷，并支持模块化项目构建。当前实现为 CLI 工具 + SWE-bench 评测管道：17 个构造用例、3 个完整项目构建、611 次 API 调用，成本约 5,000 tokens/bug；在 SWE-bench 26 个真实缺陷实例上 resolved 7/26（26.9%，R1→R5 提升 7 倍）。

---

## 当前能做什么

```
snakes fix slugify.py smart_truncate "negative max_length causes truncation"
```

背后流程：

```
Bug描述 → 蛇头分层分析(轻量DeepSeek/重量Claude)
       → 修复蛇生成修复代码
       → L1确定性审计(零token AST扫描)
       → 输出 unified diff patch
```

### 已实现的核心机制

| 机制 | 说明 | 来源 |
|------|------|------|
| 蛇头分层 | 根据bug复杂度自动选择轻量/重量模型 | P11:-62.5% |
| 修复模板匹配 | 6个模板，关键词命中→零token修复 | P13:67%命中 |
| 文件级缓存 | 同文件多bug，后续只传目标函数 | P12:-58.2% |
| L1确定性审计 | AST扫描裸except/bool-is-int/范围溢出 | P4:零token |
| 批量法官审查 | N个修复打包一次LLM调用 | P10:-68.6% |
| 快速验证 | 子进程执行修复代码+触发输入 | — |

### CLI四个命令

```bash
# 配置
snakes config --init
snakes config --api-key <tokeness-key>

# 修复单个bug
snakes fix <file> <function> "<bug描述>" [--trigger "输入"]

# 批量扫描
snakes scan <file> --bugs bugs.json

# 查看修复模板
snakes templates
```

---

## 实验验证（14个实验，506次API）

| 实验 | 核心发现 |
|------|---------|
| P0-P3 | 缺陷检出100%(17/17用例)，三法官38%→100% |
| P4-P7 | 修复率75%，黑箱重写14/14回归通过 |
| P8 | python-slugify 5/5，与维护者方案100%一致 |
| P9-P13 | 成本优化：8400→~5000t/bug (-40%) |
| P14 | validators 2/4，暴露框架约定盲区 |

模式B项目构建（3个项目，105次API）：matchlog CLI / Score Analyzer / pystatic，12/12模块首次集成通过。

---

## SWE-bench 评测（26 个真实缺陷实例）

在 SWE-bench dev 集上选取 26 个 Python 实例（marshmallow 8 / astroid 18），完整流程为：clone → checkout base_commit → 建 venv → 应用 test_patch → 复现 FAIL_TO_PASS → 定位 → 修复 → 复跑 FAIL_TO_PASS + PASS_TO_PASS。判定与官方 harness 一致：FAIL_TO_PASS 全过且 PASS_TO_PASS 无回归记为 RESOLVED。

| 轮次 | resolved | 通过率 | 关键改动 |
|------|---------|-------|---------|
| R1 | 1/26 | 3.8% | 初始管道，65% 失败为空 content |
| R2 | 3/9 | 33% | 修 max_tokens，被定时关机中断 |
| R3 | 6/26 | 23.1% | 定位纠偏 + 中间验证循环 |
| R4 | 5/26 | 19.2% | 引入候选截断 bug（候选1失败即放弃） |
| R5 | 7/26 | 26.9% | 修复 P1-1，多候选循环恢复 |

失败模式（R5）：候选 2 轮迭代全败 43%、迭代耗尽仍失败 31%、patch apply 失败 16%、空 content 4%、其他 6%。
分层：有 traceback 实例 4/8（50%），无 traceback 3/18（17%）。
消融：多候选切换直接救回 3 个实例（927/934/1252）。

诚实边界：无 Docker，手动评测与官方 harness 环境不完全等价；单供应商模型（DeepSeek），三法官异构性降级为同供应商多模型+多温度；单次运行受采样随机性影响，best-of-k 合并后 7/7 保持。

---

## 代码结构

```
snakes_cli/
  snakes_core.py        五层核心：执行层(蛇头/蛇身/蛇尾) · 裁决层(三法官) ·
                        修复层(A 修复 + B 黑箱重写) · 审计层(L1/L2/L3) · 学习层
  locator.py            定位层：traceback 行号确定性定位 + LLM 语义候选 +
                        AST 索引路径纠偏 + 符号检索兜底(P0-4 降权)
  run_swebench.py       SWE-bench 端到端评测管道（含多候选切换、中间验证循环、
                        迭代2轮失败→黑箱重写触发）
  cli.py                CLI 入口（config / fix / scan / build / templates）
  profile_matcher.py    四维任务空间(X/Y/Z/V)剖面匹配
  profiles.yaml         快照剖面表
  patterns.json         学习层模式库（114 条，含触发条件/教训/修复策略/置信度）
  fix_knowledge.jsonl   修复知识库（61 条：自身成功修复 + 同仓历史 PR，已排除评测实例）
```

---

## 复现 SWE-bench 评测

```bash
# 需本地已有各 repo 的 clone 与对应 Python 环境（astroid 3.10 / marshmallow 3.11）
python snakes_cli/run_swebench.py --instances swebench_results_r3.jsonl
```

评测数据与逐实例结果：`swebench_results_r3.jsonl`。

---

## 架构设计 vs 代码实现

完整的v0.7架构设计见 [docs/蛇群架构设计_v0.7.md](docs/蛇群架构设计_v0.7.md)。以下是当前代码与设计的对照：

| 架构组件 | 代码 |
|---------|:----:|
| 蛇头分层 + 修复蛇 + L1审计 | ✅ |
| 角色化三法官(语义/测试/契约) | ✅ |
| 冲突处理(3:0/2:1/1:1:1) + 仲裁器 | ✅ |
| 黑箱重写(B阶段修复) | ✅ |
| 蛇尾结构化自述 + 校验 | ✅ |
| 学习层(提取→检索→注入→反馈) | ✅ |
| 模式B项目构建(需求→模块→集成) | ✅ |
| 模板匹配 + 文件缓存 | ✅ |
| 任务剖面匹配器 | ✅ |
| 定位层(多路融合 + AST 路径纠偏) | ✅ |
| 多候选切换(测试反馈驱动) | ✅ |
| SWE-bench 端到端评测管道 | ✅ |

> ⚠️ **异构性要求**: 三角色法官必须使用**至少两个不同供应商**的模型（如DeepSeek+Gemini）。同厂商模型共享训练偏差，丧失互补性。初始化时自动校验并警告。[设计原理](docs/蛇群架构设计_v0.7.md)

---

## 快速开始

```bash
# 1. 安装依赖
pip install requests pyyaml

# 2. 配置API Key (Tokeness中转站)
python snakes_cli/cli.py config --api-key sk-xxx

# 3. 修复一个bug
python snakes_cli/cli.py fix tests/fixtures/slugify.py smart_truncate \
  "negative max_length bypasses validation"

# 4. 批量修复
python snakes_cli/cli.py scan tests/fixtures/slugify.py \
  --bugs snakes_cli/sample_bugs.json
```

---

## 论文

- **中文投稿版**：已投稿（CCF-B 期刊，审稿中）；全文待审稿结束后放出
- **英文预印本**：[Zenodo DOI: 10.5281/zenodo.21780091](https://doi.org/10.5281/zenodo.21780091)（早期版本，仅含 P0 阶段六个实验）

---

## 许可证

- 代码：MIT License
- 论文预印本：CC-BY-4.0
