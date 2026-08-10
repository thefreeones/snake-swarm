# Snake Swarm 🐍

**A Heterogeneous Multi-Agent Architecture for General Task Execution**

[![Zenodo DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21780091.svg)](https://doi.org/10.5281/zenodo.21780091)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

> "我们不追求零错误，追求错误能被快速识别并低成本修正。"

蛇群是一个**异构多智能体协同架构**，用于自动检测和修复代码缺陷。当前实现为实验验证阶段的CLI工具——完成14个实验（506次API调用），成本优化至~5000 tokens/bug。

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

- **中文投稿版**：已投稿至《计算机研究与发展》，审稿中
- **英文预印本**：[Zenodo DOI: 10.5281/zenodo.21780091](https://doi.org/10.5281/zenodo.21780091)

---

## 许可证

- 代码：MIT License
- 论文预印本：CC-BY-4.0
