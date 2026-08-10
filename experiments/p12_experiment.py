#!/usr/bin/env python3
"""
P12: 蛇头分析缓存验证 — 同一文件多bug场景下增量分析节省蛇头token
实验：冷缓存(全文件) vs 温缓存(增量) 对比

用法: python p12_experiment.py
"""
import json, yaml, time, sys, re, os
import requests

# =============================================================================
# Configuration
# =============================================================================
API_BASE = "https://n.tokeness.io/v1"
MODEL = "deepseek-v4-pro"
TEMPERATURE = 0.3

# Load API key from config
import os as _os
_config_paths = [
    _os.environ.get('HERMES_CONFIG'),
    _os.path.expanduser('~/.hermes/config.yaml'),
    _os.path.expanduser('~/AppData/Local/hermes/config.yaml'),
]
_config_path = next((p for p in _config_paths if p and _os.path.exists(p)), None)
if _config_path:
    with open(_config_path, 'r') as f:
        config = yaml.safe_load(f)
API_KEY = None
for p in config.get('custom_providers', []):
    if p['name'] == 'tokeness':
        API_KEY = p['api_key']
        break
assert API_KEY, "Tokeness API key not found!"

# Load P8 data
with open(r'D:\competation\design\experiments\results\p8_case_study.json', 'r') as f:
    p8_data = json.load(f)

# Load slugify source
with open(r'D:\competation\design\experiments\p8_work\slugify\slugify.py', 'r') as f:
    SLUGIFY_SOURCE = f.read()
SLUGIFY_LINES = SLUGIFY_SOURCE.split('\n')

# =============================================================================
# Bug definitions
# =============================================================================
BUGS = {}
for b in p8_data['bugs']:
    BUGS[b['bug_id']] = {
        'title': b['title'],
        'error_type': b['error_type'],
        'root_cause': b['root_cause'],
        'trigger': b['trigger'],
        'expected': b['expected'],
        'buggy_output': b['buggy_output'],
        'expected_fix': b.get('snake_swarm_solution', ''),
    }

# Map each bug to its primary function
BUG_FUNCTION_MAP = {
    'bug-185-max-length': 'smart_truncate',
    'bug-186-empty-separator': 'smart_truncate',
    'bug-178-malformed-entities': 'slugify',
    'bug-179-self-referential': 'slugify',
    'bug-148-uppercase-return': 'add_uppercase_char',
}

# =============================================================================
# Source code extraction helpers
# =============================================================================
def extract_function_source(source_lines, func_name, context_lines=5):
    """Extract full source of a named function + context"""
    in_func = False
    func_start = None
    func_end = None
    indent_level = None
    
    for i, line in enumerate(source_lines):
        if line.startswith('def ' + func_name + '('):
            func_start = i
            in_func = True
            indent_level = len(line) - len(line.lstrip())
            continue
        if in_func:
            # Check if we're back at the same or lower indent (function ended)
            stripped = line.lstrip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('"""'):
                current_indent = len(line) - len(stripped)
                if current_indent <= indent_level and stripped:
                    func_end = i
                    break
    
    if func_start is None:
        return None, None, None
    
    if func_end is None:
        func_end = len(source_lines)
    
    # Include context lines before and after
    ctx_start = max(0, func_start - context_lines)
    ctx_end = min(len(source_lines), func_end + context_lines)
    
    func_code = '\n'.join(source_lines[func_start:func_end])
    full_extract = '\n'.join(source_lines[ctx_start:ctx_end])
    
    return func_code, full_extract, (func_start + 1, func_end)  # 1-indexed lines

def extract_global_vars(source_lines):
    """Extract global variable names and values"""
    globals_info = []
    for i, line in enumerate(source_lines):
        stripped = line.strip()
        if re.match(r'^[A-Z_][A-Z_0-9]*\s*=', stripped):
            name = stripped.split('=')[0].strip()
            value = stripped.split('=', 1)[1].strip()
            globals_info.append({'name': name, 'value': value, 'line': i+1})
    return globals_info

def extract_function_signatures(source_lines):
    """Extract function signatures and call relationships"""
    funcs = []
    for i, line in enumerate(source_lines):
        if line.startswith('def '):
            sig = line.strip()
            name = re.match(r'def (\w+)', sig).group(1)
            funcs.append({'name': name, 'signature': sig, 'line': i+1})
    return funcs

