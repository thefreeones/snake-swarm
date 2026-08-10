#!/usr/bin/env python
"""
蛇群 P1 异构组合对比实验
C1: DS+DS+Gemini  vs  C2: Claude+DS+Gemini
用例: S2(compute_variance 灾难性抵消) + case8(get_user_info KeyError)
API: Tokeness (https://n.tokeness.io/v1)
"""
import json, time, os, sys, yaml, requests
from datetime import datetime

# ============================================================
# 1. 配置
# ============================================================
CONFIG_PATH = os.path.expanduser("~/AppData/Local/hermes/config.yaml")
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

# 找 tokeness provider 的 api_key
API_KEY = None
for p in config.get("custom_providers", []):
    if p.get("name") == "tokeness":
        API_KEY = p.get("api_key", "")
        break

if not API_KEY:
    print("ERROR: 找不到 tokeness API key")
    sys.exit(1)

BASE_URL = "https://n.tokeness.io/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

RESULTS_DIR = "D:/competation/design/experiments/results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ============================================================
# 2. 测试用例定义
# ============================================================

S2_CASE = {
    "id": "S2",
    "title": "领域知识 / 数值稳定性 — 灾难性抵消",
    "error_type": "L3: domain knowledge / numerical stability",
    "category": "deep_adversarial",
    "z_score": 8,
    "ground_truth": "FAIL",
    "task": "写一个函数 compute_variance(data)，计算总体方差。",
    "buggy_code": """def compute_variance(data):
    n = len(data)
    sum_x = sum(data)
    sum_x2 = sum(x*x for x in data)
    return (sum_x2 - sum_x * sum_x / n) / n  # BUG: 灾难性抵消""",
    "expected_bugs": ["灾难性抵消（catastrophic cancellation）", "大数相减导致精度丢失甚至负方差"],
    # P0 数据：C1 → PASS（漏判）
    "c1_p0_verdict": "PASS",
    # 推理增强插件测试报告
    "reasoning_plugin_report": {
        "test_input": [1e10 + 1, 1e10 + 2, 1e10 + 3],
        "actual_output": 0.0,
        "reference_output": 0.6666666666666666,
        "explanation": "该测试用例选择了三个非常接近的大数(1e10+1, 1e10+2, 1e10+3)。它们的方差理论上约为0.667(均值附近均匀分布±1)。但由于平方项sum_x2和sum_x*sum_x/n都是~1e20量级的大数，相减时浮点精度不足，导致灾难性抵消，实际输出0.0（甚至可能为负）。这是典型的数值稳定性缺陷——功能逻辑正确，但数值结果完全错误。"
    }
}

CASE8 = {
    "id": "case8",
    "title": "变量遮蔽 / KeyError",
    "error_type": "L1: logic error / variable-shadowing",
    "category": "logic_error",
    "z_score": 2,
    "ground_truth": "FAIL",
    "task": "写一个函数 filter_adults(people)，从字典列表中筛选 age >= 18 的人。",
    "buggy_code": """def filter_adults(people):
    result = []
    for person in people:
        if person['age'] >= 18:  # BUG: 可能 KeyError
            result.append(person)
    return result""",
    "expected_bugs": ["字典缺少 'age' 键时 KeyError", "应使用 .get('age', 0)"],
    # P0 数据：C1 → FAIL（正确检出）
    "c1_p0_verdict": "FAIL",
}

TEST_CASES = [S2_CASE, CASE8]

# 法官组合定义
# C1: DS(t=0.3) + DS(t=0.7) + Gemini(t=0.3)
C1_JUDGES = [
    {"model": "deepseek-v4-pro", "temperature": 0.3, "label": "DS-lo"},
    {"model": "deepseek-v4-pro", "temperature": 0.7, "label": "DS-hi"},
    {"model": "gemini-3.6-flash", "temperature": 0.3, "label": "Gemini"},
]

# C2: Claude(t=0.3) + DS(t=0.7) + Gemini(t=0.3)
C2_JUDGES = [
    {"model": "claude-sonnet-5", "temperature": 0.3, "label": "Claude"},
    {"model": "deepseek-v4-pro", "temperature": 0.7, "label": "DS-hi"},
    {"model": "gemini-3.6-flash", "temperature": 0.3, "label": "Gemini"},
]

