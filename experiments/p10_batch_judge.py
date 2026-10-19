#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P10: 批量法官审查验证
比较个体审查 vs 批量审查的token成本和判决质量
"""
import json, time, os, urllib.request, sys

# ── API Config ──
hex_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_apikey_hex.txt')
if not os.path.exists(hex_path):
    hex_path = '<SNAKE_SWARM_DATA>/_apikey_hex.txt'
with open(hex_path, 'r') as f:
    API_KEY = bytes.fromhex(f.read().strip()).decode('utf-8')
BASE_URL = "https://n.tokeness.io/v1"

# ── C1 Judge Config ──
JUDGES = [
    {"name": "DS-t0.3", "model": "deepseek-v4-pro", "temperature": 0.3, "max_tokens": 4000},
    {"name": "DS-t0.7", "model": "deepseek-v4-pro", "temperature": 0.7, "max_tokens": 4000},
    {"name": "Gemini-t0.3", "model": "gemini-3.6-flash", "temperature": 0.3, "max_tokens": 4000},
]

# ── Shared code context (python-slugify source ~197 lines) ──
SHARED_CODE = r'''# slugify/slugify.py (excerpt)
from html.entities import name2codepoint
import re, unicodedata

CHAR_ENTITY_PATTERN = re.compile(r'&(%s);' % '|'.join(name2codepoint))
DECIMAL_PATTERN = re.compile(r'&#(\d+);')
HEX_PATTERN = re.compile(r'&#x([\da-fA-F]+);')
DEFAULT_SEPARATOR = '-'

def smart_truncate(string, max_length=0, word_boundary=False, separator=" ", save_order=False):
    string = string.strip(separator)
    if not max_length:          # <-- LINE 46: bug-185 here
        return string
    if len(string) < max_length:
        return string
    if not word_boundary:       # <-- LINE 52: bug-186 here
        return string[:max_length].strip(separator)
    if separator not in string:
        return string[:max_length]
    truncated = ''
    for word in string.split(separator):
        if word:
            next_len = len(truncated) + len(word)
            if next_len < max_length:
                truncated += '{}{}'.format(word, separator)
            elif next_len == max_length:
                truncated += '{}'.format(word)
                break
            else:
                if save_order:
                    break
    if not truncated:
        truncated = string[:max_length]
    return truncated.strip(separator)

def slugify(text, entities=True, decimal=True, hexadecimal=True, max_length=0,
            word_boundary=False, separator='-', save_order=False, stopwords=(),
            regex_pattern=None, lowercase=True, replacements=(), allow_unicode=False):
    # user-specific replacements (PRE-PROCESS)
    if replacements:
        for old, new in replacements:
            text = text.replace(old, new)          # <-- LINE 111: bug-179 first application
    # ... normalize, entity decode ...
    if decimal:
        try:
            text = DECIMAL_PATTERN.sub(lambda m: chr(int(m.group(1))), text)
        except Exception:                          # <-- LINE 139: bug-178 broad except
            pass
    # ... more processing ...
    # finalize user-specific replacements (POST-PROCESS)
    if replacements:
        for old, new in replacements:
            text = text.replace(old, new)          # <-- LINE 188: bug-179 second application
    # smart truncate
    if max_length > 0:
        text = smart_truncate(text, max_length, word_boundary, '-', save_order)
    return text

# slugify/special.py
def add_uppercase_char(char_list):
    for item in char_list:
        char, xlate = item
        upper_dict = char.upper(), xlate.capitalize()
        if upper_dict not in char_list and char != upper_dict[0]:
            char_list.insert(0, upper_dict)
        return char_list      # <-- LINE 12: bug-148 indented inside for loop

_GERMAN = [(u'\xe4', u'ae'), (u'\xf6', u'oe'), (u'\xfc', u'ue')]
GERMAN = add_uppercase_char(_GERMAN)
PRE_TRANSLATIONS = CYRILLIC + GERMAN + GREEK  # bug-148: missing Uppercase entries
'''

# ── 5 Bug Cases ──
# Each: bug_id, title, error_type, root_cause, trigger, expected, buggy_output, fix_description
BUGS = [
    {
        "bug_id": "bug-185-max-length",
        "title": "smart_truncate: negative max_length causes unexpected truncation",
        "error_type": "Logic error (condition check)",
        "root_cause": "`if not max_length:` uses Python truthiness — `not -1` is False, so negative values enter truncation logic",
        "trigger": "smart_truncate('hello-world', max_length=-1)",
        "expected": "'hello-world' (no truncation)",
        "buggy_output": "'hello-worl' (truncated to 11 chars)",
        "fix_description": "Change line 46 from `if not max_length:` to `if max_length <= 0:`",
        "fix_code": "if max_length <= 0:",
        "file": "slugify/slugify.py",
        "line": 46,
    },
    {
        "bug_id": "bug-186-empty-separator",
        "title": "smart_truncate: empty separator + word_boundary causes ValueError crash",
        "error_type": "Missing boundary condition",
        "root_cause": "`''.split('')` raises ValueError, but empty separator is not handled before split",
        "trigger": "smart_truncate('helloworld', max_length=5, word_boundary=True, separator='')",
        "expected": "No exception (hard truncate to 'hello')",
        "buggy_output": "ValueError: empty separator",
        "fix_description": "Change line 52 from `if not word_boundary:` to `if not word_boundary or not separator:`",
        "fix_code": "if not word_boundary or not separator:",
        "file": "slugify/slugify.py",
        "line": 52,
    },
    {
        "bug_id": "bug-178-malformed-entities",
        "title": "slugify: malformed numeric entity causes all entity conversions to be lost",
        "error_type": "Overly broad exception handling (ValueError propagation)",
        "root_cause": "Broad `except Exception` wraps entire `re.sub()`, so one invalid entity (&#99999999;) discards all entity conversions for that call",
        "trigger": "slugify('&#381; &#99999999;', decimal=True)",
        "expected": "'z-99999999' (valid entity Z -> z, invalid entity kept as-is)",
        "buggy_output": "'381-99999999' (all entity conversions skipped)",
        "fix_description": "Replace the broad try/except (lines 137-140) with per-match exception handling. Instead of wrapping the entire DECIMAL_PATTERN.sub() in try/except, use a helper function `_char_from_decimal_codepoint(m)` that tries chr(int(m.group(1))) per-match. Invalid entities are kept as-is (the original text), valid ones are converted.",
        "fix_code": "def _char_from_decimal_codepoint(m):\n    try:\n        return chr(int(m.group(1)))\n    except (ValueError, OverflowError):\n        return m.group(0)  # keep original text\n# Then on the decimal line:\ntext = DECIMAL_PATTERN.sub(_char_from_decimal_codepoint, text)",
        "file": "slugify/slugify.py",
        "line": "137-140",
    },
    {
        "bug_id": "bug-179-self-referential",
        "title": "slugify: self-referential replacements applied twice causing result bloat",
        "error_type": "Logic error (double processing)",
        "root_cause": "Replacements are applied at pre-process (line 111) AND post-process (line 188). Self-referencing rules like ['a','aa'] get doubled: a->aa->aaaa",
        "trigger": "slugify('a', replacements=[['a', 'aa']])",
        "expected": "'aa' (applied once)",
        "buggy_output": "'aaaa' (applied twice: a->aa->aaaa)",
        "fix_description": "In the post-process replacement loop (line 187-188), skip self-referential rules. Add a check: `if old in new: continue`. This prevents double-application when the replacement target contains the source pattern.",
        "fix_code": "if replacements:\n    for old, new in replacements:\n        if old in new:\n            continue  # skip self-referential to avoid double application\n        text = text.replace(old, new)",
        "file": "slugify/slugify.py",
        "line": "186-188",
    },
    {
        "bug_id": "bug-148-uppercase-return",
        "title": "add_uppercase_char: return statement incorrectly indented inside for loop",
        "error_type": "Indentation error (control flow)",
        "root_cause": "`return char_list` is indented inside the for loop, so function returns after processing only the first character",
        "trigger": "Check PRE_TRANSLATIONS content — it should contain Ue, Oe, Ae (uppercase German)",
        "expected": "PRE_TRANSLATIONS contains all three uppercase German entries (Ue, Oe, Ae)",
        "buggy_output": "Only contains Ae (first char's uppercase); missing Ue and Oe",
        "fix_description": "Move `return char_list` from inside the for loop (line 12, indented 8 spaces) to outside the for loop (same indentation as the `for` keyword). The fixed code:\n    for item in char_list:\n        char, xlate = item\n        upper_dict = char.upper(), xlate.capitalize()\n        if upper_dict not in char_list and char != upper_dict[0]:\n            char_list.insert(0, upper_dict)\n    return char_list  # <-- unindented from for loop",
        "fix_code": "    return char_list  # outside for loop",
        "file": "slugify/special.py",
        "line": 12,
    },
]


def call_llm(model, temperature, max_tokens, system_prompt, user_prompt):
    """Call LLM API via urllib. Returns (content, prompt_tokens, completion_tokens)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "latency": time.time() - t0}

    content = result["choices"][0]["message"].get("content", "")
    usage = result.get("usage", {})
    return {
        "content": content,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "latency": round(time.time() - t0, 1),
    }