def build_cache():
    """Build deterministic code cache from source analysis"""
    lines = SLUGIFY_LINES
    globals_info = extract_global_vars(lines)
    funcs = extract_function_signatures(lines)
    
    # Build function summaries
    cache = {
        'file': 'slugify.py',
        'total_lines': len(lines),
        'functions': [],
        'globals': [g['name'] for g in globals_info],
        'call_graph': {
            'slugify': {
                'calls': ['smart_truncate', '_safe_chr'],
                'called_by': [],
                'line': 78,
                'params': 'text, entities=True, decimal=True, hexadecimal=True, max_length=0, word_boundary=False, separator="-", save_order=False, stopwords=(), regex_pattern=None, lowercase=True, replacements=(), allow_unicode=False'
            },
            'smart_truncate': {
                'calls': [],
                'called_by': ['slugify'],
                'line': 27,
                'params': 'string, max_length=0, word_boundary=False, separator=" ", save_order=False'
            },
            '_safe_chr': {
                'calls': [],
                'called_by': ['slugify'],
                'line': 139,
                'params': 'codepoint, original',
                'note': 'inline helper defined inside slugify()'
            },
            'add_uppercase_char': {
                'calls': [],
                'called_by': [],
                'line': 'N/A (not in this file - defined in __init__.py or helpers)',
                'params': 'char_list',
                'note': 'Generates PRE_TRANSLATIONS uppercase entries. Not a standalone function in slugify.py'
            }
        }
    }
    
    # Full function sources (used in cache)
    for func in funcs:
        code, _, line_range = extract_function_source(lines, func['name'])
        cache['functions'].append({
            'name': func['name'],
            'line_range': line_range,
            'full_code': code,
            'params': cache['call_graph'].get(func['name'], {}).get('params', ''),
        })
    
    return cache

# =============================================================================
# Prompt builders
# =============================================================================
SYSTEM_PROMPT = """你是一个代码分析专家（蛇头/Snake Head），负责对bug报告进行根因分析。
你的任务是：阅读提供的代码和bug信息，找出bug的根本原因，定位到具体函数和代码行，并给出修复建议。

输出格式（严格JSON）：
{
  "bug_id": "bug-xxx",
  "affected_function": "函数名",
  "affected_lines": [起始行, 结束行],
  "root_cause_analysis": "根因分析（简洁）",
  "fix_suggestion": "修复建议（代码diff）",
  "confidence": "high/medium/low",
  "analysis_quality_notes": "分析质量自评"
}"""

def build_cold_prompt(bug_id):
    """Build cold cache prompt: system + full file + bug"""
    bug = BUGS[bug_id]
    
    user_prompt = f"""## Bug 报告
**Bug ID**: {bug_id}
**标题**: {bug['title']}
**错误类型**: {bug['error_type']}
**触发条件**: {bug['trigger']}
**期望输出**: {bug['expected']}
**实际错误输出**: {bug['buggy_output']}

## 源代码文件: slugify.py (完整内容)
```python
{SLUGIFY_SOURCE}
```

## 任务
分析以上代码，找出此bug的根本原因，定位到具体函数和代码行，并给出修复建议。"""
    
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