# ============================================================
# 3. API 调用
# ============================================================

def call_llm(model, messages, temperature=0.3, max_tokens=4096, max_retries=3):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return {"content": content, "tokens": tokens, "error": None}
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
        except Exception as e:
            err_msg = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
    return {"content": None, "tokens": 0, "error": err_msg}

# ============================================================
# 4. Prompt 构建
# ============================================================

SNAKE_HEAD_PROMPT = """你是一位资深软件架构师（蛇头层）。请分析以下编程任务，制定执行计划并标记风险点。

【任务】
{task}

请输出：
1. 任务分解（按步骤列出）
2. 每步的风险点（边界条件、异常输入、隐含假设、性能陷阱）
3. 不确定性标记（低/中/高 —— 哪些地方需要特别注意）

输出格式：自由文本，但需包含以上三部分。"""

# 标准法官 prompt
JUDGE_PROMPT = """你是一位严格的代码审查员（区域法官）。蛇头层已完成任务分析，以下是分析结果和蛇身生成的代码。请结合蛇头分析审查代码。

【蛇头分析（风险地图）】
{snake_head}

【任务】
{task}

【蛇身代码】
```python
{code}
```

请逐行审查代码，找出所有 bug。对每个 bug 说明：
1. 什么错误
2. 为什么是错误（给出反例）
3. 如何修复

【判决标准】仅功能性缺陷（错误输出/崩溃/数据损坏）才判 FAIL。代码风格/质量问题不算功能性缺陷。

最后给出判决：PASS（代码无功能性缺陷）或 FAIL（存在功能性缺陷）。

输出格式：
```
判决: [PASS/FAIL]
Bug 1: ...
Bug 2: ...
```"""

# S2 专用法官 prompt —— 注入推理增强插件测试报告
JUDGE_PROMPT_S2_PLUGIN = """你是一位严格的代码审查员（区域法官）。蛇头层已完成任务分析，以下是分析结果和蛇身生成的代码。此外，推理增强插件提供了具体的数值测试报告。

【蛇头分析（风险地图）】
{snake_head}

【推理增强插件 — 数值测试报告】
{plugin_report}

【任务】
{task}

【蛇身代码】
```python
{code}
```

请逐行审查代码，结合蛇头分析和插件测试报告，找出所有 bug。对每个 bug 说明：
1. 什么错误
2. 为什么是错误（给出反例）
3. 如何修复

【判决标准】仅功能性缺陷（错误输出/崩溃/数据 corruption）才判 FAIL。代码风格/质量问题不算功能性缺陷。

最后给出判决：PASS（代码无功能性缺陷）或 FAIL（存在功能性缺陷）。

输出格式：
```
判决: [PASS/FAIL]
Bug 1: ...
Bug 2: ...
```"""

# 深挖 prompt
DEEP_DIVE_PROMPT = """你是蛇群架构的深挖法官。在之前的审查中，出现了意见分歧：

多数派（2票）意见：{majority_verdict}
少数派（1票）意见：{minority_verdict}

少数派的完整审查意见如下：
---
{minority_review}
---

任务描述：{task}
代码：
```python
{code}
```

请判断少数派的审查意见是否正确：
- 如果少数派正确地指出了多数派遗漏的功能性缺陷，判决为 VALID
- 如果少数派的意见是错误的（误判），判决为 INVALID

输出格式：
```
深挖结论: [VALID/INVALID]
理由: ...
```"""

# ============================================================
# 5. 解析函数
# ============================================================

def parse_verdict(text):
    """从法官输出中提取 PASS/FAIL"""
    if not text:
        return "UNKNOWN"
    text_u = text.upper()
    # 优先匹配 "判决: PASS" 或 "判决: FAIL"
    for line in text.split('\n'):
        line_s = line.strip().upper()
        if '判决' in line_s and ':' in line_s:
            after = line_s.split('判决', 1)[-1]
            after = after.split(':', 1)[-1] if ':' in after else after
            after = after.strip()
            if 'FAIL' in after:
                return "FAIL"
            if 'PASS' in after:
                return "PASS"
    # 回退
    fail_markers = text_u.count("BUG ") + text_u.count("BUG:") + text_u.count("缺陷")
    if fail_markers >= 1 and "PASS" not in text_u[-100:]:
        return "FAIL"
    if "PASS" in text_u.split('\n')[-5].upper() if len(text_u.split('\n')) > 5 else text_u[-200:]:
        return "PASS"
    return "UNKNOWN"

