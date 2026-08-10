"""
蛇群 v0.3 P0 实验运行器
用法: python runner.py --mode [baseline|hetero|full] --cases [case1,case2,...|all]

模式:
  baseline  - 强模型基线：claude-sonnet-5 单法官审查
  hetero    - 异构三法官：2x DeepSeek + 1x Gemini
  full      - 全链路：蛇头分析 + 异构三法官（v0.3 完整模拟）

输出: results/{mode}_{timestamp}.json
"""
import json
import os
import sys
import time
import argparse
from datetime import datetime
from test_cases import TEST_CASES, PRE_TESTED_CASES, UNTESTED_CASES

# ============================================================
# 配置
# ============================================================
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Tokeness API 配置（从环境变量或 Hermes 配置读取）
TOKENESS_BASE = os.environ.get("TOKENESS_BASE", "https://api.tokeness.ai/v1")
TOKENESS_KEY = os.environ.get("TOKENESS_KEY", "")

# 模型配置
MODELS = {
    "claude-sonnet-5": "claude-sonnet-5",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "gemini-3.6-flash": "gemini-3.6-flash",
}

# 异构法官配置
HETERO_JUDGES = [
    {"model": "deepseek-v4-pro", "temp": 0.3},
    {"model": "deepseek-v4-pro", "temp": 0.7},
    {"model": "gemini-3.6-flash", "temp": 0.3},
]


# ============================================================
# 构建 Prompt
# ============================================================

def build_judge_prompt(case, include_snake_head=False):
    """构建法官审查 prompt"""
    task = case["task"]
    code = case["buggy_code"]
    
    if include_snake_head and "snake_head_analysis" in case:
        analysis = case["snake_head_analysis"]
        return f"""你是一位严格的代码审查员。以下是蛇头（任务规划层）的分析和蛇身（执行层）生成的代码。请审查代码是否正确。

【任务】
{task}

【蛇头分析】
{analysis}

【蛇身代码】
```python
{code}
```

请逐行审查代码，找出所有 bug。对每个 bug 说明：
1. 什么错误
2. 为什么是错误（给出反例）
3. 如何修复

最后给出判决：PASS（代码正确）或 FAIL（存在 bug）。

输出格式：
```
判决: [PASS/FAIL]
Bug 1: ...
Bug 2: ...
```"""
    
    return f"""你是一位严格的代码审查员。请审查以下代码是否正确。

【任务】
{task}

【代码】
```python
{code}
```

请逐行审查代码，找出所有 bug。对每个 bug 说明：
1. 什么错误
2. 为什么是错误（给出反例或具体场景）
3. 如何修复

最后给出判决：PASS（代码正确）或 FAIL（存在 bug）。

输出格式：
```
判决: [PASS/FAIL]
Bug 1: ...
Bug 2: ...
```"""


def build_snake_head_prompt(case):
    """构建蛇头分析 prompt（用于全链路模式）"""
    return f"""你是一位资深软件架构师。请分析以下任务，制定执行计划。

【任务】
{case['task']}

请输出：
1. 任务分解（步骤列表）
2. 每步的风险点
3. 不确定性标记

输出格式：
```
任务分解:
1. ...
2. ...

风险点:
- ...

不确定性: [低/中/高]
```"""


def build_deep_dive_prompt(case, minority_review, majority_verdict):
    """构建深挖 prompt"""
    return f"""你是深度调查法官。多数派判决为 {majority_verdict}，但有一位少数派法官持不同意见。

【少数派审查意见】
{minority_review}

【原任务】
{case['task']}

【被审查代码】
```python
{case['buggy_code']}
```

请独立判断少数派意见是否正确：
1. 复现少数派提出的具体场景
2. 判断少数派的推理是否有效
3. 给出最终结论：VALID（少数派正确）或 INVALID（少数派错误）

输出格式：
```
深挖结论: [VALID/INVALID]
理由: ...
```"""