def build_warm_prompt(bug_id, cache):
    """Build warm cache prompt: system + cache + targeted function + bug"""
    bug = BUGS[bug_id]
    func_name = BUG_FUNCTION_MAP[bug_id]
    
    # Build cache summary
    cache_lines = []
    cache_lines.append("## 代码缓存（来自之前分析的函数依赖图）")
    cache_lines.append(f"**文件**: {cache['file']} ({cache['total_lines']} 行)")
    cache_lines.append(f"**全局变量**: {', '.join(cache['globals'])}")
    cache_lines.append("")
    cache_lines.append("### 函数调用关系图")
    for fname, info in cache['call_graph'].items():
        calls_str = ', '.join(info['calls']) if info['calls'] else '无'
        called_by_str = ', '.join(info['called_by']) if info['called_by'] else '无'
        cache_lines.append(f"- **{fname}**({info['params']})")
        cache_lines.append(f"  - 行号: {info['line']}")
        cache_lines.append(f"  - 调用: [{calls_str}]")
        cache_lines.append(f"  - 被调用: [{called_by_str}]")
        if 'note' in info:
            cache_lines.append(f"  - 备注: {info['note']}")
    
    # Find the targeted function's code
    func_code = None
    for f in cache['functions']:
        if f['name'] == func_name:
            func_code = f['full_code']
            break
    
    # For add_uppercase_char, it's in special.py not slugify.py
    if func_code is None and func_name == 'add_uppercase_char':
        special_path = r'D:\competation\design\experiments\p8_work\slugify\special.py'
        if os.path.exists(special_path):
            with open(special_path, 'r') as f:
                special_source = f.read()
            lines = special_source.split('\n')
            for i, line in enumerate(lines):
                if 'def add_uppercase_char' in line:
                    # Extract function (lines i to i+10)
                    func_code = '\n'.join(lines[i:min(i+12, len(lines))])
                    break
        if func_code is None:
            func_code = "# add_uppercase_char 在 special.py 中定义\n# Bug: return 语句缩进在 for 循环内部\n# 参考: P8 case study"
    
    cache_summary = '\n'.join(cache_lines)
    
    # Other functions' signature summaries
    sig_summaries = []
    for f in cache['functions']:
        if f['name'] != func_name:
            sig_summaries.append(f"- **{f['name']}** (行 {f['line_range'][0]}-{f['line_range'][1]}): 签名见调用图，完整代码省略（已缓存）")
    
    sig_summary_text = '\n'.join(sig_summaries) if sig_summaries else '无其他函数'
    
    user_prompt = f"""{cache_summary}

### 其他函数签名摘要
{sig_summary_text}

## Bug 报告
**Bug ID**: {bug_id}
**标题**: {bug['title']}
**错误类型**: {bug['error_type']}
**触发条件**: {bug['trigger']}
**期望输出**: {bug['expected']}
**实际错误输出**: {bug['buggy_output']}

## 目标函数完整代码: {func_name}
```python
{func_code}
```

## 任务
基于以上缓存信息和目标函数代码，分析此bug的根本原因，定位到具体代码行，并给出修复建议。"""
    
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