def parse_verdict(content):
    """Parse PASS/FAIL verdict from judge output."""
    if not content:
        return "UNKNOWN"
    # Look for verdict pattern
    for line in content.split('\n'):
        ls = line.strip().upper()
        if 'VERDICT' in ls or 'JUDGMENT' in ls or 'JUDGEMENT' in ls:
            if 'FAIL' in ls:
                return "FAIL"
            if 'PASS' in ls:
                return "PASS"
    # Fallback: look for PASS/FAIL at start of line
    for line in content.split('\n'):
        ls = line.strip()
        if ls.startswith('PASS') and not ls.startswith('PASS_'):
            return "PASS"
        if ls.startswith('FAIL'):
            return "FAIL"
    # Loose fallback
    upper = content.upper()
    fail_count = upper.count('FAIL')
    pass_count = upper.count('PASS')
    if fail_count > pass_count:
        return "FAIL"
    if pass_count > fail_count:
        return "PASS"
    return "UNKNOWN"


def build_individual_prompt(bug):
    """Build prompt for individual bug review."""
    system = """You are a strict code reviewer (C1 Judge Panel) evaluating a bug fix for python-slugify.

Your task: Review whether the proposed fix correctly and completely addresses the described bug, without introducing regressions.

Evaluation criteria:
1. Does the fix address the root cause?
2. Does the fix handle all edge cases?
3. Does the fix introduce any new bugs or regressions?

Output format:
[VERDICT]: PASS or FAIL
[REASONING]: Your detailed analysis
[Bug ID]: (repeat the bug ID)"""
    
    user = f"""=== SHARED CODE CONTEXT (python-slugify source) ===
```python
{SHARED_CODE}
```

=== BUG TO REVIEW ===
**Bug ID**: {bug['bug_id']}
**Title**: {bug['title']}
**Error Type**: {bug['error_type']}

**Root Cause Analysis (Snake Head)**:
{bug['root_cause']}

**Trigger**: `{bug['trigger']}`
**Expected Output**: {bug['expected']}
**Buggy Output**: {bug['buggy_output']}

**Proposed Fix** (File: {bug['file']}, Line: {bug['line']}):
{bug['fix_description']}

**Fix Code**:
```python
{bug['fix_code']}
```

Evaluate this fix. Does it correctly resolve the bug? Output your verdict."""
    
    return system, user