# ============================================================
# API 调用（通过 hermes_tools）
# ============================================================

def call_llm(prompt, model="claude-sonnet-5", temperature=0.3, max_tokens=2000):
    """
    通过终端调用 LLM。
    在 Hermes 环境中，通过 execute_code 的 terminal() 调用。
    在独立 Python 环境中，使用 requests 直接调用 API。
    """
    # 尝试导入 hermes_tools（在 execute_code 中可用）
    try:
        from hermes_tools import terminal
        # 构建一个完整的 curl 命令或 Python 调用
        # 直接使用 Python requests 在 execute_code 中也可用
    except ImportError:
        pass
    
    # 通用实现：使用 subprocess 调用 curl
    import subprocess
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    curl_cmd = [
        "curl", "-s", f"{TOKENESS_BASE}/chat/completions",
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {TOKENESS_KEY}",
        "-d", json.dumps(payload),
        "--connect-timeout", "30",
        "--max-time", "120",
    ]
    
    result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=130)
    
    if result.returncode != 0:
        return {"error": f"curl failed: {result.stderr}", "raw": result.stdout}
    
    try:
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "tokens": usage.get("total_tokens", 0),
            "model": data.get("model", model),
        }
    except (json.JSONDecodeError, KeyError) as e:
        return {"error": str(e), "raw": result.stdout[:500]}


def parse_verdict(content):
    """从 LLM 回复中解析判决"""
    content_upper = content.upper()
    
    # 查找判决行
    for line in content.split("\n"):
        line_upper = line.strip().upper()
        if "判决" in line_upper or "VERDICT" in line_upper or "结论" in line_upper:
            if "FAIL" in line_upper or "失败" in line_upper or "有" in line_upper:
                return "FAIL"
            elif "PASS" in line_upper or "通过" in line_upper or "正确" in line_upper or "无" in line_upper:
                return "PASS"
    
    # 回退：全文搜索
    if "判决: FAIL" in content_upper or "判决：FAIL" in content_upper:
        return "FAIL"
    if "判决: PASS" in content_upper or "判决：PASS" in content_upper:
        return "PASS"
    
    # 进一步回退：数 bug 数量
    bug_count = content_upper.count("BUG ")
    bug_count += content_upper.count("BUG:")
    bug_count += content_upper.count("错误")
    bug_count += content_upper.count("漏洞")
    
    if bug_count > 0:
        return "FAIL"
    
    return "PASS"  # 默认为通过


# ============================================================
# 实验模式
# ============================================================

def run_baseline(cases, model="claude-sonnet-5"):
    """强模型基线：单法官审查"""
    results = []
    
    for case in cases:
        print(f"\n{'='*60}")
        print(f"[baseline] {case['id']}: {case['title']}")
        print(f"  GT={case['ground_truth']}, Model={model}")
        
        prompt = build_judge_prompt(case, include_snake_head=False)
        
        t0 = time.time()
        response = call_llm(prompt, model=model, temperature=0.3)
        latency = time.time() - t0
        
        if "error" in response:
            print(f"  ❌ API错误: {response['error']}")
            results.append({
                "case": case["id"],
                "config": f"baseline-{model}",
                "verdict": "ERROR",
                "tokens": 0,
                "latency": latency,
                "error": response["error"],
            })
            continue
        
        verdict = parse_verdict(response["content"])
        correct = (verdict == case["ground_truth"])
        status = "✅" if correct else "❌"
        
        print(f"  {status} 判决={verdict}, GT={case['ground_truth']}, tokens={response['tokens']}, latency={latency:.1f}s")
        
        results.append({
            "case": case["id"],
            "error_type": case["error_type"],
            "config": f"baseline-{model}",
            "verdict": verdict,
            "ground_truth": case["ground_truth"],
            "correct": correct,
            "tokens": response["tokens"],
            "latency": round(latency, 1),
            "review": response["content"][:500],
        })
        
        time.sleep(1)  # 速率限制
    
    return results


