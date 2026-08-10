#!/usr/bin/env python
"""Full pipeline heterogeneous judge experiment for 6 test cases."""
import json, time, os, sys, requests

# Read API key
with open('D:/competation/design/.tokeness_key.txt') as f:
    API_KEY = f.read().strip()

BASE_URL = "https://n.tokeness.io/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def call_llm(model, messages, temperature=0.3, max_retries=3):
    """Call the LLM API and return (content, token_count)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2048
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens
            else:
                print(f"  [WARN] API returned {resp.status_code}: {resp.text[:200]}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  [WARN] API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
    return None, 0

# ========== 6 test cases ==========
CASES = [
    {
        "id": "case1",
        "error_type": "L1: off-by-one + boundary",
        "ground_truth": "FAIL",
        "task": "写一个函数 get_middle_elements(lst)，返回列表的中间元素。偶数长度返回中间两个，奇数长度返回中间一个。",
        "buggy_code": """def get_middle_elements(lst):
    n = len(lst)
    if n % 2 == 0:
        return [lst[n//2 - 1], lst[n//2]]
    else:
        return [lst[n//2 + 1]]"""
    },
    {
        "id": "case2",
        "error_type": "L1: boundary / missing-edge-case",
        "ground_truth": "FAIL",
        "task": "写一个函数 safe_divide(a, b)，安全地执行除法。如果除数为 0 返回 None。",
        "buggy_code": """def safe_divide(a, b):
    if b == 0:
        return None
    return a / b"""
    },
    {
        "id": "case3",
        "error_type": "L3: algorithm / inefficient",
        "ground_truth": "PASS",
        "task": "写一个函数 has_duplicate(lst)，判断列表中是否有重复元素。",
        "buggy_code": """def has_duplicate(lst):
    for i in range(len(lst)):
        for j in range(i+1, len(lst)):
            if lst[i] == lst[j]:
                return True
    return False"""
    },
    {
        "id": "case4",
        "error_type": "L1: type error / type-confusion",
        "ground_truth": "FAIL",
        "task": "写一个函数 sum_numbers(items)，对列表中的所有数字求和。",
        "buggy_code": """def sum_numbers(items):
    total = 0
    for x in items:
        total += x
    return total"""
    },
    {
        "id": "case5",
        "error_type": "L1: index error / wrong-condition",
        "ground_truth": "FAIL",
        "task": "写一个函数 is_palindrome(s)，判断字符串是否是回文。",
        "buggy_code": """def is_palindrome(s):
    n = len(s)
    for i in range(n):
        if s[i] != s[n - i]:
            return False
    return True"""
    },
    {
        "id": "case6",
        "error_type": "L1: boundary / empty-input",
        "ground_truth": "FAIL",
        "task": "写一个函数 find_max(lst)，返回列表中的最大值。",
        "buggy_code": """def find_max(lst):
    max_val = lst[0]
    for x in lst[1:]:
        if x > max_val:
            max_val = x
    return max_val"""
    }
]

# ========== Snake head prompt ==========
SNAKE_HEAD_PROMPT = """你是蛇群架构的蛇头层（任务规划器）。请分析以下任务，输出执行计划和风险地图。

【任务】
{task}

请输出：
1. 任务分解（按步骤列出）
2. 每步的风险点（边界条件、异常输入、隐含假设）
3. 不确定性标记（哪些地方需要特别注意）

输出格式：自由文本，但需包含以上三部分。"""

# ========== Judge prompt ==========
JUDGE_PROMPT = """你是蛇群架构的区域法官。蛇头层已完成任务分析，以下是分析结果和蛇身生成的代码。请结合蛇头分析审查代码。

【蛇头分析（风险地图）】
{snake_head}

【任务】
{task}

【蛇身代码】
```python
{code}
```

请结合蛇头分析中指出的风险点，逐行审查代码。对每个bug说明：
1. 什么错误
2. 为什么是错误（给出反例）
3. 如何修复

最后给出判决：PASS（代码正确）或 FAIL（存在bug）。

输出格式：
```
判决: [PASS/FAIL]
Bug 1: ...
```"""

# ========== Deep dive prompt ==========
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

请判断少数派的审查意见是否正确。如果少数派指出了多数派遗漏的bug，判决为VALID；如果少数派的意见是错误的（误判），判决为INVALID。

输出格式：
```
深挖结论: [VALID/INVALID]
理由: ...
```"""

# ========== Judges config ==========
JUDGES = [
    {"model": "deepseek-v4-pro", "temperature": 0.3, "name": "judge1_dsv4_low_temp"},
    {"model": "deepseek-v4-pro", "temperature": 0.7, "name": "judge2_dsv4_high_temp"},
    {"model": "gemini-3.6-flash", "temperature": 0.3, "name": "judge3_gemini_flash"},
]

def extract_verdict(text):
    """Extract PASS/FAIL from judge output."""
    if not text:
        return "UNKNOWN"
    text_upper = text.upper()
    # Look for 判决: PASS or 判决: FAIL
    for line in text.split('\n'):
        line = line.strip().upper()
        if '判决' in line:
            if 'PASS' in line.split('判决')[-1]:
                return "PASS"
            if 'FAIL' in line.split('判决')[-1]:
                return "FAIL"
    # Fallback
    if 'PASS' in text_upper and 'FAIL' not in text_upper:
        return "PASS"
    if 'FAIL' in text_upper:
        return "FAIL"
    return "UNKNOWN"

def extract_deep_dive_conclusion(text):
    """Extract VALID/INVALID from deep dive output."""
    if not text:
        return None
    text_upper = text.upper()
    if 'VALID' in text_upper:
        return True
    if 'INVALID' in text_upper:
        return False
    return None

def run_case(case):
    """Run full pipeline for one case."""
    case_id = case["id"]
    print(f"\n{'='*60}")
    print(f"Processing {case_id}: {case['error_type']}")
    print(f"{'='*60}")
    
    total_tokens = 0
    result = {
        "case": case_id,
        "snake_head_analysis": "",
        "judges": [],
        "votes": [],
        "deep_dive": None,
        "final_verdict": "",
        "ground_truth": case["ground_truth"],
        "correct": False,
        "total_tokens": 0
    }

    # Step 1: Snake head analysis with claude-sonnet-5
    print(f"  [1/4] Snake head analysis (claude-sonnet-5)...")
    sh_prompt = SNAKE_HEAD_PROMPT.format(task=case["task"])
    sh_content, sh_tokens = call_llm("claude-sonnet-5", [{"role": "user", "content": sh_prompt}], temperature=0.3)
    total_tokens += sh_tokens
    result["snake_head_analysis"] = sh_content or "ERROR: No response"
    print(f"  -> Snake head tokens: {sh_tokens}")

    if not sh_content:
        print(f"  [ERROR] Snake head failed for {case_id}")
        return result

    # Step 2: Three heterogeneous judges
    print(f"  [2/4] Running 3 heterogeneous judges...")
    votes = []
    for ji, judge in enumerate(JUDGES):
        jp = JUDGE_PROMPT.format(
            snake_head=sh_content,
            task=case["task"],
            code=case["buggy_code"]
        )
        j_content, j_tokens = call_llm(
            judge["model"],
            [{"role": "user", "content": jp}],
            temperature=judge["temperature"]
        )
        total_tokens += j_tokens
        verdict = extract_verdict(j_content)
        votes.append(verdict)
        result["judges"].append({
            "model": judge["model"],
            "temperature": judge["temperature"],
            "verdict": verdict,
            "tokens": j_tokens,
            "raw_output": j_content or "ERROR"
        })
        print(f"  -> {judge['name']} ({judge['model']}, T={judge['temperature']}): {verdict} ({j_tokens} tokens)")
        time.sleep(0.5)

    result["votes"] = votes

    # Step 3: Deep dive if needed
    pass_count = votes.count("PASS")
    fail_count = votes.count("FAIL")
    unknown_count = votes.count("UNKNOWN")
    
    print(f"  [3/4] Vote tally: PASS={pass_count}, FAIL={fail_count}, UNKNOWN={unknown_count}")
    
    if pass_count == 3 or fail_count == 3:
        # Unanimous - no deep dive needed
        result["final_verdict"] = "PASS" if pass_count == 3 else "FAIL"
        result["deep_dive"] = None
        print(f"  -> Unanimous: {result['final_verdict']}, no deep dive needed")
    
    elif (pass_count == 2 and fail_count == 1) or (pass_count == 1 and fail_count == 2):
        # 2:1 split - deep dive the minority
        minority_verdict = "FAIL" if fail_count == 1 else "PASS"
        majority_verdict = "PASS" if pass_count == 2 else "FAIL"
        
        # Find minority judge
        minority_idx = None
        for i, v in enumerate(votes):
            if v == minority_verdict:
                minority_idx = i
                break
        
        minority_review = result["judges"][minority_idx]["raw_output"]
        
        print(f"  -> 2:1 split, deep diving minority ({minority_verdict})...")
        
        dd_prompt = DEEP_DIVE_PROMPT.format(
            majority_verdict=majority_verdict,
            minority_verdict=minority_verdict,
            minority_review=minority_review,
            task=case["task"],
            code=case["buggy_code"]
        )
        dd_content, dd_tokens = call_llm(
            "deepseek-v4-pro",
            [{"role": "user", "content": dd_prompt}],
            temperature=0.3
        )
        total_tokens += dd_tokens
        valid = extract_deep_dive_conclusion(dd_content)
        result["deep_dive"] = {"valid": valid, "tokens": dd_tokens, "raw_output": dd_content or "ERROR"}
        
        if valid:
            result["final_verdict"] = minority_verdict
            print(f"  -> Deep dive: VALID, adopting minority ({minority_verdict})")
        else:
            result["final_verdict"] = majority_verdict
            print(f"  -> Deep dive: INVALID, adopting majority ({majority_verdict})")
    else:
        # Deadlock (UNKNOWN votes)
        result["final_verdict"] = "DEADLOCK"
        result["deep_dive"] = None
        print(f"  -> DEADLOCK (too many UNKNOWN votes)")

    # Step 4: Check correctness
    result["correct"] = (result["final_verdict"] == result["ground_truth"])
    result["total_tokens"] = total_tokens
    print(f"  [4/4] Final: {result['final_verdict']} (Ground truth: {result['ground_truth']}) -> {'✓ CORRECT' if result['correct'] else '✗ INCORRECT'}")
    print(f"  Total tokens: {total_tokens}")

    return result

def main():
    os.makedirs("D:/competation/design/experiments/results", exist_ok=True)
    
    results = []
    for case in CASES:
        result = run_case(case)
        results.append(result)
        # Save after each case as backup
        with open("D:/competation/design/experiments/results/full_pipeline_batch1.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        time.sleep(1)
    
    print(f"\n{'='*60}")
    print(f"ALL DONE! {len(results)} cases processed.")
    print(f"Results saved to: D:/competation/design/experiments/results/full_pipeline_batch1.json")
    
    # Summary
    correct_count = sum(1 for r in results if r["correct"])
    print(f"Accuracy: {correct_count}/{len(results)} = {correct_count/len(results)*100:.1f}%")
    total_tokens = sum(r["total_tokens"] for r in results)
    print(f"Total tokens used: {total_tokens}")

if __name__ == "__main__":
    main()
