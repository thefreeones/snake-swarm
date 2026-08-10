"""
U3: 报告聚合器 — 聚合Issue列表，输出Markdown或JSON报告。

接收所有规则的Issue列表，聚合统计，输出Markdown或JSON格式报告。
零外部依赖，纯标准库实现。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """单个检测到的问题。

    Attributes:
        file: 源文件路径。
        line: 问题所在行号（1-indexed）。
        rule_id: 规则标识符，如 "bare-except", "mutable-default"。
        severity: 严重级别 — "error", "warning", "info"。
        message: 人类可读的问题描述。
        code_snippet: 触发的代码片段（可选）。
    """

    file: str
    line: int
    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str
    code_snippet: str = ""


@dataclass
class Report:
    """聚合后的扫描报告。

    Attributes:
        total_files: 被扫描的文件总数。
        total_issues: 发现的问题总数。
        by_severity: 按严重级别汇总，如 {"error": N, "warning": N, "info": N}。
        by_rule: 按规则汇总，如 {"bare-except": N, ...}。
        issues: 所有Issue实例的列表。
    """

    total_files: int
    total_issues: int
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_rule: Dict[str, int] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def aggregate(issues: List[Issue]) -> Report:
    """聚合Issue列表为Report。

    从Issue列表中提取去重文件数、按严重级别和规则分组统计。

    Args:
        issues: Issue实例列表。

    Returns:
        聚合后的Report对象。
    """
    total_files = len(set(issue.file for issue in issues))

    by_severity: Dict[str, int] = defaultdict(int)
    by_rule: Dict[str, int] = defaultdict(int)

    for issue in issues:
        by_severity[issue.severity] += 1
        by_rule[issue.rule_id] += 1

    return Report(
        total_files=total_files,
        total_issues=len(issues),
        by_severity=dict(by_severity),
        by_rule=dict(by_rule),
        issues=list(issues),
    )


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_LABELS = {"error": "Error", "warning": "Warning", "info": "Info"}

_RULE_LABELS: Dict[str, str] = {
    "bare-except": "裸 Except",
    "mutable-default": "可变默认参数",
    "too-broad-try": "Try 块过长",
    "print-leftover": "调试残留 (print)",
    "function-length": "函数过长",
}


def _severity_sort_key(issue: Issue) -> int:
    return _SEVERITY_ORDER.get(issue.severity, 99)


def to_markdown(report: Report) -> str:
    """输出Markdown格式报告。

    Args:
        report: 聚合后的Report对象。

    Returns:
        Markdown格式的报告字符串。
    """
    lines: List[str] = []

    # 标题
    lines.append("# pystatic 扫描报告")
    lines.append("")

    # 概览
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 扫描文件: {report.total_files}")
    lines.append(f"- 总问题: {report.total_issues}")

    sev_parts = []
    for sev in ("error", "warning", "info"):
        count = report.by_severity.get(sev, 0)
        sev_parts.append(f"{_SEVERITY_LABELS[sev]}: {count}")
    lines.append(f"- {' | '.join(sev_parts)}")
    lines.append("")

    # 按规则统计
    lines.append("## 按规则统计")
    lines.append("")
    if report.by_rule:
        lines.append("| 规则 | 数量 |")
        lines.append("|------|------|")
        for rule_id, count in sorted(report.by_rule.items()):
            label = _RULE_LABELS.get(rule_id, rule_id)
            lines.append(f"| {label} | {count} |")
    else:
        lines.append("_未检测到问题_")
    lines.append("")

    # 详细问题列表
    lines.append("## 详细问题列表")
    lines.append("")

    if not report.issues:
        lines.append("_未检测到问题_")
        return "\n".join(lines)

    # 按文件分组，按严重度 > 行号排序
    by_file: Dict[str, List[Issue]] = defaultdict(list)
    for issue in report.issues:
        by_file[issue.file].append(issue)

    for file_path in sorted(by_file):
        file_issues = sorted(by_file[file_path], key=lambda i: (_severity_sort_key(i), i.line))
        lines.append(f"### {file_path}")
        lines.append("")
        for idx, issue in enumerate(file_issues):
            sev_label = _SEVERITY_LABELS.get(issue.severity, issue.severity)
            lines.append(f"**{idx + 1}. [{sev_label}] {issue.message}**")
            lines.append(f"- 行号: `{issue.line}` — 规则: `{issue.rule_id}`")
            if issue.code_snippet:
                lines.append("- 代码片段:")
                lines.append("")
                lines.append("```python")
                lines.append(issue.code_snippet.rstrip())
                lines.append("```")
            lines.append("")

    return "\n".join(lines)


def to_json(report: Report) -> str:
    """输出JSON格式报告。

    Args:
        report: 聚合后的Report对象。

    Returns:
        格式化的JSON字符串（indent=2，ensure_ascii=False）。
    """
    serializable = {
        "total_files": report.total_files,
        "total_issues": report.total_issues,
        "by_severity": report.by_severity,
        "by_rule": report.by_rule,
        "issues": [
            {
                "file": i.file,
                "line": i.line,
                "rule_id": i.rule_id,
                "severity": i.severity,
                "message": i.message,
                "code_snippet": i.code_snippet,
            }
            for i in report.issues
        ],
    }
    return json.dumps(serializable, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Smoketest — 直接运行本文件以验证模块
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 构造模拟Issue数据（覆盖5种规则、3种严重级别、2个文件）
    fake_issues: List[Issue] = [
        Issue(
            file="src/dirty.py",
            line=23,
            rule_id="bare-except",
            severity="error",
            message="禁止使用裸 except:",
            code_snippet="except:\n    return None",
        ),
        Issue(
            file="src/dirty.py",
            line=9,
            rule_id="mutable-default",
            severity="warning",
            message="函数默认参数为可变对象 []",
            code_snippet="def add_item(item, target=[]):",
        ),
        Issue(
            file="src/dirty.py",
            line=37,
            rule_id="too-broad-try",
            severity="warning",
            message="try 块包含 22 行，超过限制 20 行",
            code_snippet="try:\n    a = 1\n    ...\n    v = 22",
        ),
        Issue(
            file="src/dirty.py",
            line=66,
            rule_id="print-leftover",
            severity="info",
            message="可能存在调试残留: print()",
            code_snippet='print("DEBUG: input is", x)',
        ),
        Issue(
            file="src/dirty.py",
            line=73,
            rule_id="function-length",
            severity="warning",
            message="函数 very_long_function 包含 52 行，超过限制 50 行",
            code_snippet="def very_long_function():\n    a = 1\n    ...\n    return zz",
        ),
        Issue(
            file="src/utils.py",
            line=5,
            rule_id="print-leftover",
            severity="info",
            message="可能存在调试残留: print()",
            code_snippet='print("Hello")',
        ),
    ]

    report = aggregate(fake_issues)

    # 基础断言
    assert report.total_files == 2, f"expected 2 files, got {report.total_files}"
    assert report.total_issues == 6, f"expected 6 issues, got {report.total_issues}"
    assert report.by_severity == {"error": 1, "warning": 3, "info": 2}, (
        f"severity mismatch: {report.by_severity}"
    )
    assert report.by_rule == {
        "bare-except": 1,
        "mutable-default": 1,
        "too-broad-try": 1,
        "print-leftover": 2,
        "function-length": 1,
    }, f"rule mismatch: {report.by_rule}"

    # 输出测试
    md = to_markdown(report)
    assert "# pystatic 扫描报告" in md
    assert "src/dirty.py" in md
    assert "src/utils.py" in md
    assert "裸 Except" in md
    assert "可变默认参数" in md
    assert "调试残留 (print)" in md
    print("=== Markdown 报告 ===")
    print(md)

    j = to_json(report)
    data = json.loads(j)
    assert data["total_files"] == 2
    assert len(data["issues"]) == 6
    print("\n=== JSON 报告 ===")
    print(j)

    print("\nreporter.py — OK (all assertions passed)")
