#!/usr/bin/env python3
"""
蛇群 SWE-bench 定位层 (Locator)
================================
输入: issue 描述 + repo 目录
输出: 候选修复位置 {file, function, class_name}

公平性设计:
- 不读取 gold patch / test_patch
- 只使用 issue 描述 + 代码结构索引(文件/类/方法名, AST零token扫描)
- LLM 基于这两者输出候选位置, 与 SWE-bench 标准玩法一致
  (模型需要自己定位 bug 在哪)

用法:
    python locator.py <repo_dir> "<issue描述>"
"""
import argparse
import ast
import json
import os
import sys


def scan_repo(repo_dir: str, max_files: int = 60) -> dict:
    """AST 扫描 repo, 构建 文件→类→方法 索引 (零token)."""
    index = {}
    for root, dirs, files in os.walk(repo_dir):
        # 跳过常见噪声目录
        dirs[:] = [d for d in dirs if d not in (
            ".git", ".venv", "venv", "node_modules", "__pycache__",
            ".tox", ".pytest_cache", "build", "dist", "docs", "tests", "test",
        )]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, repo_dir).replace("\\", "/")
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    code = f.read()
                tree = ast.parse(code)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            classes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body
                               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    classes.append({"name": node.name, "methods": methods})
            funcs = [n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if classes or funcs:
                index[rel] = {"classes": classes, "funcs": funcs}
            if len(index) >= max_files:
                return index
    return index


def render_index(index: dict) -> str:
    """把索引渲染成 token 友好的文本."""
    lines = []
    for rel, info in sorted(index.items()):
        parts = [f"{rel}:"]
        if info["funcs"]:
            parts.append(f"  funcs: {', '.join(info['funcs'][:20])}")
        for cls in info["classes"][:10]:
            methods = ", ".join(cls["methods"][:15])
            parts.append(f"  class {cls['name']}: {methods}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


LOCATOR_PROMPT = """你是代码定位专家。给定一个 GitHub issue 描述和代码结构索引，找出最可能包含 bug 的修复位置。

代码结构索引 (文件: 类/方法):
```
{index}
```

GitHub Issue 描述:
```
{issue}
```

要求:
1. 分析 issue 描述的根因, 判断哪些文件最相关
2. 输出 top-3 候选位置, 按可能性从高到低排列
3. 如果 bug 在类方法中, 给出 class_name; 如果是顶层函数, class_name 留空
4. 输出 JSON (不要其他文字):
{{"candidates": [{{"file": "相对路径", "function": "函数名", "class_name": "类名或空字符串", "reason": "一句话定位理由"}}, ...]}}
只输出 JSON。"""


def locate(api_key: str, base_url: str, model: str,
           repo_dir: str, issue: str, max_retries: int = 3) -> dict:
    """LLM 定位候选修复位置 (top-3). 空 content 自动重试."""
    import urllib.request
    index = scan_repo(repo_dir)
    prompt = LOCATOR_PROMPT.format(index=render_index(index)[:6000], issue=issue[:2000])

    last_raw = ""
    for attempt in range(max_retries):
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "你是代码定位专家。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        last_raw = content[:200]
        if not content:
            continue  # reasoning 吃掉全部 token, 重试
        # 提取 JSON
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            continue
        try:
            parsed = json.loads(content[start:end + 1])
            if "candidates" in parsed:
                return parsed
            # 兼容旧格式: 单候选 → 包装成 list
            return {"candidates": [parsed]}
        except json.JSONDecodeError:
            continue
    return {"candidates": [], "raw": last_raw, "retries": max_retries}


def main():
    parser = argparse.ArgumentParser(description="蛇群 SWE-bench 定位层")
    parser.add_argument("repo_dir", help="repo 目录")
    parser.add_argument("issue", help="issue 描述")
    parser.add_argument("--config", default=os.path.expanduser("~/.snakes_config.json"))
    args = parser.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    result = locate(
        cfg["api_key"], cfg["base_url"],
        cfg["models"].get("light_head", "deepseek-v4-flash"),
        args.repo_dir, args.issue,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
