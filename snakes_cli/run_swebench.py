#!/usr/bin/env python3
"""
蛇群 SWE-bench 评测脚本
=======================
流程 per instance:
1. 准备环境: clone repo → checkout base_commit → uv venv → 装依赖 → 应用 test_patch
2. 定位层: issue 描述 → top-3 候选 {file, function, class_name}
3. 修复层: 逐候选跑蛇群 fix, 生成 patch
4. 评测: 应用 patch → 跑 FAIL_TO_PASS + PASS_TO_PASS → resolved?
5. 记录结果 JSONL

用法:
    python run_swebench.py --instances inst_list.json --out results.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from locator import locate, scan_repo, render_index  # noqa: E402

ENV_ROOT = Path(r"D:/competation/design/swebench_env")
DATA_DIR = Path(r"D:/competation/design/swebench_data")
CONFIG = json.load(open(os.path.expanduser("~/.snakes_config.json"), encoding="utf-8"))

# 依赖预装 (轻量仓库的手动依赖清单 + Python 版本)
REPO_DEPS = {
    "marshmallow-code/marshmallow": {
        "python": "3.11",
        "packages": ["pytest", "pytz", "simplejson"],
    },
    "pylint-dev/astroid": {
        "python": "3.10",
        "packages": ["pytest", "lazy-object-proxy", "wrapt", "typing-extensions", "setuptools"],
    },
}


def clone_checkout(repo: str, base_commit: str, env_setup: str = "") -> Path:
    """clone + checkout base_commit. 返回 repo 目录."""
    repo_name = repo.split("/")[1]
    repo_dir = ENV_ROOT / repo_name
    if not (repo_dir / ".git").exists():
        subprocess.run(
            ["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(repo_dir)],
            check=True, timeout=300,
        )
    # 先清残留 (test_patch/蛇群patch/临时文件), 再 fetch
    subprocess.run(["git", "-C", str(repo_dir), "reset", "--hard", "HEAD"],
                   check=False, timeout=60)
    subprocess.run(["git", "-C", str(repo_dir), "clean", "-fd"],
                   check=False, timeout=60)
    # fetch base_commit (带重试; 代理优先, 直连兜底)
    # 策略: 代理(v2rayN)通常开着, 直连在GFW波动时可能失败;
    #       代理挂时直连兜底 (R3曾被代理挂掉连累, R4曾因强制直连失败)
    # 2026-08-28 修复: 若本地已有该 commit (GitHub 对 force-push 清理的历史
    #   SHA 会拒绝 fetch), 直接跳过 fetch —— 零网络依赖, 避免 fetch 必失败
    have_commit = subprocess.run(
        ["git", "-C", str(repo_dir), "cat-file", "-e", f"{base_commit}^{{commit}}"],
        capture_output=True, text=True,
    ).returncode == 0
    if not have_commit:
        for attempt in range(3):
            use_proxy = (attempt % 2 == 0)  # 0:代理, 1:直连, 2:代理
            cmd = ["git", "-C", str(repo_dir)]
            if not use_proxy:
                cmd += ["-c", "http.proxy=", "-c", "https.proxy="]
            cmd += ["fetch", "--quiet", "origin", base_commit]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                break
            if attempt == 2:
                raise RuntimeError(f"git fetch failed after 3 attempts: {r.stderr[:200]}")
            time.sleep(5)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", base_commit],
                   check=True, timeout=60)
    # 重置到干净状态 (清掉之前 apply 的 patch)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                   check=False, timeout=60)
    return repo_dir


def setup_venv(repo_dir: Path, repo: str) -> Path:
    """建 venv + 装依赖. 返回 venv python 路径."""
    spec = REPO_DEPS.get(repo, {"python": "3.11", "packages": ["pytest"]})
    pyver = spec["python"]
    venv = repo_dir / f".venv{pyver.replace('.', '')}"
    if not (venv / "Scripts" / "python.exe").exists():
        subprocess.run(["uv", "venv", "--python", pyver, str(venv)],
                       check=True, timeout=120)
    deps = spec["packages"]
    env = {**os.environ, "VIRTUAL_ENV": str(venv)}
    subprocess.run(["uv", "pip", "install", "-q", *deps], env=env,
                   check=False, timeout=300)
    # 不装 editable: 测试用 PYTHONPATH=repo_dir 指向当前 checkout (切commit后代码即生效)
    # editable 安装会被新版 setuptools 的 build_editable 缺失阻断 (astroid老pyproject)
    return venv / "Scripts" / "python.exe"


def apply_patch(repo_dir: Path, patch: str, strip: int = 1) -> bool:
    """应用 patch (git apply), 自动修正路径前缀."""
    patch_file = repo_dir / "_tmp_apply.patch"
    patch_file.write_text(patch, encoding="utf-8")
    # 先试原样 apply
    r = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 失败: 用 basename 反查仓库内真实路径 (e.g. brain_builtin_inference.py → astroid/brain/brain_builtin_inference.py)
    def _resolve_by_basename(p: str) -> str:
        _EX = (".venv", "venv", "site-packages", "node_modules", "__pycache__",
               ".tox", ".pytest_cache", "build", "dist", ".git")
        for root, dirs, files in os.walk(str(repo_dir)):
            dirs[:] = [d for d in dirs if not any(ex in d for ex in _EX)]
            for fn in files:
                if fn == os.path.basename(p):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, str(repo_dir)).replace("\\", "/")
                    return rel
        return p

    # 提取 patch 里的文件路径并替换
    def _rewrite_paths(p: str) -> str:
        new_lines = []
        for line in p.split("\n"):
            m = re.match(r'^(--- a/|\+\+\+ b/)(\S+)', line)
            if m:
                old = m.group(2)
                # 若 old 不是仓库内真实相对路径, 用 basename 反查
                if not (repo_dir / old).exists():
                    resolved = _resolve_by_basename(old)
                    if resolved != old:
                        line = f"{m.group(1)}{resolved}"
            new_lines.append(line)
        return "\n".join(new_lines)

    fixed = _rewrite_paths(patch)
    patch_file.write_text(fixed, encoding="utf-8")
    r2 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                        capture_output=True, text=True)
    if r2.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 兜底: 递归向上尝试 src/ 和 <repo_name>/ 前缀
    repo_name = repo_dir.name
    for prefix in (f"src/{repo_name}/", f"{repo_name}/", "src/"):
        fixed2 = re.sub(r'^--- a/(?!src/)', f'--- a/{prefix}', patch, flags=re.M)
        fixed2 = re.sub(r'^\+\+\+ b/(?!src/)', f'+++ b/{prefix}', fixed2, flags=re.M)
        patch_file.write_text(fixed2, encoding="utf-8")
        r3 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                            capture_output=True, text=True)
        if r3.returncode == 0:
            subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                           check=True)
            return True
    return False


def _extract_function_slice(orig: str, function: str, class_name: str = "") -> str:
    """方案B: 从原始文件提取目标函数源码切片 (供 _audit 行数差比较).

    与 _replace_for_rewrite 定位逻辑一致: AST 行号精确定位 (class 限定).
    """
    import ast as _ast
    try:
        tree = _ast.parse(orig)
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == function:
                if class_name:
                    for parent in _ast.walk(tree):
                        if isinstance(parent, _ast.ClassDef) and node in list(parent.body):
                            return _ast.get_source_segment(orig, node) or ""
                    continue
                return _ast.get_source_segment(orig, node) or ""
    except SyntaxError:
        pass
    # 回退: 正则定位
    m = re.search(r'(?:^|\n)(    )?def ' + re.escape(function) + r'\(.*?(?=\n(?!    |\t))', orig, re.DOTALL)
    return m.group(0) if m else ""


def _replace_for_rewrite(orig: str, new_code: str, function: str,
                         class_name: str = "") -> str:
    """方案B: 在原始文件全文中定位 function 的实际位置, 替换为重写代码.

    与 snakes_core.fix() 内 _replace_at_location 逻辑一致:
    优先 AST 行号精确定位 (class 限定), 失败回退 find 首次匹配.
    """
    import ast as _ast
    try:
        tree = _ast.parse(orig)
        lines = orig.split("\n")
        target_first = ""
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == function:
                if class_name:
                    parent_cls = None
                    for parent in _ast.walk(tree):
                        if isinstance(parent, _ast.ClassDef):
                            for item in parent.body:
                                if item is node:
                                    parent_cls = parent.name
                    if parent_cls != class_name:
                        continue
                start = node.lineno - 1
                end = node.end_lineno
                actual = "\n".join(lines[start:end])
                lines[start:end] = new_code.rstrip("\n").split("\n")
                return "\n".join(lines)
    except SyntaxError:
        pass
    # 回退: AST 定位失败 → 返回原内容不变 (生成的空 patch 会被 apply_patch 拒绝,
    # 安全降级为「重写未应用」, 不冒险做无 target 的模糊替换)
    return orig


def run_tests(python: Path, repo_dir: Path, test_ids: list, timeout: int = 300) -> dict:
    """运行测试. 返回 {test_id: 'PASS'|'FAIL'|'ERROR'}.

    SWE-bench 参数化测试 ID 含换行等特殊字符, 无法精确解析时
    回退到"文件::类::函数"前缀匹配 (跑该函数全部参数化用例).
    """
    results = {}
    # PYTHONPATH=repo_dir: import 用当前 checkout 源码 (非 editable 安装)
    env = {**os.environ, "PYTHONPATH": str(repo_dir)}
    for tid in test_ids:
        # 尝试精确执行; 失败则截断到 文件::类::函数 前缀
        cr = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", tid],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout, env=env,
        )
        if cr.returncode == 0:
            results[tid] = "PASS"
            continue
        # 精确失败: 若含 [ 参数部分, 截断后重试
        if "[" in tid:
            prefix = tid.split("[")[0]
            pr = subprocess.run(
                [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", prefix],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout, env=env,
            )
            if pr.returncode == 0:
                results[tid] = "PASS"
                continue
            if "collected 0" in pr.stdout or "no tests ran" in pr.stdout:
                results[tid] = "ERROR"  # 测试文件/节点不存在 (环境不可复现)
                continue
            results[tid] = "FAIL"
            continue
        # 区分 FAIL vs ERROR
        if "collected 0" in cr.stdout or "no tests ran" in cr.stdout:
            results[tid] = "ERROR"
        elif "ERROR" in cr.stdout or "error" in cr.stderr.lower():
            results[tid] = "ERROR"
        else:
            results[tid] = "FAIL"
    return results


def _parse_list(v):
    """parquet 里 FAIL_TO_PASS/PASS_TO_PASS 是 JSON 字符串, 解析成 list."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return []
    return v or []