def build_batch_prompt(bugs):
    """Build prompt for batch review of all 5 bugs."""
    system = """You are a strict code reviewer (C1 Judge Panel) evaluating 5 bug fixes for python-slugify in a batch.

Your task: For EACH bug below, review whether the proposed fix correctly and completely addresses the described bug, without introducing regressions.

Evaluation criteria (per bug):
1. Does the fix address the root cause?
2. Does the fix handle all edge cases?
3. Does the fix introduce any new bugs or regressions?

Output format — for each bug, output a separate block:
---
[Bug ID]: <bug_id>
[VERDICT]: PASS or FAIL
[REASONING]: Your detailed analysis
---

Then after all bugs, output a summary table."""
    
    user_parts = [f"=== SHARED CODE CONTEXT (python-slugify source) ===\n```python\n{SHARED_CODE}\n```\n"]
    user_parts.append("=" * 60)
    user_parts.append("BATCH REVIEW: 5 BUG FIXES")
    user_parts.append("=" * 60)
    
    for i, bug in enumerate(bugs, 1):
        user_parts.append(f"""
--- Bug {i}/{len(bugs)} ---
**Bug ID**: {bug['bug_id']}
**Title**: {bug['title']}
**Error Type**: {bug['error_type']}

**Root Cause Analysis (Snake Head)**:
{bug['root_cause']}

**Trigger**: `{bug['trigger']}`
**Expected Output**: {bug['expected']}
**Buggy Output**: {bug['buggy_output']}

**Proposed Fix** (File: {bug['file']}, Line: {bug['line']}):
{bug['fix_description']}

**Fix Code**:
```python
{bug['fix_code']}```
""")
    
    user_parts.append("\n" + "=" * 60)
    user_parts.append("Evaluate ALL 5 fixes above. For each bug, output [Bug ID], [VERDICT], and [REASONING].")
    
    return system, '\n'.join(user_parts)


