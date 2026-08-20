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

# 依赖预装 (轻量仓库的手动依赖清单)
REPO_DEPS = {
    "marshmallow-code/marshmallow": ["pytest", "pytz", "simplejson"],
    "pylint-dev/astroid": ["pytest", "lazy-object-proxy", "wrapt", "typing-extensions", "setuptools"],
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
    # fetch + checkout base_commit
    subprocess.run(["git", "-C", str(repo_dir), "fetch", "--quiet", "origin", base_commit],
                   check=True, timeout=120)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", base_commit],
                   check=True, timeout=60)
    # 重置到干净状态 (清掉之前 apply 的 patch)
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                   check=False, timeout=60)
    return repo_dir


def setup_venv(repo_dir: Path, repo: str) -> Path:
    """建 venv + 装依赖. 返回 venv python 路径."""
    venv = repo_dir / ".venv"
    if not (venv / "Scripts" / "python.exe").exists():
        subprocess.run(["uv", "venv", "--python", "3.11", str(venv)],
                       check=True, timeout=120)
    deps = REPO_DEPS.get(repo, ["pytest"])
    env = {**os.environ, "VIRTUAL_ENV": str(venv)}
    subprocess.run(["uv", "pip", "install", "-q", *deps], env=env,
                   check=False, timeout=300)
    # editable install 包本身 (如果存在 setup.py/pyproject)
    if (repo_dir / "setup.py").exists() or (repo_dir / "pyproject.toml").exists():
        subprocess.run(["uv", "pip", "install", "-q", "-e", "."], env=env,
                       cwd=str(repo_dir), check=False, timeout=300)
    return venv / "Scripts" / "python.exe"


def apply_patch(repo_dir: Path, patch: str, strip: int = 1) -> bool:
    """应用 patch (git apply), 自动修正路径前缀."""
    # 修正路径: 若 a/ 后面没有仓库相对路径前缀, 尝试加 src/<repo>/
    patch_file = repo_dir / "_tmp_apply.patch"
    patch_file.write_text(patch, encoding="utf-8")
    # 先试原样 apply
    r = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 失败: 尝试把 a/xxx.py → a/src/<repo>/xxx.py (相对路径丢失场景)
    fixed = patch
    fixed = re.sub(r'^--- a/(?!src/)', '--- a/src/', fixed, flags=re.M)
    fixed = re.sub(r'^\+\+\+ b/(?!src/)', '+++ b/src/', fixed, flags=re.M)
    patch_file.write_text(fixed, encoding="utf-8")
    r2 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                        capture_output=True, text=True)
    if r2.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    # 再试: src/<repo>/ 前缀 (e.g. src/marshmallow/fields.py)
    repo_name = repo_dir.name
    fixed2 = re.sub(r'^--- a/(?!src/)', f'--- a/src/{repo_name}/', patch, flags=re.M)
    fixed2 = re.sub(r'^\+\+\+ b/(?!src/)', f'+++ b/src/{repo_name}/', fixed2, flags=re.M)
    patch_file.write_text(fixed2, encoding="utf-8")
    r3 = subprocess.run(["git", "-C", str(repo_dir), "apply", "--check", str(patch_file)],
                        capture_output=True, text=True)
    if r3.returncode == 0:
        subprocess.run(["git", "-C", str(repo_dir), "apply", str(patch_file)],
                       check=True)
        return True
    return False


def run_tests(python: Path, repo_dir: Path, test_ids: list, timeout: int = 300) -> dict:
    """运行测试. 返回 {test_id: 'PASS'|'FAIL'|'ERROR'}."""
    results = {}
    # pytest 一次跑所有 test_ids
    cmd = [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", *test_ids]
    r = subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout)
    # 解析 pytest 输出
    # 简单方案: 逐 test_id 单独跑 (慢但可靠, 先做正确性)
    for tid in test_ids:
        cr = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--no-header", "--tb=no", tid],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=timeout,
        )
        if cr.returncode == 0:
            results[tid] = "PASS"
        else:
            # 区分 FAIL vs ERROR
            if "ERROR" in cr.stdout or "error" in cr.stderr.lower():
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
    for m in re.finditer(r'File "([^"]+)", line (\d+)', issue):
        fpath, lineno = m.group(1), int(m.group(2))
        fname = os.path.basename(fpath)
        # 在 repo 里找同名文件
        for root, dirs, files in os.walk(str(repo_dir)):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "venv", "__pycache__")]
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
        # traceback 行号加权排序
        tb_map = _traceback_line_to_func(repo_dir, problem)
        if tb_map and candidates:
            candidates = _weight_candidates(candidates, tb_map)
            record["locator_weights"] = {k: str(v) for k, v in tb_map.items()}
        if not candidates:
            record["errors"].append("定位层无候选")
            out_fd.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fd.flush()
            return record

        # 5. 逐候选修复
        for ci, cand in enumerate(candidates[:3]):
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
                r = snakes.fix(
                    file_path=file_path,
                    function=function,
                    bug_description=problem,
                    class_name=class_name,
                    enable_judges=False,
                )
                attempt["fix_success"] = r.success
                attempt["tokens"] = r.tokens
                if not r.patch:
                    attempt["error"] = (getattr(r, "error", "") or "无patch输出")[:300]
                    record["attempts"].append(attempt)
                    continue

                # 回滚 test_patch 之前的修复尝试? 不行——每候选都是独立 fix,
                # 但 repo 状态会被上一个候选污染. 这里用 git checkout 恢复.
                subprocess.run(["git", "-C", str(repo_dir), "checkout", "--quiet", "--", "."],
                               check=False)
                # 重新应用 test_patch (被 checkout 清掉了)
                apply_patch(repo_dir, inst["test_patch"])

                # 应用蛇群 patch
                if not apply_patch(repo_dir, r.patch):
                    attempt["error"] = "蛇群patch apply失败"
                    attempt["patch"] = r.patch[:300]
                    record["attempts"].append(attempt)
                    continue

                # 评测: FAIL_TO_PASS + PASS_TO_PASS 采样
                after_ftp = run_tests(python, repo_dir, fail_to_pass)
                after_ptp = run_tests(python, repo_dir, pass_to_pass)
                ftp_pass = all(v == "PASS" for v in after_ftp.values())
                ptp_pass = all(v == "PASS" for v in after_ptp.values())
                attempt["fail_to_pass"] = after_ftp
                attempt["pass_to_pass"] = after_ptp
                if ftp_pass and ptp_pass:
                    record["resolved"] = True
                    record["attempts"].append(attempt)
                    break
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

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as f:
        for inst in instances:
            print(f"\n{'='*60}\n▶ {inst['instance_id']}", flush=True)
            rec = evaluate_instance(inst, f, dry_run=args.dry_run)
            status = "✅ RESOLVED" if rec.get("resolved") else "❌ failed"
            print(f"  {status}", flush=True)


if __name__ == "__main__":
    main()