def run_hetero(cases):
    """异构三法官：2x DeepSeek + 1x Gemini + 深挖"""
    results = []
    
    for case in cases:
        print(f"\n{'='*60}")
        print(f"[hetero] {case['id']}: {case['title']}")
        print(f"  GT={case['ground_truth']}")
        
        prompt = build_judge_prompt(case, include_snake_head=False)
        
        # 三法官并行审查
        judges = []
        total_tokens = 0
        total_latency = 0
        
        for j, judge_config in enumerate(HETERO_JUDGES):
            model = judge_config["model"]
            temp = judge_config["temp"]
            
            print(f"  法官{j+1}: {model} (t={temp})...", end=" ", flush=True)
            
            t0 = time.time()
            response = call_llm(prompt, model=model, temperature=temp)
            latency = time.time() - t0
            
            if "error" in response:
                print(f"❌ {response['error']}")
                judges.append({"model": model, "verdict": "ERROR", "tokens": 0, "latency": latency})
                continue
            
            verdict = parse_verdict(response["content"])
            judges.append({
                "model": model,
                "temp": temp,
                "verdict": verdict,
                "review": response["content"],
                "tokens": response["tokens"],
                "latency": round(latency, 1),
            })
            total_tokens += response["tokens"]
            total_latency += latency
            
            print(f"{verdict} ({response['tokens']}t, {latency:.1f}s)")
            
            time.sleep(0.5)
        
        # 统计投票
        votes = [j["verdict"] for j in judges if j["verdict"] != "ERROR"]
        fail_count = votes.count("FAIL")
        pass_count = votes.count("PASS")
        
        print(f"  投票: FAIL={fail_count}, PASS={pass_count}")
        
        # 深挖逻辑
        deep_dive = None
        final_verdict = None
        
        if fail_count == 3:
            # 3:0 — 全票 FAIL
            final_verdict = "FAIL"
            print(f"  3:0 → 全票 FAIL")
        elif pass_count == 3:
            # 0:3 — 全票 PASS
            final_verdict = "PASS"
            print(f"  0:3 → 全票 PASS")
        elif fail_count >= 2:
            # 2:1 — 多数 FAIL，少数派深挖
            minority = [j for j in judges if j["verdict"] == "PASS"][0]
            print(f"  2:1 → 多数 FAIL，深挖少数派(PASS)...")
            
            dd_prompt = build_deep_dive_prompt(case, minority["review"], "FAIL")
            t0 = time.time()
            dd_response = call_llm(dd_prompt, model="deepseek-v4-pro", temperature=0.3)
            dd_latency = time.time() - t0
            
            if "error" not in dd_response:
                dd_verdict = "VALID" if "VALID" in dd_response["content"].upper() else "INVALID"
            else:
                dd_verdict = "ERROR"
            
            deep_dive = {"valid": dd_verdict == "VALID", "tokens": dd_response.get("tokens", 0)}
            total_tokens += dd_response.get("tokens", 0)
            total_latency += dd_latency
            
            final_verdict = "PASS" if dd_verdict == "VALID" else "FAIL"
            print(f"  深挖: {dd_verdict} → 最终: {final_verdict}")
        elif pass_count >= 2:
            # 1:2 — 多数 PASS，少数派深挖
            minority = [j for j in judges if j["verdict"] == "FAIL"][0]
            print(f"  1:2 → 多数 PASS，深挖少数派(FAIL)...")
            
            dd_prompt = build_deep_dive_prompt(case, minority["review"], "PASS")
            t0 = time.time()
            dd_response = call_llm(dd_prompt, model="deepseek-v4-pro", temperature=0.3)
            dd_latency = time.time() - t0
            
            if "error" not in dd_response:
                dd_verdict = "VALID" if "VALID" in dd_response["content"].upper() else "INVALID"
            else:
                dd_verdict = "ERROR"
            
            deep_dive = {"valid": dd_verdict == "VALID", "tokens": dd_response.get("tokens", 0)}
            total_tokens += dd_response.get("tokens", 0)
            total_latency += dd_latency
            
            final_verdict = "FAIL" if dd_verdict == "VALID" else "PASS"
            print(f"  深挖: {dd_verdict} → 最终: {final_verdict}")
        else:
            # 1:1:1 — 上抛
            final_verdict = "DEADLOCK"
            print(f"  1:1:1 → 死锁，上抛中央")
        
        correct = (final_verdict == case["ground_truth"])
        status = "✅" if correct else "❌"
        
        results.append({
            "case": case["id"],
            "error_type": case["error_type"],
            "config": "v0.3-hetero",
            "judges": [{k: v for k, v in j.items() if k != "review"} for j in judges],
            "votes": votes,
            "fail_count": fail_count,
            "final_verdict": final_verdict,
            "ground_truth": case["ground_truth"],
            "correct": correct,
            "total_tokens": total_tokens,
            "total_latency": round(total_latency, 1),
            "deep_dive": deep_dive,
        })
        
        print(f"  {status} 最终={final_verdict}, GT={case['ground_truth']}, tokens={total_tokens}")
        
        time.sleep(1)
    
    return results


