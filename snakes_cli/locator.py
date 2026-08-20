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
                    methods = []
                    for m in node.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            # 预览方法体 (最多 12 行), 辅助定位
                            src_lines = code.split("\n")
                            body = "\n".join(src_lines[m.lineno - 1:m.end_lineno])
                            methods.append({
                                "name": m.name,
                                "preview": body[:500],
                            })
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
            methods = ", ".join(m["name"] for m in cls["methods"][:15])
            parts.append(f"  class {cls['name']}: {methods}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def render_method_details(index: dict, file: str, max_classes: int = 4) -> str:
    """渲染指定文件里各 class 方法体预览 (定位辅助)."""
    info = index.get(file)
    if not info:
        return ""
    out = []
    for cls in info["classes"][:max_classes]:
        for m in cls["methods"]:
            out.append(f"--- {file} :: {cls['name']}.{m['name']} ---")
            out.append(m["preview"])
    return "\n".join(out)


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
2. **优先关注 issue 中 traceback 提到的文件和行号** (如果有)
3. 输出 top-3 候选位置, 按可能性从高到低排列
4. 如果 bug 在类方法中, 给出 class_name; 如果是顶层函数, class_name 留空
5. 输出 JSON (不要其他文字):
{{"candidates": [{{"file": "相对路径", "function": "函数名", "class_name": "类名或空字符串", "reason": "一句话定位理由"}}, ...]}}
只输出 JSON。"""


def traceback_hint(issue: str) -> str:
    """从 issue 提取 traceback 中的文件/行号线索 (确定性, 零token)."""
    lines = issue.split("\n")
    out = []
    for ln in lines:
        if 'File "' in ln and 'line ' in ln:
            out.append(ln.strip())
        if 'Error:' in ln or 'error:' in ln.lower():
            out.append(ln.strip())
    return "\n".join(out[:8])

LOCATOR_PROMPT_V2 = """你是代码定位专家。给定一个 GitHub issue 描述和一个候选文件的方法体预览，找出 bug 的精确定位。

候选文件方法体预览:
```
{details}
```

GitHub Issue 描述:
```
{issue}
```

要求:
1. 仔细阅读方法体预览, 找出真正包含 bug 的那个方法
2. 注意: issue 描述可能提到容器/外层组件, 但根因常在被调用的内部组件里
3. 输出 top-3 候选位置 (文件+函数+class), 按可能性排序
4. 输出 JSON (不要其他文字):
{{"candidates": [{{"file": "相对路径", "function": "函数名", "class_name": "类名或空字符串", "reason": "一句话定位理由"}}, ...]}}
只输出 JSON。"""


def _call_llm(api_key: str, base_url: str, model: str, prompt: str,
              max_retries: int = 3) -> str:
    """调用 LLM 返回 content (空 content 重试)."""
    import urllib.request
    last_raw = ""
    for _ in range(max_retries):
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
        if content:
            return content
    return last_raw


def _parse_candidates(content: str) -> list:
    """从 LLM 输出提取候选列表."""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        parsed = json.loads(content[start:end + 1])
        if "candidates" in parsed:
            return parsed["candidates"]
        if isinstance(parsed, dict) and "file" in parsed:
            return [parsed]
        return []
    except json.JSONDecodeError:
        return []


def locate(api_key: str, base_url: str, model: str,
           repo_dir: str, issue: str, max_retries: int = 3) -> dict:
    """两阶段 LLM 定位: 全索引粗定位 → 候选文件方法体预览细定位."""
    index = scan_repo(repo_dir)
    tb = traceback_hint(issue)
    tb_note = f"\n\nTraceback 线索 (确定性提取):\n{tb}" if tb else ""
    prompt = LOCATOR_PROMPT.format(index=render_index(index)[:6000],
                                   issue=(issue + tb_note)[:4000])
    content = _call_llm(api_key, base_url, model, prompt, max_retries)
    candidates = _parse_candidates(content)

    # 阶段2: 对 top 候选文件渲染方法体预览, 精确定位 (结果与阶段1合并)
    if candidates:
        top_file = candidates[0].get("file", "")
        details = render_method_details(index, top_file)
        if details:
            prompt2 = LOCATOR_PROMPT_V2.format(details=details[:6000], issue=issue[:2000])
            content2 = _call_llm(api_key, base_url, model, prompt2, max_retries)
            refined = _parse_candidates(content2)
            if refined:
                # 合并去重 (按 file+function+class 去重)
                seen = set()
                merged = []
                for c in candidates + refined:
                    key = (c.get("file", ""), c.get("function", ""), c.get("class_name", ""))
                    if key not in seen and c.get("function"):
                        seen.add(key)
                        merged.append(c)
                return {"candidates": merged[:4], "stage2": True, "top_file": top_file}
    return {"candidates": candidates, "stage2": False}


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