# =============================================================================
# API call
# =============================================================================
def call_api(messages, label="unknown"):
    """Call tokeness API with deepseek-v4-pro, return response + token usage"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": 2048,
    }
    
    t0 = time.time()
    try:
        resp = requests.post(
            f"{API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed = time.time() - t0
        
        usage = data.get('usage', {})
        content = data['choices'][0]['message']['content']
        
        return {
            'success': True,
            'label': label,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
            'elapsed_seconds': round(elapsed, 2),
            'content': content,
            'model': data.get('model', MODEL),
        }
    except Exception as e:
        return {
            'success': False,
            'label': label,
            'error': str(e),
            'elapsed_seconds': round(time.time() - t0, 2),
        }

def estimate_tokens(text):
    """Rough token estimate: chars/3.5 for code-heavy text"""
    return len(text) / 3.5

# =============================================================================
# Parse LLM response
# =============================================================================
def parse_analysis(response_text):
    """Try to parse JSON from LLM response"""
    # Try to find JSON block
    json_match = re.search(r'\{[^{}]*"bug_id"[^{}]*\}', response_text, re.DOTALL)
    if not json_match:
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
    
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except:
            pass
    
    return {"raw_response": response_text[:500]}

# =============================================================================
# Main experiment
# =============================================================================
def run_experiment():
    print("=" * 70)
    print("P12: 蛇头分析缓存验证实验")
    print(f"Model: {MODEL} (temperature={TEMPERATURE})")
    print(f"API: {API_BASE}")
    print("=" * 70)
    
    results = {
        'experiment': 'P12_head_analysis_cache',
        'model': MODEL,
        'temperature': TEMPERATURE,
        'api': API_BASE,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'design': {
            'cold_cache_group': 'bug-185, full slugify.py (195 lines)',
            'warm_cache_group': 'bug-186/178/148/179, cache + targeted function only',
            'cache_contents': 'function list, call graph, global vars, targeted function full code, other functions signature-only',
            'hypothesis': '温缓存每次分析节省≥15% prompt tokens vs 冷缓存'
        },
        'cache': {},
        'runs': [],
        'comparison': {},
    }
    
    # Step 1: Build cache (deterministic, from source analysis)
    print("\n[Step 1] 构建代码缓存...")
    cache = build_cache()
    results['cache'] = {
        'functions': [f['name'] for f in cache['functions']],
        'globals': cache['globals'],
        'call_graph_summary': {k: {'calls': v['calls'], 'called_by': v['called_by']} for k, v in cache['call_graph'].items()}
    }
    print(f"  缓存构建完成: {len(cache['functions'])} 个函数, {len(cache['globals'])} 个全局变量, {len(cache['call_graph'])} 个调用关系节点")
    
    # Compute estimated prompt sizes
    cold_prompt_est = build_cold_prompt('bug-185-max-length')
    cold_est_tokens = estimate_tokens(cold_prompt_est[1]['content'])
    print(f"\n  冷缓存提示词估算: ~{cold_est_tokens:.0f} tokens (字符数: {len(cold_prompt_est[1]['content'])})")
    
    for bid in ['bug-186-empty-separator', 'bug-178-malformed-entities', 'bug-148-uppercase-return', 'bug-179-self-referential']:
        warm_prompt_est = build_warm_prompt(bid, cache)
        warm_est_tokens = estimate_tokens(warm_prompt_est[1]['content'])
        ratio = warm_est_tokens / cold_est_tokens * 100
        print(f"  温缓存 {bid}: ~{warm_est_tokens:.0f} tokens (字符数: {len(warm_prompt_est[1]['content'])}) — {ratio:.1f}% of cold")
    
    # Step 2: Cold cache run (bug-185, full file)
    print("\n[Step 2] 冷缓存基线运行: bug-185 (全文件)...")
    cold_messages = build_cold_prompt('bug-185-max-length')
    cold_prompt_char_count = len(cold_messages[1]['content'])
    print(f"  提示词大小: {cold_prompt_char_count} 字符")
    
    cold_result = call_api(cold_messages, 'cold_bug-185')
    if cold_result['success']:
        print(f"  ✅ prompt_tokens={cold_result['prompt_tokens']}, completion_tokens={cold_result['completion_tokens']}, total={cold_result['total_tokens']}, elapsed={cold_result['elapsed_seconds']}s")
    else:
        print(f"  ❌ 失败: {cold_result['error']}")
    
    cold_result['prompt_char_count'] = cold_prompt_char_count
    cold_result['cache_type'] = 'cold'
    results['runs'].append(cold_result)
    
    if not cold_result['success']:
        print("冷缓存失败，终止实验")
        return results
    
    # Step 3: Warm cache runs
    warm_bugs = [
        ('bug-186-empty-separator', 'smart_truncate'),
        ('bug-178-malformed-entities', 'slugify'),
        ('bug-148-uppercase-return', 'add_uppercase_char'),
        ('bug-179-self-referential', 'slugify'),
    ]
    
    warm_results = []
    for step_idx, (bid, func_name) in enumerate(warm_bugs):
        step_num = step_idx + 3
        print(f"\n[Step {step_num}] 温缓存运行: {bid} (目标函数: {func_name})...")
        
        warm_messages = build_warm_prompt(bid, cache)
        warm_prompt_char_count = len(warm_messages[1]['content'])
        print(f"  提示词大小: {warm_prompt_char_count} 字符")
        
        warm_result = call_api(warm_messages, f'warm_{bid}')
        if warm_result['success']:
            print(f"  ✅ prompt_tokens={warm_result['prompt_tokens']}, completion_tokens={warm_result['completion_tokens']}, total={warm_result['total_tokens']}, elapsed={warm_result['elapsed_seconds']}s")
        else:
            print(f"  ❌ 失败: {warm_result['error']}")
        
        warm_result['prompt_char_count'] = warm_prompt_char_count
        warm_result['cache_type'] = 'warm'
        warm_result['target_function'] = func_name
        results['runs'].append(warm_result)
        warm_results.append(warm_result)
    
    # Step 4: Comparison
    print("\n" + "=" * 70)
    print("对比分析")
    print("=" * 70)
    
    if all(r['success'] for r in warm_results):
        cold_pt = cold_result['prompt_tokens']
        cold_ct = cold_result['completion_tokens']
        cold_tt = cold_result['total_tokens']
        
        warm_pts = [r['prompt_tokens'] for r in warm_results]
        warm_cts = [r['completion_tokens'] for r in warm_results]
        warm_tts = [r['total_tokens'] for r in warm_results]
        
        avg_warm_pt = sum(warm_pts) / len(warm_pts)
        avg_warm_ct = sum(warm_cts) / len(warm_cts)
        avg_warm_tt = sum(warm_tts) / len(warm_tts)
        
        # Per-bug comparison
        print("\n逐bug Prompt Token对比:")
        print(f"  冷缓存 (bug-185): {cold_pt:,} prompt tokens")
        for i, (bid, _) in enumerate(warm_bugs):
            savings = (1 - warm_pts[i]/cold_pt) * 100
            print(f"  温缓存 ({bid}): {warm_pts[i]:,} prompt tokens — 节省 {savings:+.1f}%")
        
        avg_savings_pt = (1 - avg_warm_pt / cold_pt) * 100
        avg_savings_tt = (1 - avg_warm_tt / cold_tt) * 100
        
        print(f"\n平均 Prompt Token 节省: {avg_savings_pt:+.1f}%")
        print(f"平均 Total Token 节省: {avg_savings_tt:+.1f}%")
        
        # Pipeline-level savings
        total_cold_pipeline = cold_tt * 5  # hypothetical 5 all-cold runs
        total_warm_pipeline = cold_tt + sum(warm_tts)  # 1 cold + 4 warm
        pipeline_savings = (1 - total_warm_pipeline / total_cold_pipeline) * 100
        print(f"\n管道级 Total Token 节省: {pipeline_savings:+.1f}%")
        print(f"  (5×冷缓存={total_cold_pipeline:,} vs 1×冷+4×温={total_warm_pipeline:,})")
        
        results['comparison'] = {
            'cold_prompt_tokens': cold_pt,
            'cold_completion_tokens': cold_ct,
            'cold_total_tokens': cold_tt,
            'warm_prompt_tokens': warm_pts,
            'warm_completion_tokens': warm_cts,
            'warm_total_tokens': warm_tts,
            'avg_warm_prompt_tokens': avg_warm_pt,
            'avg_warm_completion_tokens': avg_warm_ct,
            'avg_warm_total_tokens': avg_warm_tt,
            'per_bug_prompt_savings_pct': [(1 - wp/cold_pt)*100 for wp in warm_pts],
            'avg_prompt_savings_pct': avg_savings_pt,
            'avg_total_savings_pct': avg_savings_tt,
            'pipeline_total_savings_pct': pipeline_savings,
            'hypothesis_met_15pct': avg_savings_pt >= 15.0,
        }
    
    # Step 5: Quality analysis
    print("\n" + "=" * 70)
    print("分析质量评估")
    print("=" * 70)
    
    quality_scores = {}
    for run in results['runs']:
        if not run['success']:
            continue
        parsed = parse_analysis(run['content'])
        bug_id = run['label'].replace('cold_', '').replace('warm_', '')
        
        # Check if the analysis correctly identified the function
        expected_func = BUG_FUNCTION_MAP.get(bug_id, 'unknown')
        actual_func = parsed.get('affected_function', 'N/A')
        
        # Check confidence
        confidence = parsed.get('confidence', 'N/A')
        
        # Basic quality check: did it identify the right function?
        func_match = actual_func == expected_func if actual_func != 'N/A' else False
        
        quality_scores[bug_id] = {
            'expected_function': expected_func,
            'identified_function': actual_func,
            'function_match': func_match,
            'confidence': confidence,
            'cache_type': run['cache_type'],
            'root_cause_snippet': parsed.get('root_cause_analysis', parsed.get('raw_response', ''))[:200],
        }
        
        match_icon = '✅' if func_match else '⚠️'
        print(f"  {match_icon} {bug_id} ({run['cache_type']}): expected={expected_func}, got={actual_func}, confidence={confidence}")
    
    results['quality'] = quality_scores
    
    return results

# =============================================================================
# Entry point
# =============================================================================
if __name__ == '__main__':
    results = run_experiment()
    
    # Save results
    output_path = r'D:\competation\design\experiments\results\p12_head_cache.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存: {output_path}")
    
    # Print summary
    comp = results.get('comparison', {})
    if comp:
        print(f"\n{'='*70}")
        print("实验结论")
        print(f"{'='*70}")
        print(f"冷缓存 Prompt Tokens: {comp.get('cold_prompt_tokens', 'N/A'):,}")
        print(f"温缓存 平均 Prompt Tokens: {comp.get('avg_warm_prompt_tokens', 'N/A'):,.0f}")
        print(f"平均 Prompt Token 节省: {comp.get('avg_prompt_savings_pct', 'N/A'):+.1f}%")
        print(f"15%节省目标: {'✅ 达标' if comp.get('hypothesis_met_15pct', False) else '❌ 未达标'}")
