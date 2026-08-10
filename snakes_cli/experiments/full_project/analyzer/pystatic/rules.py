"""
pystatic U2 — 5个规则检测器

五个独立的 AST 规则检测器，每个检测一种 Python 反模式。
零外部依赖，纯标准库 ast 模块。

规则:
  1. bare-except       — 裸 except: (不带具体异常类型)
  2. mutable-default   — 函数默认参数为可变对象 (list/dict/set)
  3. too-broad-try     — try 块超过 20 条语句
  4. print-leftover    — 残留的 print() 调试调用
  5. function-length   — 函数体超过 50 行
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List


@dataclass
class Issue:
    """单个规则检测问题。

    Attributes:
        file: 源文件路径。
        line: 问题所在行号 (1-indexed)。
        rule_id: 规则标识符 (如 "bare-except")。
        severity: 严重级别 ("error" | "warning" | "info")。
        message: 人类可读的问题描述。
        code_snippet: 触发问题的源代码行 (去除首尾空白)。
    """
    file: str
    line: int
    rule_id: str
    severity: str
    message: str
    code_snippet: str


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_code_snippet(source: str, lineno: int) -> str:
    """从源码中提取指定行的内容作为代码片段。

    Args:
        source: 原始源代码字符串。
        lineno: 1-indexed 行号。

    Returns:
        去除首尾空白的代码行；若行号越界则返回空字符串。
    """
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


# ---------------------------------------------------------------------------
# 规则检测器
# ---------------------------------------------------------------------------

def check_bare_except(tree: ast.AST, source: str, filepath: str) -> List[Issue]:
    """检测裸 except: 语句 (不带具体异常类型)。

    裸 except 会捕获所有异常，包括 SystemExit 和 KeyboardInterrupt，
    导致程序难以正常终止，且隐藏意外错误。

    Args:
        tree: 已解析的 AST 树。
        source: 原始源代码字符串。
        filepath: 源文件路径。

    Returns:
        List[Issue]: 检测到的问题列表。
    """
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    rule_id="bare-except",
                    severity="error",
                    message=(
                        "Bare except clause catches all exceptions "
                        "including SystemExit and KeyboardInterrupt"
                    ),
                    code_snippet=_get_code_snippet(source, node.lineno),
                ))
    return issues


def check_mutable_default(tree: ast.AST, source: str, filepath: str) -> List[Issue]:
    """检测函数默认参数使用可变对象 (list/dict/set)。

    Python 在函数定义时只求值一次默认参数，可变默认值会在所有调用间
    共享同一个对象，导致难以追踪的副作用。

    Args:
        tree: 已解析的 AST 树。
        source: 原始源代码字符串。
        filepath: 源文件路径。

    Returns:
        List[Issue]: 检测到的问题列表。
    """
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    mutable_type: str = type(default).__name__.lower()
                    issues.append(Issue(
                        file=filepath,
                        line=node.lineno,
                        rule_id="mutable-default",
                        severity="warning",
                        message=(
                            f"Mutable default argument {mutable_type}() "
                            f"in function '{node.name}' — shared across all calls"
                        ),
                        code_snippet=_get_code_snippet(source, node.lineno),
                    ))
                    break  # 每个函数只报告一次
    return issues


def check_too_broad_try(tree: ast.AST, source: str, filepath: str) -> List[Issue]:
    """检测 try 块包含超过 20 条语句。

    过大的 try 块容易隐藏异常来源，应缩小 try 范围到仅包裹可能
    抛出异常的语句，其余逻辑放在 try 外部。

    Args:
        tree: 已解析的 AST 树。
        source: 原始源代码字符串。
        filepath: 源文件路径。

    Returns:
        List[Issue]: 检测到的问题列表。
    """
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            body_count: int = len(node.body)
            if body_count > 20:
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    rule_id="too-broad-try",
                    severity="warning",
                    message=(
                        f"Try block has {body_count} statements "
                        f"(max 20 recommended) — narrow the exception scope"
                    ),
                    code_snippet=_get_code_snippet(source, node.lineno),
                ))
    return issues


def check_print_leftover(tree: ast.AST, source: str, filepath: str) -> List[Issue]:
    """检测残留的 print() 调试调用。

    生产代码中的 print() 通常是调试遗留，应替换为 logging 模块。
    仅检测 `print(...)` 形式的调用，不检测 `obj.print()` 等方法调用。

    Args:
        tree: 已解析的 AST 树。
        source: 原始源代码字符串。
        filepath: 源文件路径。

    Returns:
        List[Issue]: 检测到的问题列表。
    """
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    rule_id="print-leftover",
                    severity="info",
                    message="Possible leftover debug print() call",
                    code_snippet=_get_code_snippet(source, node.lineno),
                ))
    return issues


def check_function_length(tree: ast.AST, source: str, filepath: str) -> List[Issue]:
    """检测函数体超过 50 行。

    过长的函数难以理解和测试，建议拆分为多个职责单一的小函数。

    Args:
        tree: 已解析的 AST 树。
        source: 原始源代码字符串。
        filepath: 源文件路径。

    Returns:
        List[Issue]: 检测到的问题列表。
    """
    issues: List[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            length: int = node.end_lineno - node.lineno
            if length > 50:
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    rule_id="function-length",
                    severity="warning",
                    message=(
                        f"Function '{node.name}' spans {length} lines "
                        f"(max 50 recommended)"
                    ),
                    code_snippet=_get_code_snippet(source, node.lineno),
                ))
    return issues


# ---------------------------------------------------------------------------
# 注册表 — 供 CLI 按名称查找
# ---------------------------------------------------------------------------

ALL_RULES: dict[str, object] = {
    "bare-except": check_bare_except,
    "mutable-default": check_mutable_default,
    "too-broad-try": check_too_broad_try,
    "print-leftover": check_print_leftover,
    "function-length": check_function_length,
}


# ---------------------------------------------------------------------------
# 冒烟测试 (smoketest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # 测试样本: sample_dirty.py 的代码片段
    DIRTY_SOURCE: str = r'''
def add_item(item, target=[]):
    target.append(item)
    return target

def risky_parse(data):
    try:
        return __import__("json").loads(data)
    except:
        return None

def long_try_block():
    try:
        a=1;b=2;c=3;d=4;e=5;f=6;g=7;h=8;i=9;j=10
        k=11;l=12;m=13;n=14;o=15;p=16;q=17;r=18
        s=19;t=20;u=21;v=22
    except ValueError:
        return 0

def calculate(x):
    print("DEBUG: input is", x)
    result = x * 2
    print("result =", result)
    return result

def very_long_function():
    """A function that spans more than 50 lines."""
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    h = 8
    i = 9
    j = 10
    k = 11
    l = 12
    m = 13
    n = 14
    o = 15
    p = 16
    q = 17
    r = 18
    s = 19
    t = 20
    u = 21
    v = 22
    w = 23
    x = 24
    y = 25
    z = 26
    aa = 27
    bb = 28
    cc = 29
    dd = 30
    ee = 31
    ff = 32
    gg = 33
    hh = 34
    ii = 35
    jj = 36
    kk = 37
    ll = 38
    mm = 39
    nn = 40
    oo = 41
    pp = 42
    qq = 43
    rr = 44
    ss = 45
    tt = 46
    uu = 47
    vv = 48
    ww = 49
    xx = 50
    yy = 51
    zz = 52
    return zz
'''

    DIRTY_TREE: ast.AST = ast.parse(DIRTY_SOURCE)
    DIRTY_PATH: str = "sample_dirty.py"
    print("=" * 60)
    print("  Smoketest: sample_dirty.py (should trigger ALL 5 rules)")
    print("=" * 60)

    all_issues: List[Issue] = []
    for rule_id, checker in ALL_RULES.items():
        issues: List[Issue] = checker(DIRTY_TREE, DIRTY_SOURCE, DIRTY_PATH)
        all_issues.extend(issues)
        status: str = "PASS" if issues else "FAIL (no issues)"
        print(f"\n[{rule_id}]  found={len(issues)}  {status}")
        for iss in issues:
            print(f"  line={iss.line}  sev={iss.severity}  {iss.message}")
            print(f"  code: {iss.code_snippet}")

    # 检查是否所有规则都至少触发了一次
    triggered_rules: set[str] = {iss.rule_id for iss in all_issues}
    missing: set[str] = set(ALL_RULES) - triggered_rules
    print("\n" + "-" * 60)
    print(f"Total issues: {len(all_issues)}")
    if missing:
        print(f"FAIL — rules not triggered: {missing}")
        sys.exit(1)
    else:
        print("ALL 5 RULES TRIGGERED — smoketest PASSED")

    # --- 阴性对照: sample_clean.py ---
    CLEAN_SOURCE: str = r'''
def calculate_average(numbers):
    if not numbers:
        raise ValueError("empty")
    return sum(numbers) / len(numbers)

def process(data):
    try:
        result = calculate_average(data)
    except ValueError:
        result = 0
    return result
'''
    CLEAN_TREE: ast.AST = ast.parse(CLEAN_SOURCE)
    CLEAN_PATH: str = "sample_clean.py"
    print("\n" + "=" * 60)
    print("  Smoketest: sample_clean.py (should produce 0 issues)")
    print("=" * 60)

    clean_issues: List[Issue] = []
    for rule_id, checker in ALL_RULES.items():
        issues = checker(CLEAN_TREE, CLEAN_SOURCE, CLEAN_PATH)
        clean_issues.extend(issues)
        if issues:
            print(f"\n[{rule_id}]  found={len(issues)}  UNEXPECTED")
            for iss in issues:
                print(f"  {iss}")
    if clean_issues:
        print(f"\nFAIL — {len(clean_issues)} unexpected issues on clean sample")
        sys.exit(1)
    else:
        print("0 issues — clean smoketest PASSED")
        print("\n✓ All smoketests passed.")