def parse_batch_verdicts(content, bugs):
    """Parse verdicts from batch output."""
    results = {}
    for bug in bugs:
        bid = bug['bug_id']
        # Find the block for this bug
        # Look for text between [Bug ID]: bid and next --- or end
        verdict = "UNKNOWN"
        lines = content.split('\n')
        in_block = False
        for line in lines:
            if bid in line and ('Bug ID' in line or 'bug_id' in line.lower()):
                in_block = True
                continue
            if in_block:
                ls = line.strip().upper()
                if ls.startswith('---') or ('Bug ID' in line and bid not in line):
                    break
                if 'VERDICT' in ls or 'JUDGMENT' in ls:
                    if 'FAIL' in ls:
                        verdict = "FAIL"
                    elif 'PASS' in ls:
                        verdict = "PASS"
                    break
        results[bid] = verdict
    
    # If structured parsing failed, try looser
    for bug in bugs:
        bid = bug['bug_id']
        if results[bid] == "UNKNOWN":
            # Search for bid + PASS/FAIL nearby
            idx = content.find(bid)
            if idx >= 0:
                snippet = content[idx:idx+500].upper()
                fail_pos = snippet.find('FAIL')
                pass_pos = snippet.find('PASS')
                if fail_pos >= 0 and (pass_pos < 0 or fail_pos < pass_pos):
                    results[bid] = "FAIL"
                elif pass_pos >= 0:
                    results[bid] = "PASS"
    
    return results


def run_individual_group():
    """Run individual judge reviews: 5 bugs × 3 judges = 15 calls."""
    print("=" * 70)
    print("INDIVIDUAL GROUP: Each bug reviewed separately")
    print("=" * 70)
    
    all_results = []
    
    for bug in BUGS:
        print(f"\n--- {bug['bug_id']} ---")
        system_prompt, user_prompt = build_individual_prompt(bug)
        
        bug_result = {
            "bug_id": bug['bug_id'],
            "judge_results": [],
            "votes": [],
            "total_tokens": 0,
            "total_latency": 0,
            "verdict": "UNKNOWN",
        }
        
        for judge in JUDGES:
            print(f"  Calling {judge['name']}...", end=' ', flush=True)
            result = call_llm(
                judge['model'], judge['temperature'], judge['max_tokens'],
                system_prompt, user_prompt
            )
            
            if "error" in result:
                print(f"ERROR: {result['error']}")
                bug_result["judge_results"].append({
                    "judge": judge['name'],
                    "error": result['error'],
                    "verdict": "UNKNOWN",
                })
                bug_result["votes"].append("UNKNOWN")
                continue
            
            verdict = parse_verdict(result['content'])
            print(f"{verdict} ({result['total_tokens']} tok, {result['latency']}s)")
            
            bug_result["judge_results"].append({
                "judge": judge['name'],
                "model": judge['model'],
                "temperature": judge['temperature'],
                "verdict": verdict,
                "prompt_tokens": result['prompt_tokens'],
                "completion_tokens": result['completion_tokens'],
                "total_tokens": result['total_tokens'],
                "latency": result['latency'],
                "content": result['content'][:500] + "..." if len(result['content']) > 500 else result['content'],
            })
            bug_result["votes"].append(verdict)
            bug_result["total_tokens"] += result['total_tokens']
            bug_result["total_latency"] += result['latency']
        
        # Majority vote
        pass_cnt = bug_result["votes"].count("PASS")
        fail_cnt = bug_result["votes"].count("FAIL")
        if pass_cnt >= 2:
            bug_result["verdict"] = "PASS"
        elif fail_cnt >= 2:
            bug_result["verdict"] = "FAIL"
        else:
            bug_result["verdict"] = "DEADLOCK"
        
        print(f"  => Majority: {bug_result['verdict']} (P:{pass_cnt} F:{fail_cnt}) Total: {bug_result['total_tokens']} tok")
        
        all_results.append(bug_result)
    
    return all_results