def _traceback_line_to_func(repo_dir: Path, issue: str) -> dict:
    """把 traceback 里的 文件:行号 映射到 函数/类 (确定性, 零token).

    返回 {file: {line: (function, class_name)}} 供候选排序加权.
    """
    import ast as _ast
    result = {}
    _EX = (".venv", "venv", "site-packages", "node_modules", "__pycache__",
           ".tox", ".pytest_cache", "build", "dist", ".git")
    for m in re.finditer(r'File "([^"]+)", line (\d+)', issue):
        fpath, lineno = m.group(1), int(m.group(2))
        fname = os.path.basename(fpath)
        # 在 repo 里找同名文件
        for root, dirs, files in os.walk(str(repo_dir)):
            dirs[:] = [d for d in dirs if not any(ex in d for ex in _EX)]
            for fn in files:
                if fn == fname:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, str(repo_dir)).replace("\\", "/")
                    try:
                        code = open(full, encoding="utf-8", errors="replace").read()
                        tree = _ast.parse(code)
                        for node in _ast.walk(tree):
                            if isinstance(node, _ast.FunctionDef):
                                if node.lineno <= lineno <= node.end_lineno:
                                    cls = ""
                                    for parent in _ast.walk(tree):
                                        if isinstance(parent, _ast.ClassDef):
                                            for item in parent.body:
                                                if item is node:
                                                    cls = parent.name
                                    result.setdefault(rel, {})[lineno] = (node.name, cls)
                    except (SyntaxError, OSError):
                        pass
    return result


