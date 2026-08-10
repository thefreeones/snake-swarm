"""
[已废弃] 预评分蛇 (Pre-Scoring Snake)
被 profile_matcher.py 取代 — 见 v0.6 任务剖面体系。

保留此文件作为：
1. 回退机制：当任务无匹配剖面时，临时评估Z值
2. 新剖面候选生成：临时评估的结果经人工审核后可固化为新剖面
3. 历史参考：v0.6-B实验验证了四维建模的可行性

不再用于主路由决策。使用 profile_matcher.route() 代替。
"""
import json, os, urllib.request, urllib.error

API_BASE = "https://n.tokeness.io/v1/chat/completions"
MODEL = "claude-sonnet-5"
API_KEY = None

def _load_key():
    global API_KEY
    keyfile = os.path.join(os.path.dirname(__file__), "experiments", ".tokeness_key.txt")
    if not os.path.exists(keyfile):
        raise RuntimeError(f"API key not found at {keyfile}")
    with open(keyfile) as f:
        API_KEY = f.read().strip()

def temporary_score(task_description: str) -> dict:
    """
    临时Z轴评估（回退机制）
    仅在任务无匹配剖面时使用。
    结果不应直接用于路由——应标记为候选剖面，经人工审核后固化。
    """
    if not API_KEY:
        _load_key()

    prompt = f"""评估以下任务的复杂度。严格回答3个问题(各1-3分)：

Q1: 几步独立推理步骤？
Q2: 几个知识领域？
Q3: 描述是否有歧义/缺失信息？

任务: {task_description}

只输出JSON: {{"Q1": int, "Q2": int, "Q3": int, "Z": float (Z=(Q1+Q2+Q3-3)/6*9), "reasoning": "简述"}}"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "任务复杂度评估器。只输出JSON。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1, "max_tokens": 256
    }

    req = urllib.request.Request(API_BASE, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"})

    with urllib.request.urlopen(req, timeout=30) as resp:
        content = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start:end+1])
        return {"error": "parse_failed", "raw": content}
