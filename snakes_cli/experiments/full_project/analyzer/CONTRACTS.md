# Mini Static Analyzer — 完整规格
#
# 与蛇群L1审计层共享8种危险模式知识,但作为独立CLI工具运行。
# 目标：验证蛇群模式B在"分析型工具"上的构建能力，
#       与matchlog的"CRUD型"形成对比数据点。

## 项目概述
Python CLI工具, 对指定文件/目录运行静态规则检测, 输出结构化报告。

## 任务拆解（待蛇头确认）
U1: AST解析器 — 遍历Python文件, 输出AST节点流
U2: 规则引擎 — 5个独立检测器, 消费AST节点
U3: 报告器 — 聚合各规则结果, 输出Markdown/JSON
U4: CLI入口 — argparse + 文件/目录遍历 + 输出控制

## 依赖拓扑（星形, 非matchlog的线性）
         U1(AST解析)
        /    |    \
   规则A  规则B  规则C  ...  = U2(5个规则)
        \    |    /
         U3(报告聚合)
              |
         U4(CLI入口)

## 5个检测规则
1. bare-except: 检测裸except:或except Exception
2. mutable-default: 检测函数默认参数为[]/{}
3. too-broad-try: 检测try块超过20行
4. print-leftover: 检测print()调用（可能是调试残留）
5. function-length: 检测函数超过50行

## 数据契约

### U1 → U2
产出: List[Issue]
  Issue: {file, line, rule_id, severity, message, code_snippet}

### U2 → U3
输入: List[Issue]（5个规则的结果合并）
产出: Report
  Report: {total_files, total_issues, by_severity, by_rule, issues}

### U3 → U4
输入: Report
产出: report.md 或 stdout JSON

## 验证标准
测试文件: D:/competation/design/snakes_cli/experiments/full_project/analyzer/test_samples/
- sample_clean.py: 0个问题（阴性对照）
- sample_dirty.py: 包含5种问题的文件
- sample_dir/: 多文件目录

预期检出: 在sample_dirty.py上, 所有5个规则至少各触发1次

## CLI接口
```
pystatic scan <path>            # 扫描文件/目录
pystatic scan <path> --format json  # JSON输出
pystatic scan <path> --rules bare-except,mutable-default  # 选择性启用
pystatic rules                  # 列出所有规则
```
