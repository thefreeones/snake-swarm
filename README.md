# Snake Swarm 🐍

**A Heterogeneous Multi-Agent Architecture for General Task Execution**

[![Zenodo DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21780091.svg)](https://doi.org/10.5281/zenodo.21780091)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

> "我们不追求零错误，追求错误能被快速识别并低成本修正。"

蛇群是一个**异构多智能体协同架构**，通过编排不同模型的认知互补性来降低系统级错误率——不依赖提升单一模型的能力，而是让不同模型互相审查、分歧触发深挖、错误形成闭环。

---

## 核心机制

```
任务输入 → 四维空间建模(V×Z) → 蛇头分层分析 → 蛇身执行 → 蛇尾结构化自述
                                         ↓
            ┌────────────────── 裁决层 ──────────────────┐
            │  语义法官(A)  ‖  测试法官(B)  ‖  契约法官(C) │
            │     3:0通过  /  2:1深挖  /  1:1:1仲裁       │
            └─────────────────────────────────────────────┘
                                         ↓
                审计层(L1规则零token → L2回归 → L3语义)
                                         ↓
                              学习层(模式提取 → 注入 → 成本下降)
```

- **四维任务空间建模**：V(价值)×Z(难度)×领域风险系数 → 自动路由蛇配置
- **角色化三法官**：语义/测试/契约三个独立视角，而非同一模型不同温度
- **黑箱重写**：修复失败时异构模型不看原代码重写，打破认知同源性
- **批量审查**：N个修复打包一次调用，-69%法官token
- **确定性审计**：规则引擎处理90%场景，零LLM token

---

## 实验数据摘要

### 模式A：缺陷检测与修复（14个实验，506次API）

| 实验 | 核心发现 |
|------|---------|
| P0-P3 | 缺陷检出100%(17/17构造用例)，三法官38%→100% |
| P4-P7 | 修复率75%，黑箱重写14/14回归通过 |
| P8 | python-slugify 5/5，与维护者方案100%一致 |
| P9-P13 | 成本优化四连击：8400→~5000t/bug (-40%) |
| P14 | validators 2/4，暴露框架约定盲区 |

### 模式B：项目构建（3个项目，105次API）

| 项目 | 模块 | 依赖拓扑 | 结果 |
|------|------|---------|------|
| matchlog CLI | 4 | 线性 | 首次集成通过 |
| Score Analyzer | 4 | 管道式 | 字段级契约8/8 |
| pystatic | 4 | **星形** | 5规则100%，零误报 |

---

## 快速开始

### CLI工具

```bash
# 检测代码缺陷
python snakes_cli/cli.py detect --repo ./my-project --profile code-bug-detect

# 修复模式
python snakes_cli/cli.py fix --repo ./my-project

# 项目构建模式
python snakes_cli/cli.py build --spec ./requirements.md
```

### GitHub Action

```yaml
# .github/workflows/snakes-review.yml
- uses: thefreeones/snake-swarm/snakes_github_action@main
  with:
    mode: detect
    repo: ${{ github.workspace }}
```

详见 [snakes_github_action/example_workflow.yml](snakes_github_action/example_workflow.yml)

---

## 论文

- **中文投稿版**：已投稿至《计算机研究与发展》，审稿中
- **英文预印本**：[Zenodo DOI: 10.5281/zenodo.21780091](https://doi.org/10.5281/zenodo.21780091)（早期版本，含6个基础实验）
- 完整论文状态见 [paper/README.md](paper/README.md)

---

## 项目结构

```
snake-swarm/
├── README.md              ← 项目主页
├── paper/                 ← 论文状态（不含投稿全文）
├── docs/
│   └── 蛇群架构设计.md     ← 完整架构设计文档 (v0.7)
├── experiments/           ← 全部实验脚本 + 结果数据
│   └── results/           ← 38个实验JSON
├── snakes_cli/            ← CLI工具核心代码
│   ├── cli.py             ← 命令行入口
│   ├── snakes_core.py     ← 核心引擎
│   ├── profile_matcher.py ← 任务剖面匹配器
│   └── profiles.yaml      ← 10个任务剖面
└── snakes_github_action/  ← GitHub Action
    ├── action.py
    ├── action.yml
    └── example_workflow.yml
```

---

## 许可证

- 代码：MIT License
- 论文预印本：CC-BY-4.0（仅限Zenodo版本）