# ============================================================
# 分析与报告
# ============================================================

def analyze_results(results):
    """分析实验结果"""
    total = len(results)
    correct = sum(1 for r in results if r.get("correct", False))
    errors = sum(1 for r in results if r.get("verdict") == "ERROR" or r.get("final_verdict") == "ERROR")
    
    # 按配置分组
    configs = {}
    for r in results:
        cfg = r.get("config", "unknown")
        if cfg not in configs:
            configs[cfg] = {"total": 0, "correct": 0, "tokens": 0, "latency": 0}
        configs[cfg]["total"] += 1
        if r.get("correct", False):
            configs[cfg]["correct"] += 1
        configs[cfg]["tokens"] += r.get("total_tokens", r.get("tokens", 0))
        configs[cfg]["latency"] += r.get("total_latency", r.get("latency", 0))
    
    # 按错误类型分组
    by_type = {}
    for r in results:
        etype = r.get("error_type", "unknown")
        if etype not in by_type:
            by_type[etype] = {"total": 0, "correct": 0}
        by_type[etype]["total"] += 1
        if r.get("correct", False):
            by_type[etype]["correct"] += 1
    
    return {
        "summary": {
            "total_cases": total,
            "correct": correct,
            "detection_rate": f"{correct}/{total} = {correct/total*100:.0f}%" if total > 0 else "N/A",
            "errors": errors,
        },
        "by_config": configs,
        "by_error_type": by_type,
    }