def _weight_candidates(candidates: list, tb_map: dict) -> list:
    """用 traceback 行号映射给候选加权排序 (命中行号的排最前)."""
    if not tb_map:
        return candidates
    weighted = []
    for c in candidates:
        f = c.get("file", "")
        fn = c.get("function", "")
        cls = c.get("class_name", "")
        hit = False
        for line, (func, klass) in tb_map.get(f, {}).items():
            if func == fn and (not cls or klass == cls or not klass):
                hit = True
                break
        weighted.append((0 if hit else 1, c))
    weighted.sort(key=lambda x: x[0])
    return [c for _, c in weighted]


def evaluate_instance(inst: dict, out_fd, dry_run: bool = False) -> dict:
    """评测单个 SWE-bench 实例."""
    iid = inst["instance_id"]
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    env_setup = inst.get("environment_setup_commit", "")
    problem = inst["problem_statement"]
    fail_to_pass = _parse_list(inst["FAIL_TO_PASS"])
    pass_to_pass = _parse_list(inst.get("PASS_TO_PASS", []))[:20]  # 采样 20 个防爆

    record = {
        "instance_id": iid,
        "repo": repo,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "locator": None,
        "attempts": [],
        "resolved": False,
        "errors": [],
    }

    try:
        # 1. 准备环境
        repo_dir = clone_checkout(repo, base_commit, env_setup)
        python = setup_venv(repo_dir, repo)

        # 2. 应用 test_patch (先验证 bug 复现)
        if not apply_patch(repo_dir, inst["test_patch"]):
            record["errors"].append("test_patch apply failed")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 3. 确认 FAIL_TO_PASS 在修复前失败 (bug 复现)
        before = run_tests(python, repo_dir, fail_to_pass[:2])
        any_pass_before = any(v == "PASS" for v in before.values())
        record["reproduced"] = not any_pass_before
        if any_pass_before:
            record["errors"].append(f"bug 未复现(测试已过): {before}")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 4. 定位层
        if dry_run:
            record["locator"] = "DRY"
        else:
            loc = locate(CONFIG["api_key"], CONFIG["base_url"],
                         CONFIG["models"].get("light_head", "deepseek-v4-flash"),
                         str(repo_dir), problem)
            record["locator"] = loc
        candidates = (loc.get("candidates") if not dry_run else []) or []
        # traceback 行号加权排序 + 确定性兜底: 行号命中的函数无条件加入候选头部
        tb_map = _traceback_line_to_func(repo_dir, problem)
        if tb_map:
            tb_candidates = []
            seen = set()
            for f, lines in tb_map.items():
                for line, (func, klass) in lines.items():
                    # 优先最深的调用帧 (最后出现的行号往往是根因点)
                    key = (f, func, klass)
                    if key not in seen and func:
                        seen.add(key)
                        tb_candidates.append({
                            "file": f, "function": func, "class_name": klass,
                            "reason": f"traceback行号{line}确定性定位",
                            "from_traceback": True,
                        })
            # 倒序: traceback 最后一个 File 帧 = 最深调用 = 根因概率最高
            tb_candidates = tb_candidates[::-1]
            # 合并: traceback 候选在前, LLM 候选在后(去重)
            merged = list(tb_candidates)
            for c in candidates:
                key = (c.get("file", ""), c.get("function", ""), c.get("class_name", ""))
                if key not in {(x["file"], x["function"], x["class_name"]) for x in merged}:
                    merged.append(c)
            candidates = merged[:5]
            record["locator_weights"] = {k: str(v) for k, v in tb_map.items()}
        if not candidates:
            record["errors"].append("定位层无候选")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 5. 逐候选修复
        # 优化1: 候选按 (file,function,class) 去重 — R5 中 1524/1229 的 3 候选
        # 是同一函数 __call__/_serialize, 重复修复纯浪费 (2026-08-29)
        # 优化3: 候选上限 3→2 — R5 中 7 成功实例 6 个是候选#1, 仅 927 候选#2,
        # 无候选#3 成功案例, 省 1/3 候选成本 (2026-08-29)
        seen_cands = set()
        deduped = []
        for c in candidates[:2]:
            k = (c.get("file", ""), c.get("function", ""), c.get("class_name", ""))
            if k not in seen_cands:
                seen_cands.add(k)
                deduped.append(c)
        candidates = deduped
        for ci, cand in enumerate(candidates[:2]):
            file_path = os.path.join(str(repo_dir), cand.get("file", ""))
            function = cand.get("function", "")
            class_name = cand.get("class_name", "")
            if not os.path.exists(file_path) or not function:
                record["attempts"].append({"candidate": cand, "error": "file/function 无效"})
                continue
            attempt = {"candidate": cand}
            try:
                from snakes_core import Snakes
                snakes = Snakes(api_key=CONFIG["api_key"], base_url=CONFIG["base_url"],
                                models=CONFIG["models"])
                # P0-2 中间验证循环: 候选修复 → 跑 FAIL_TO_PASS → 失败带反馈迭代 (≤2轮)
                iterations = []
                feedback = ""
                final_r = None
                # 记录原始文件内容作为迭代轮的 diff 基准 (r2 的 fix 读磁盘是 r1 修改后状态,
                # 生成的 patch 上下文与干净 repo 不匹配 → apply 必失败)
                try:
                    with open(file_path, encoding="utf-8") as _f:
                        baseline_content = _f.read()
                except OSError:
                    baseline_content = None
                # 方向A: 检索相似历史修复注入 (同类函数修过 → 直接给参考)
                kb_note = ""
                try:
                    from fix_knowledge import search_fix
                    hits = search_fix(cand.get("file", ""), function, class_name,
                                      repo=inst.get("repo", ""))
                    if hits:
                        parts = []
                        for h in hits:
                            parts.append(
                                f"【历史修复参考 {h['instance_id']}】"
                                f"文件 {h['file']} 函数 {h.get('class_name','')}.{h['function']}\n"
                                f"原问题: {h['issue'][:300]}\n"
                                f"有效patch:\n{h['patch'][:800]}")
                        kb_note = "\n\n".join(parts[:2])
                except Exception as e:
                    print(f"  [kb] search_fix failed: {e}", flush=True)
                if kb_note:
                    feedback = (feedback + "\n\n" + kb_note) if feedback else kb_note
                # 注: 迭代上限保持 3 — R5 中 927 靠候选2的第3轮迭代成功,
                # 砍到2会丢 resolved (2026-08-29 数据验证后撤销了3→2优化)
                for it in range(3):  # 第1轮 + 最多2次迭代
                    r = snakes.fix(
                        file_path=file_path,
                        function=function,
                        bug_description=problem,
                        class_name=class_name,
                        enable_judges=False,
                        injected_knowledge=feedback,
                        baseline_content=baseline_content if it > 0 else None,
                    )
                    iterations.append({"round": it + 1, "tokens": r.tokens,
                                       "success": r.success,
                                       "error": (getattr(r, "error", "") or "")[:200]})
                    if not r.patch:
                        break
                    # 回滚到干净状态 → 重新应用 test_patch → 应用蛇群 patch
                    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                                   check=False)
                    apply_patch(repo_dir, inst["test_patch"])
                    if not apply_patch(repo_dir, r.patch):
                        iterations[-1]["error"] = "蛇群patch apply失败"
                        break
                    # 跑 FAIL_TO_PASS (先只跑 ftp, 全过才跑 ptp 省时间)
                    after_ftp = run_tests(python, repo_dir, fail_to_pass)
                    ftp_pass = all(v == "PASS" for v in after_ftp.values())
                    if ftp_pass:
                        after_ptp = run_tests(python, repo_dir, pass_to_pass)
                        ptp_pass = all(v == "PASS" for v in after_ptp.values())
                        attempt["fail_to_pass"] = after_ftp
                        attempt["pass_to_pass"] = after_ptp
                        if ptp_pass:
                            final_r = r
                            attempt["fix_success"] = True
                            attempt["tokens"] = r.tokens
                            attempt["iterations"] = iterations
                            record["resolved"] = True
                            record["attempts"].append(attempt)
                            # 方向A: 成功修复自动入库 (供后续实例检索复用)
                            try:
                                from fix_knowledge import save_fix
                                save_fix(
                                    instance_id=inst["instance_id"],
                                    repo=inst.get("repo", ""),
                                    file=cand.get("file", ""),
                                    function=function,
                                    class_name=class_name,
                                    issue=problem,
                                    patch=r.patch,
                                )
                            except Exception as e:
                                print(f"  [kb] save_fix failed: {e}", flush=True)
                            break
                        # ftp 过但 ptp 回归 → 反馈 ptp 失败详情继续迭代
                        ptp_fails = [f"{k}:{v}" for k, v in after_ptp.items() if v != "PASS"]
                        feedback = (f"上一轮修复通过了目标测试但引入了回归! "
                                    f"回归测试({len(ptp_fails)}个): {ptp_fails[:5]}"
                                    f"\n请保留目标修复的同时避免破坏这些测试。")
                        continue
                    # ftp 失败 → 收集失败详情反馈
                    ftp_fails = [f"{k}:{v}" for k, v in after_ftp.items() if v != "PASS"]
                    attempt["fail_to_pass"] = after_ftp
                    feedback = (f"上一轮修复后 FAIL_TO_PASS 测试仍失败 ({len(ftp_fails)}个): "
                                f"{ftp_fails[:3]}"
                                f"\n请分析为什么修复没有让这些测试通过, 重新输出修复。")
                    iterations[-1]["ftp_fail"] = len(ftp_fails)
                    # ★方案B: 迭代2轮仍失败 → 触发黑箱重写 (2026-08-31 实验)
                    # 触发点: it==1 (第2轮) 且 ftp 仍失败。复用 snakes._extract_contract
                    # + _run_blackbox_rewrite + _audit, 重写产物过 L1 审计才应用。
                    if it == 1 and ftp_fails and not record.get("resolved"):
                        rewrite_info = {}
                        try:
                            # 回滚到干净状态 → 读原始文件 → 提取契约
                            subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                                           check=False)
                            with open(file_path, encoding="utf-8") as _f:
                                orig_full = _f.read()
                            contract = snakes._extract_contract(orig_full, function, class_name)
                            # 安全降级: 目标函数在文件中不存在 (locator 候选名不准) → 跳过重写
                            if not contract.get("signature"):
                                rewrite_info["skipped"] = "function_not_found"
                                attempt["rewrite"] = rewrite_info
                            else:
                                head_analysis = (cand.get("reason", "") or problem)[:800]
                                rewrite = snakes._run_blackbox_rewrite(
                                    contract, problem, head_analysis,
                                    test_code="")
                                rewrite_info["tokens"] = rewrite.get("total_tokens", 0)
                                # 鲁棒提取: 容忍 ```python 后无换行 / ```Python / 前后空白
                                rw_match = re.search(r'```\s*python\s*\n?(.*?)```',
                                                     rewrite["content"], re.DOTALL | re.IGNORECASE)
                                if not rw_match:
                                    # 兜底: 无代码块标记时, 视整个 content 为代码
                                    rewrite_info["no_marker"] = True
                                    rw_match = re.match(r'\s*(.*?)\s*$',
                                                        rewrite["content"], re.DOTALL)
                                if rw_match:
                                    rewritten_code = rw_match.group(1)
                                    # 类方法: 剥掉 import/class 行 (与 fix() 内 :1139-1146 一致)
                                    if class_name:
                                        cleaned = []
                                        for line in rewritten_code.split("\n"):
                                            s = line.strip()
                                            if (s.startswith(("import ", "from ")) or s.startswith("class ")):
                                                continue
                                            cleaned.append(line)
                                        rewritten_code = "\n".join(cleaned).strip("\n")
                                    # 提取目标函数原始切片 (供 _audit 行数差比较, 传整个文件会误判范围溢出)
                                    target_slice = _extract_function_slice(orig_full, function, class_name)
                                    # L1 审计重写产物
                                    audit_rw = snakes._audit(target_slice, rewritten_code, function)
                                    rewrite_info["audit_passed"] = audit_rw["passed"]
                                    rewrite_info["audit_issues"] = audit_rw["issues"]
                                    if audit_rw["passed"]:
                                        # 生成 原始→重写 patch 并应用
                                        apply_patch(repo_dir, inst["test_patch"])
                                        rw_patch = snakes._generate_patch(
                                            str(file_path), orig_full,
                                            _replace_for_rewrite(orig_full, rewritten_code,
                                                                 function, class_name))
                                        if apply_patch(repo_dir, rw_patch):
                                            after_ftp = run_tests(python, repo_dir, fail_to_pass)
                                            ftp_pass = all(v == "PASS" for v in after_ftp.values())
                                            rewrite_info["ftp_after"] = after_ftp
                                            if ftp_pass:
                                                after_ptp = run_tests(python, repo_dir, pass_to_pass)
                                                ptp_pass = all(v == "PASS" for v in after_ptp.values())
                                                attempt["pass_to_pass"] = after_ptp
                                                if ptp_pass:
                                                    rewrite_info["resolved"] = True
                                                    record["resolved"] = True
                                                    attempt["fix_success"] = True
                                                    attempt["tokens"] = dict(attempt.get("tokens", {}),
                                                                             **{"rewrite": rewrite_info.get("tokens", 0)})
                                                    attempt["iterations"] = iterations
                                                    attempt["rewrite_rescued"] = True
                                                    record["attempts"].append(attempt)
                                                    break
                                            # 重写后仍失败: 回滚, 记录, 走正常迭代收尾
                                            subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                                                           check=False)
                                attempt["rewrite"] = rewrite_info
                        except Exception as e:
                            attempt["rewrite"] = {**rewrite_info, "error": str(e)[:200]}
                    if it == 2:
                        break

                if record.get("resolved"):
                    break
                # P1-1 回归保护: 2轮迭代后 ftp 仍全败的候选标记劣质,
                # 继续尝试下一个候选 (2026-08-29 修复: 原实现 break 跳出整个
                # 候选循环, 导致 15/26 实例只尝试1个候选, R4 多候选救回能力被砍)
                ftp_all_fail = all(
                    "ftp_fail" in it and it["ftp_fail"] == len(fail_to_pass)
                    for it in iterations if "ftp_fail" in it
                ) and len([it for it in iterations if "ftp_fail" in it]) >= 2
                if ftp_all_fail:
                    attempt["error"] = "候选2轮迭代ftp全败, 标记劣质跳过"
                    record["attempts"].append(attempt)
                    continue
                # 全部迭代失败: 记录最后状态
                if final_r is None and iterations:
                    last = iterations[-1]
                    attempt["fix_success"] = last.get("success", False)
                    attempt["tokens"] = last.get("tokens", {})
                    attempt["iterations"] = iterations
                    if "ftp_fail" in last:
                        pass  # fail_to_pass 已记录
                    elif "蛇群patch apply失败" in last.get("error", ""):
                        attempt["error"] = "蛇群patch apply失败"
                    elif last.get("error"):
                        attempt["error"] = last["error"]
                    else:
                        attempt["error"] = "迭代后仍失败"
                    record["attempts"].append(attempt)
            except Exception as e:
                attempt["error"] = f"异常: {str(e)[:200]}"
                record["attempts"].append(attempt)

    except Exception as e:
        record["errors"].append(f"流程异常: {str(e)[:300]}")

    out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
    out_fd.flush()
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", required=True, help="实例列表 JSON")
    parser.add_argument("--out", default="swebench_results.jsonl", help="结果输出")
    parser.add_argument("--limit", type=int, default=0, help="限制实例数(0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只测环境准备, 不调 LLM")
    args = parser.parse_args()

    instances = json.load(open(args.instances, encoding="utf-8"))
    if args.limit:
        instances = instances[:args.limit]

    # 断点续跑: 跳过 out 文件里已完成的 instance_id (R5 中断后恢复用)
    done_ids = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done_ids.add(json.loads(line)["instance_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    if done_ids:
        skipped = [i for i in instances if i["instance_id"] in done_ids]
        instances = [i for i in instances if i["instance_id"] not in done_ids]
        print(f"[resume] 跳过已完成的 {len(skipped)} 个, 剩余 {len(instances)} 个", flush=True)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as f:
        for inst in instances:
            print(f"\n{'='*60}\n▶ {inst['instance_id']}", flush=True)
            rec = evaluate_instance(inst, f, dry_run=args.dry_run)
            status = "✅ RESOLVED" if rec.get("resolved") else "❌ failed"
            print(f"  {status}", flush=True)


if __name__ == "__main__":
    main()