def run_batch_group():
    """Run batch judge review: 5 bugs × 1 batch × 3 judges = 3 calls."""
    print("\n" + "=" * 70)
    print("BATCH GROUP: All 5 bugs reviewed in one batch")
    print("=" * 70)
    
    system_prompt, user_prompt = build_batch_prompt(BUGS)
    
    batch_results = {
        "judge_results": [],
        "bug_verdicts": {},
        "total_tokens": 0,
        "total_latency": 0,
    }
    
    for judge in JUDGES:
        # Batch mode needs more output tokens
        max_tok = 8000 if "deepseek" in judge['model'] else judge['max_tokens']
        print(f"\nCalling {judge['name']} (max_tokens={max_tok})...", end=' ', flush=True)
        result = call_llm(
            judge['model'], judge['temperature'], max_tok,
            system_prompt, user_prompt
        )
        
        if "error" in result:
            print(f"ERROR: {result['error']}")
            batch_results["judge_results"].append({
                "judge": judge['name'],
                "error": result['error'],
            })
            continue
        
        per_bug = parse_batch_verdicts(result['content'], BUGS)
        print(f"OK ({result['total_tokens']} tok, {result['latency']}s)")
        for bid, v in per_bug.items():
            print(f"  {bid}: {v}")
        
        batch_results["judge_results"].append({
            "judge": judge['name'],
            "model": judge['model'],
            "temperature": judge['temperature'],
            "per_bug_verdicts": per_bug,
            "prompt_tokens": result['prompt_tokens'],
            "completion_tokens": result['completion_tokens'],
            "total_tokens": result['total_tokens'],
            "latency": result['latency'],
            "content": result['content'][:1000] + "..." if len(result['content']) > 1000 else result['content'],
        })
        batch_results["total_tokens"] += result['total_tokens']
        batch_results["total_latency"] += result['latency']
    
    # Per-bug majority verdict
    for bug in BUGS:
        bid = bug['bug_id']
        votes = []
        for jr in batch_results["judge_results"]:
            if "per_bug_verdicts" in jr:
                votes.append(jr["per_bug_verdicts"].get(bid, "UNKNOWN"))
        pass_cnt = votes.count("PASS")
        fail_cnt = votes.count("FAIL")
        if pass_cnt >= 2:
            batch_results["bug_verdicts"][bid] = "PASS"
        elif fail_cnt >= 2:
            batch_results["bug_verdicts"][bid] = "FAIL"
        else:
            batch_results["bug_verdicts"][bid] = f"DEADLOCK({','.join(votes)})"
    
    return batch_results