def parse_deep_dive(text):
    """解析深挖结论"""
    if not text:
        return None
    tu = text.upper()
    if "VALID" in tu and "INVALID" not in tu:
        return True
    if "INVALID" in tu:
        return False
    return None

# ============================================================
# 6. 蛇头分析生成
# ============================================================

def generate_snake_head(case):
    """用 claude-sonnet-5 生成蛇头分析"""
    print(f"  [蛇头] 生成 {case['id']} 的蛇头分析...")
    prompt = SNAKE_HEAD_PROMPT.format(task=case["task"])
    resp = call_llm("claude-sonnet-5", [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=4096)
    if resp["error"]:
        print(f"    ❌ 蛇头生成失败: {resp['error']}")
        return None, 0
    print(f"    ✅ 蛇头生成完成 ({resp['tokens']} tokens)")
    return resp["content"], resp["tokens"]

# ============================================================
# 7. 法官审查
# ============================================================

def run_judges(case, judges_config, snake_head, config_label):
    """运行一组法官审查"""
    print(f"\n  [{config_label}] 运行 {len(judges_config)} 位法官...")
    
    # S2 使用带插件报告的 prompt
    is_s2 = case["id"] == "S2"
    
    votes = []
    judge_results = []
    total_tokens = 0
    
    for ji, jc in enumerate(judges_config):
        # 构建 prompt
        if is_s2 and "reasoning_plugin_report" in case:
            pr = case["reasoning_plugin_report"]
            plugin_text = f"""测试输入: {pr['test_input']}
被测代码输出: {pr['actual_output']}
参考正确输出: {pr['reference_output']}
分析: {pr['explanation']}"""
            prompt = JUDGE_PROMPT_S2_PLUGIN.format(
                snake_head=snake_head,
                plugin_report=plugin_text,
                task=case["task"],
                code=case["buggy_code"]
            )
        else:
            prompt = JUDGE_PROMPT.format(
                snake_head=snake_head,
                task=case["task"],
                code=case["buggy_code"]
            )
        
        print(f"    法官{ji+1}: {jc['label']}({jc['model']}, T={jc['temperature']})...", end=" ", flush=True)
        
        resp = call_llm(jc["model"], [{"role": "user", "content": prompt}],
                       temperature=jc["temperature"], max_tokens=4096)
        
        if resp["error"]:
            print(f"❌ {resp['error']}")
            judge_results.append({"model": jc["model"], "label": jc["label"],
                                 "temperature": jc["temperature"], "verdict": "ERROR",
                                 "tokens": 0, "raw": "", "error": resp["error"]})
            continue
        
        verdict = parse_verdict(resp["content"])
        total_tokens += resp["tokens"]
        votes.append(verdict)
        judge_results.append({
            "model": jc["model"], "label": jc["label"],
            "temperature": jc["temperature"], "verdict": verdict,
            "tokens": resp["tokens"], "raw": resp["content"]
        })
        print(f"{verdict} ({resp['tokens']}t)")
        time.sleep(0.5)
    
    return judge_results, votes, total_tokens

# ============================================================
# 8. 投票 + 深挖
# ============================================================

def resolve_votes(judge_results, votes, case, total_tokens):
    """根据投票结果决定最终判决，必要时深挖"""
    pass_count = votes.count("PASS")
    fail_count = votes.count("FAIL")
    unknown_count = votes.count("UNKNOWN")
    
    print(f"    投票: FAIL={fail_count}, PASS={pass_count}, UNKNOWN={unknown_count}")
    
    deep_dive = None
    final_verdict = None
    
    if pass_count == 3:
        final_verdict = "PASS"
        print(f"    全票 PASS → {final_verdict}")
    elif fail_count == 3:
        final_verdict = "FAIL"
        print(f"    全票 FAIL → {final_verdict}")
    elif fail_count == 2 and pass_count == 1:
        # 多数 FAIL，深挖少数派 PASS
        minority = [j for j in judge_results if j["verdict"] == "PASS"][0]
        print(f"    2:1 多数FAIL，深挖少数派(PASS)...")
        
        dd_prompt = DEEP_DIVE_PROMPT.format(
            majority_verdict="FAIL", minority_verdict="PASS",
            minority_review=minority["raw"], task=case["task"], code=case["buggy_code"]
        )
        dd_resp = call_llm("deepseek-v4-pro", [{"role": "user", "content": dd_prompt}], temperature=0.3)
        total_tokens += dd_resp["tokens"]
        
        valid = parse_deep_dive(dd_resp["content"])
        deep_dive = {"valid": valid, "tokens": dd_resp["tokens"]}
        
        if valid:
            final_verdict = "PASS"
            print(f"    深挖: VALID → 采纳少数派 PASS")
        else:
            final_verdict = "FAIL"
            print(f"    深挖: INVALID → 维持多数 FAIL")
    
    elif pass_count == 2 and fail_count == 1:
        # 多数 PASS，深挖少数派 FAIL
        minority = [j for j in judge_results if j["verdict"] == "FAIL"][0]
        print(f"    1:2 多数PASS，深挖少数派(FAIL)...")
        
        dd_prompt = DEEP_DIVE_PROMPT.format(
            majority_verdict="PASS", minority_verdict="FAIL",
            minority_review=minority["raw"], task=case["task"], code=case["buggy_code"]
        )
        dd_resp = call_llm("deepseek-v4-pro", [{"role": "user", "content": dd_prompt}], temperature=0.3)
        total_tokens += dd_resp["tokens"]
        
        valid = parse_deep_dive(dd_resp["content"])
        deep_dive = {"valid": valid, "tokens": dd_resp["tokens"]}
        
        if valid:
            final_verdict = "FAIL"
            print(f"    深挖: VALID → 采纳少数派 FAIL")
        else:
            final_verdict = "PASS"
            print(f"    深挖: INVALID → 维持多数 PASS")
    else:
        final_verdict = "DEADLOCK"
        print(f"    死锁 → DEADLOCK")
    
    return final_verdict, deep_dive, total_tokens

# ============================================================
# 9. 主流程
# ============================================================

def main():
    print("=" * 70)
    print("  蛇群 P1 异构组合对比实验")
    print("  C1: DS+DS+Gemini  vs  C2: Claude+DS+Gemini")
    print("  用例: S2 (Z=8) + case8 (Z=2)")
    print("=" * 70)
    
    all_results = []
    total_tokens_used = 0
    
    for case in TEST_CASES:
        case_id = case["id"]
        print(f"\n{'='*70}")
        print(f"  用例: {case_id} — {case['title']}")
        print(f"  GT={case['ground_truth']}, Z={case['z_score']}")
        print(f"{'='*70}")
        
        # Step 1: 蛇头分析
        print(f"\n[Phase 1] 蛇头分析 (claude-sonnet-5)")
        snake_head, sh_tokens = generate_snake_head(case)
        total_tokens_used += sh_tokens
        
        if not snake_head:
            print(f"  ❌ {case_id} 蛇头分析失败，跳过")
            continue
        
        # S2 打印推理增强插件报告
        if case_id == "S2" and "reasoning_plugin_report" in case:
            pr = case["reasoning_plugin_report"]
            print(f"\n[推理增强插件] S2 数值测试报告:")
            print(f"  测试输入: {pr['test_input']}")
            print(f"  被测输出: {pr['actual_output']}")
            print(f"  参考输出: {pr['reference_output']}")
            print(f"  分析: {pr['explanation'][:80]}...")
        
        # Step 2: C1 组合
        print(f"\n[Phase 2] C1 组合: DS+DS+Gemini")
        c1_judges, c1_votes, c1_tokens = run_judges(case, C1_JUDGES, snake_head, "C1")
        total_tokens_used += c1_tokens
        
        c1_final, c1_deep_dive, c1_tokens2 = resolve_votes(c1_judges, c1_votes, case, c1_tokens)
        total_tokens_used += (c1_tokens2 - c1_tokens)  # add deep dive tokens
        
        c1_correct = (c1_final == case["ground_truth"])
        
        # Step 3: C2 组合
        print(f"\n[Phase 3] C2 组合: Claude+DS+Gemini")
        c2_judges, c2_votes, c2_tokens = run_judges(case, C2_JUDGES, snake_head, "C2")
        total_tokens_used += c2_tokens
        
        c2_final, c2_deep_dive, c2_tokens2 = resolve_votes(c2_judges, c2_votes, case, c2_tokens)
        total_tokens_used += (c2_tokens2 - c2_tokens)
        
        c2_correct = (c2_final == case["ground_truth"])
        
        # 组装结果
        case_result = {
            "case": case_id,
            "title": case["title"],
            "error_type": case["error_type"],
            "z_score": case["z_score"],
            "ground_truth": case["ground_truth"],
            "snake_head_analysis": snake_head,
            "p0_c1_verdict": case.get("c1_p0_verdict", "N/A"),
            "combinations": {
                "C1_DS_DS_Gemini": {
                    "judges": [{"model": j["model"], "label": j["label"],
                               "temperature": j["temperature"], "verdict": j["verdict"],
                               "tokens": j["tokens"]} for j in c1_judges],
                    "votes": c1_votes,
                    "deep_dive": c1_deep_dive,
                    "final_verdict": c1_final,
                    "correct": c1_correct,
                },
                "C2_Claude_DS_Gemini": {
                    "judges": [{"model": j["model"], "label": j["label"],
                               "temperature": j["temperature"], "verdict": j["verdict"],
                               "tokens": j["tokens"]} for j in c2_judges],
                    "votes": c2_votes,
                    "deep_dive": c2_deep_dive,
                    "final_verdict": c2_final,
                    "correct": c2_correct,
                }
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # S2 附加推理插件报告
        if case_id == "S2":
            case_result["reasoning_plugin"] = case["reasoning_plugin_report"]
        
        all_results.append(case_result)
        
        # 逐个用例的小结
        print(f"\n  --- {case_id} 结果小结 ---")
        print(f"  C1: {c1_final} (GT={case['ground_truth']}) → {'✅' if c1_correct else '❌'}")
        print(f"  C2: {c2_final} (GT={case['ground_truth']}) → {'✅' if c2_correct else '❌'}")
        
        time.sleep(1)
    
    # ============================================================
    # 10. 汇总分析
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  汇总分析")
    print(f"{'='*70}")
    
    c1_correct = sum(1 for r in all_results if r["combinations"]["C1_DS_DS_Gemini"]["correct"])
    c2_correct = sum(1 for r in all_results if r["combinations"]["C2_Claude_DS_Gemini"]["correct"])
    total = len(all_results)
    
    print(f"\nC1 (DS+DS+Gemini): {c1_correct}/{total} 正确检出")
    print(f"C2 (Claude+DS+Gemini): {c2_correct}/{total} 正确检出")
    
    for r in all_results:
        c1 = r["combinations"]["C1_DS_DS_Gemini"]
        c2 = r["combinations"]["C2_Claude_DS_Gemini"]
        print(f"\n  {r['case']} ({r['title'][:30]}):")
        print(f"    C1: votes={c1['votes']} → {c1['final_verdict']} {'✅' if c1['correct'] else '❌'}")
        print(f"    C2: votes={c2['votes']} → {c2['final_verdict']} {'✅' if c2['correct'] else '❌'}")
    
    # 计算改进
    improvement = ""
    if c2_correct > c1_correct:
        improvement = f"C2 比 C1 多检出 {c2_correct - c1_correct} 个用例"
    elif c2_correct < c1_correct:
        improvement = f"C1 比 C2 多检出 {c1_correct - c2_correct} 个用例"
    else:
        improvement = "C1 和 C2 检出率相同"
    
    # S2 特殊分析
    s2_result = next((r for r in all_results if r["case"] == "S2"), None)
    
    # 保存结果
    output_path = os.path.join(RESULTS_DIR, "p1_batch1.json")
    output = {
        "experiment": "蛇群P1-异构组合对比",
        "description": "对比 C1(DS+DS+Gemini) 和 C2(Claude+DS+Gemini) 两种法官组合的检出率",
        "date": datetime.now().isoformat(),
        "api": {"base": BASE_URL},
        "cases_tested": [r["case"] for r in all_results],
        "results": all_results,
        "summary": {
            "total_cases": total,
            "C1_correct": c1_correct,
            "C2_correct": c2_correct,
            "C1_detection_rate": f"{c1_correct}/{total}",
            "C2_detection_rate": f"{c2_correct}/{total}",
            "improvement": improvement,
            "total_tokens_used": total_tokens_used,
        }
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存: {output_path}")
    print(f"总 Token 消耗: {total_tokens_used}")
    
    # ============================================================
    # 11. 中文结论输出
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  📊 P1 异构组合对比实验 — 中文结论")
    print(f"{'='*70}")
    
    print(f"""
一、实验概况
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 用例数：{total}（S2: compute_variance 灾难性抵消 Z=8, case8: filter_adults KeyError Z=2）
• C1 组合：DeepSeek(t=0.3) + DeepSeek(t=0.7) + Gemini(t=0.3)
• C2 组合：Claude-Sonnet-5(t=0.3) + DeepSeek(t=0.7) + Gemini(t=0.3)
• 判决标准：仅功能性缺陷（错误输出/崩溃/数据损坏）判 FAIL

二、检出率对比
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• C1 (DS+DS+Gemini)：{c1_correct}/{total}
• C2 (Claude+DS+Gemini)：{c2_correct}/{total}
• 改进：{improvement}""")
    
    for r in all_results:
        c1 = r["combinations"]["C1_DS_DS_Gemini"]
        c2 = r["combinations"]["C2_Claude_DS_Gemini"]
        print(f"""
三、用例 {r['case']} ({r['title'][:40]}) 详细分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• GT: {r['ground_truth']}, Z={r['z_score']}
• P0 基线: C1→{r.get('p0_c1_verdict', 'N/A')}
• C1 投票: {c1['votes']} → 终判: {c1['final_verdict']} {'✅ 正确' if c1['correct'] else '❌ 错误'}
• C2 投票: {c2['votes']} → 终判: {c2['final_verdict']} {'✅ 正确' if c2['correct'] else '❌ 错误'}""")
        
        if c1["deep_dive"]:
            print(f"  C1 深挖: {'VALID(翻转)' if c1['deep_dive']['valid'] else 'INVALID(维持多数)'}")
        if c2["deep_dive"]:
            print(f"  C2 深挖: {'VALID(翻转)' if c2['deep_dive']['valid'] else 'INVALID(维持多数)'}")
    
    # S2 专项分析
    if s2_result:
        s2_c1 = s2_result["combinations"]["C1_DS_DS_Gemini"]
        s2_c2 = s2_result["combinations"]["C2_Claude_DS_Gemini"]
        print(f"""
四、S2 关键分析（灾难性抵消 — 领域知识制胜点）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S2 是本次实验的核心攻坚用例（Z=8，难度最高）。compute_variance
使用标准公式 Var=Σx²/n-(Σx/n)²，对大数输入会产生灾难性抵消。

推理增强插件关键证据：
  输入：[1e10+1, 1e10+2, 1e10+3]
  被测输出：0.0（完全错误！）
  参考输出：0.667（理论正确值）
  结论：代码在数值上产生完全错误的结果，属于功能性缺陷。

P0 基线：C1 漏判（→PASS）
P1 结果：
  C1 (DS+DS+Gemini): {s2_c1['final_verdict']} {'✅' if s2_c1['correct'] else '❌'}
  C2 (Claude+DS+Gemini): {s2_c2['final_verdict']} {'✅' if s2_c2['correct'] else '❌'}""")
    
    print(f"""
五、综合结论
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 检出率：C1={c1_correct}/{total}, C2={c2_correct}/{total}
2. {improvement}
3. S2（灾难性抵消）是区分两种组合能力的关键用例：
   - 该用例需要领域知识（数值分析）才能识别
   - 推理增强插件的测试报告为法官提供了客观数值证据
   - 能否利用插件报告中的反例证据是检出与否的关键
4. case8（KeyError）属于显性逻辑错误（L1），预计两种组合均能检出

六、文件输出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• {output_path}
• 总 Token: {total_tokens_used}
""")

if __name__ == "__main__":
    main()