def print_report(results, analysis):
    """打印实验报告"""
    s = analysis["summary"]
    
    print("\n" + "=" * 70)
    print("  P0 实验报告")
    print("=" * 70)
    print(f"\n总用例数: {s['total_cases']}")
    print(f"正确检出: {s['correct']}")
    print(f"检出率:   {s['detection_rate']}")
    print(f"API错误:  {s['errors']}")
    
    print(f"\n--- 按配置 ---")
    for cfg, stats in analysis["by_config"].items():
        rate = f"{stats['correct']}/{stats['total']} = {stats['correct']/stats['total']*100:.0f}%"
        avg_tokens = stats['tokens'] / stats['total'] if stats['total'] > 0 else 0
        avg_latency = stats['latency'] / stats['total'] if stats['total'] > 0 else 0
        print(f"  {cfg}: {rate} | avg {avg_tokens:.0f}t, {avg_latency:.1f}s")
    
    print(f"\n--- 按错误类型 ---")
    for etype, stats in analysis["by_error_type"].items():
        rate = f"{stats['correct']}/{stats['total']} = {stats['correct']/stats['total']*100:.0f}%"
        print(f"  {etype}: {rate}")
    
    # 逐用例
    print(f"\n--- 逐用例 ---")
    for r in results:
        vid = r.get("case", "?")
        cfg = r.get("config", "?")
        verdict = r.get("final_verdict", r.get("verdict", "?"))
        gt = r.get("ground_truth", "?")
        ok = "✅" if r.get("correct", False) else "❌"
        tokens = r.get("total_tokens", r.get("tokens", 0))
        print(f"  {ok} {vid:6s} | {cfg:20s} | 判决={verdict} GT={gt} | {tokens}t")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="蛇群 v0.3 P0 实验运行器")
    parser.add_argument("--mode", choices=["baseline", "hetero", "full", "dry-run"],
                        default="dry-run", help="实验模式")
    parser.add_argument("--cases", type=str, default="all",
                        help="用例列表（逗号分隔）或 'all'/'untested'/'pretested'")
    parser.add_argument("--model", type=str, default="claude-sonnet-5",
                        help="基线模型（仅 baseline 模式）")
    args = parser.parse_args()
    
    # 选择用例
    if args.cases == "all":
        selected = TEST_CASES
    elif args.cases == "untested":
        selected = [c for c in TEST_CASES if c["id"] in UNTESTED_CASES]
    elif args.cases == "pretested":
        selected = [c for c in TEST_CASES if c["id"] in PRE_TESTED_CASES]
    else:
        case_ids = [x.strip() for x in args.cases.split(",")]
        selected = [c for c in TEST_CASES if c["id"] in case_ids]
    
    if not selected:
        print("错误：未找到匹配的用例")
        sys.exit(1)
    
    print(f"实验模式: {args.mode}")
    print(f"用例数: {len(selected)}")
    print(f"用例: {[c['id'] for c in selected]}")
    
    if args.mode == "dry-run":
        print("\n[dry-run] 仅预览，不实际调用 API。")
        for case in selected:
            print(f"\n  {case['id']}: {case['title']}")
            print(f"    类型={case['error_type']}, Z={case['z_score']}, V={case['value']}")
            print(f"    GT={case['ground_truth']}")
        return
    
    # 检查 API Key
    if not TOKENESS_KEY or TOKENESS_KEY == "":
        print("\n⚠️  未设置 TOKENESS_KEY 环境变量")
        print("请设置: export TOKENESS_KEY='your-key-here'")
        print("或在 Hermes 环境中通过 execute_code 运行")
        print("\n当前以 dry-run 模式预览。")
        return
    
    # 运行实验
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if args.mode == "baseline":
        results = run_baseline(selected, model=args.model)
    elif args.mode == "hetero":
        results = run_hetero(selected)
    elif args.mode == "full":
        print("全链路模式尚未实现")
        return
    
    # 分析
    analysis = analyze_results(results)
    print_report(results, analysis)
    
    # 保存结果
    output_path = os.path.join(RESULTS_DIR, f"{args.mode}_{timestamp}.json")
    
    # 合并已有 P0-前置A/B 结果（如果是异构模式且仅测了新用例）
    if args.mode == "hetero" and args.cases == "untested":
        # 尝试加载已有结果
        existing_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ab_test_results.json")
        if os.path.exists(existing_path):
            try:
                with open(existing_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                # 提取异构结果
                existing_hetero = [r for r in existing if r.get("config") == "v0.3-hetero"]
                # 转换格式
                for r in existing_hetero:
                    r["from_cache"] = True
                all_results = results + existing_hetero
                all_analysis = analyze_results(all_results)
                
                combined_path = os.path.join(RESULTS_DIR, f"hetero_combined_{timestamp}.json")
                with open(combined_path, "w", encoding="utf-8") as f:
                    json.dump({"results": all_results, "analysis": all_analysis}, f,
                              ensure_ascii=False, indent=2)
                print(f"\n合并结果已保存: {combined_path}")
                print_report(all_results, all_analysis)
            except Exception as e:
                print(f"合并已有结果时出错: {e}")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "analysis": analysis}, f,
                  ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存: {output_path}")


if __name__ == "__main__":
    main()
