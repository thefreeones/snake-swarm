"""
pystatic U1 — AST 解析器 + Issue 数据模型
===========================================
遍历 Python 文件/目录，用 ast 模块解析，为后续规则引擎提供 AST 节点流。

零外部依赖（仅 ast/stdlib），类型注解 + docstring。
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass
class Issue:
    """规则引擎产出的单条问题记录。

    Attributes:
        file: 触发问题的源文件路径。
        line: 行号（1-indexed）。
        rule_id: 规则 ID，例如 ``bare-except``、``mutable-default``。
        severity: 严重级别 — ``"error"`` | ``"warning"`` | ``"info"``。
        message: 人类可读的问题描述。
        code_snippet: 触发问题的代码片段（单行，已去除首尾空白）。
    """

    file: str
    line: int
    rule_id: str
    severity: str
    message: str
    code_snippet: str = ""


# ── AST 解析 ────────────────────────────────────────────────────────────────

def get_ast_nodes(filepath: str) -> tuple[Optional[ast.AST], str]:
    """解析单个 Python 文件，返回 ``(AST根节点, 源代码字符串)``。

    遇到 ``SyntaxError`` 时返回 ``(None, 错误描述信息)``。

    Args:
        filepath: Python 源文件的绝对或相对路径。

    Returns:
        二元组 ``(ast_root, source_code)``；语法错误时第一个元素为 ``None``，
        第二个元素为人工可读的错误描述。

    Examples:
        >>> root, src = get_ast_nodes("example.py")
        >>> isinstance(root, ast.AST)
        True
    """
    path = Path(filepath)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"Cannot read file: {exc}"

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return None, f"SyntaxError in {path}: {exc}"

    return tree, source


# ── 路径扫描 ────────────────────────────────────────────────────────────────

def _iter_py_files(path: Path) -> List[Path]:
    """收集单个文件或目录下所有 ``.py`` 文件（递归）。"""
    path = path.resolve()
    if path.is_file():
        return [path] if path.suffix == ".py" else []

    py_files: List[Path] = []
    for root, _dirs, files in os.walk(path):
        root_path = Path(root)
        for fname in files:
            if fname.endswith(".py"):
                py_files.append(root_path / fname)
    return sorted(py_files)


def scan_path(path: str) -> List[Issue]:
    """扫描单个文件或目录，递归收集所有 ``.py`` 文件并解析。

    当前版本返回空列表 — 规则引擎会在此基础上填充 ``Issue``。
    如果某个文件无法解析（``SyntaxError`` / 读取失败），会在 stderr 输出
    一条诊断信息，但不会中断扫描。

    Args:
        path: 文件或目录路径。

    Returns:
        ``Issue`` 列表（当前始终为空，由规则引擎填充）。
    """
    target = Path(path)
    if not target.exists():
        print(f"[pystatic] WARNING: path does not exist: {path}", flush=True)
        return []

    py_files = _iter_py_files(target)
    for fpath in py_files:
        ast_root, msg = get_ast_nodes(str(fpath))
        if ast_root is None:
            print(f"[pystatic] SKIP {fpath}: {msg}", flush=True)

    return []


# ── 自检 smoketest ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # 默认测试目录：与本文件同级的 test_samples
    script_dir = Path(__file__).resolve().parent
    samples_dir = script_dir.parent / "test_samples"

    if not samples_dir.is_dir():
        print(f"test_samples dir not found at {samples_dir}", file=sys.stderr)
        sys.exit(1)

    # ··· 1. 单文件解析 ·······················································
    clean_file = samples_dir / "sample_clean.py"
    print(f"--- Parsing {clean_file.name} ---")
    root, src = get_ast_nodes(str(clean_file))
    assert root is not None, "sample_clean.py 应能正常解析"
    assert isinstance(root, ast.AST)
    assert len(src) > 0
    print(f"  ✓ AST root type: {type(root).__name__}")
    print(f"  ✓ Source length: {len(src)} chars")
    print(f"  ✓ Top-level nodes: {len(root.body)}")

    # ··· 2. 目录扫描 ·························································
    print(f"\n--- Scanning directory {samples_dir.name} ---")
    issues = scan_path(str(samples_dir))
    print(f"  ✓ scan_path returned {len(issues)} issues (expected 0)")

    # ··· 3. 语法错误文件 ·····················································
    invalid_file = samples_dir / "__invalid_syntax_test__.py"
    invalid_file.write_text("def broken(\n", encoding="utf-8")
    try:
        print(f"\n--- Parsing intentionally broken file ---")
        root2, msg2 = get_ast_nodes(str(invalid_file))
        assert root2 is None, "语法错误文件应返回 None"
        assert "SyntaxError" in msg2
        print(f"  ✓ Correctly returned error: {msg2[:80]}...")
    finally:
        invalid_file.unlink(missing_ok=True)

    # ··· 4. 不存在的文件 ·····················································
    print(f"\n--- Parsing non-existent file ---")
    issues_bad = scan_path(str(samples_dir / "does_not_exist.py"))
    assert issues_bad == []
    print(f"  ✓ Non-existent path returns empty list")

    print("\n✓ All smoketests passed.")