def compare_and_report(individual, batch):
    """Generate comparison report."""
    print("\n" + "=" * 70)
    print("P10 COMPARISON REPORT")
    print("=" * 70)
    
    # Token comparison
    ind_total = sum(r['total_tokens'] for r in individual)
    bat_total = batch['total_tokens']
    ind_input = sum(sum(j.get('prompt_tokens', 0) for j in r['judge_results']) for r in individual)
    bat_input = sum(j.get('prompt_tokens', 0) for j in batch['judge_results'])
    ind_output = sum(sum(j.get('completion_tokens', 0) for j in r['judge_results']) for r in individual)
    bat_output = sum(j.get('completion_tokens', 0) for j in batch['judge_results'])
    
    saving = (ind_total - bat_total) / ind_total * 100 if ind_total > 0 else 0
    input_saving = (ind_input - bat_input) / ind_input * 100 if ind_input > 0 else 0
    
    print(f"\n{'Metric':<30} {'Individual':>15} {'Batch':>15} {'Saving':>12}")
    print("-" * 72)
    print(f"{'Total Tokens':<30} {ind_total:>15,} {bat_total:>15,} {saving:>11.1f}%")
    print(f"{'Input Tokens':<30} {ind_input:>15,} {bat_input:>15,} {input_saving:>11.1f}%")
    print(f"{'Output Tokens':<30} {ind_output:>15,} {bat_output:>15,} {(ind_output-bat_output)/ind_output*100 if ind_output else 0:>11.1f}%")
    print(f"{'API Calls':<30} {sum(len(r['judge_results']) for r in individual):>15} {len(batch['judge_results']):>15}")
    
    # Verdict consistency
    print(f"\n{'Bug ID':<30} {'Individual':>12} {'Batch':>12} {'Match':>8}")
    print("-" * 65)
    matches = 0
    total = 0
    for r in individual:
        bid = r['bug_id']
        ind_v = r['verdict']
        bat_v = batch['bug_verdicts'].get(bid, 'N/A')
        match = "YES" if ind_v == bat_v else "NO"
        if ind_v == bat_v:
            matches += 1
        total += 1
        short_id = bid.replace('bug-','')
        print(f"{short_id:<30} {ind_v:>12} {bat_v:>12} {match:>8}")
    
    print(f"\nVerdict Consistency: {matches}/{total} ({matches/total*100:.0f}%)")
    
    # Per-judge token breakdown
    print(f"\n{'Judge':<15} {'Indiv Tok':>12} {'Batch Tok':>12} {'Saving':>10}")
    print("-" * 52)
    for ji, judge in enumerate(JUDGES):
        jname = judge['name']
        ind_jtok = sum(r['judge_results'][ji].get('total_tokens', 0) for r in individual if ji < len(r['judge_results']))
        bat_jtok = batch['judge_results'][ji].get('total_tokens', 0) if ji < len(batch['judge_results']) else 0
        jsave = (ind_jtok - bat_jtok) / ind_jtok * 100 if ind_jtok > 0 else 0
        print(f"{jname:<15} {ind_jtok:>12,} {bat_jtok:>12,} {jsave:>9.1f}%")
    
    return {
        "individual_total_tokens": ind_total,
        "batch_total_tokens": bat_total,
        "individual_input_tokens": ind_input,
        "batch_input_tokens": bat_input,
        "individual_output_tokens": ind_output,
        "batch_output_tokens": bat_output,
        "token_saving_pct": round(saving, 1),
        "input_token_saving_pct": round(input_saving, 1),
        "verdict_consistency": f"{matches}/{total}",
        "verdict_consistency_pct": round(matches/total*100, 0),
        "individual_api_calls": sum(len(r['judge_results']) for r in individual),
        "batch_api_calls": len(batch['judge_results']),
    }


def main():
    print("P10: 批量法官审查验证")
    print(f"Bugs: {len(BUGS)} | Judges: {len(JUDGES)} (C1: DSx2+Gemini)")
    print(f"Expected: batch mode saves 40-50% judge tokens\n")
    
    # ── Individual Group ──
    individual = run_individual_group()
    
    # ── Batch Group ──
    batch = run_batch_group()
    
    # ── Compare ──
    comparison = compare_and_report(individual, batch)
    
    # ── Save Results ──
    output = {
        "experiment": "P10-batch-judge-review",
        "description": "Compare individual vs batch C1 judge review for token cost and verdict consistency",
        "judge_config": "C1: deepseek-v4-pro(t=0.3) + deepseek-v4-pro(t=0.7) + gemini-3.6-flash(t=0.3)",
        "api_provider": "tokeness (https://n.tokeness.io/v1)",
        "date": "2026-08-05",
        "bug_count": len(BUGS),
        "bugs": [b['bug_id'] for b in BUGS],
        "individual_group": individual,
        "batch_group": batch,
        "comparison": comparison,
        "verdict_consistency_analysis": {
            "matches": comparison['verdict_consistency'],
            "details": [
                {"bug_id": r['bug_id'], "individual": r['verdict'], "batch": batch['bug_verdicts'].get(r['bug_id'])}
                for r in individual
            ]
        }
    }
    
    out_path = "<SNAKE_SWARM_DATA>/experiments/results/p10_batch_judge.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {out_path}")
    print(f"File size: {os.path.getsize(out_path):,} bytes")


if __name__ == '__main__':
    main()
