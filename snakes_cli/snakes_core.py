"""
蛇群核心引擎 (Snakes Core) v1.0
可被CLI/API/GitHub Action调用的独立核心。

用法:
    from snakes_core import Snakes
    snakes = Snakes(api_key="sk-...", base_url="https://n.tokeness.io/v1")
    result = snakes.fix(file="slugify.py", function="smart_truncate", bug_description="...")
    print(result.patch)
"""
import os
import json
import time
import re
from dataclasses import dataclass, field
from typing import Optional

import requests


# ================================================================
# 配置
# ================================================================
DEFAULT_MODELS = {
    "heavy_head": "claude-sonnet-5",       # L3+ 重蛇头
    "light_head": "deepseek-v4-pro",       # L1/L2 轻蛇头
    "fix_snake": "deepseek-v4-pro",        # 修复蛇
    "rewrite_snake": "gemini-3.6-flash",   # 黑箱重写
    "judge_semantic": "deepseek-v4-pro",   # 法官A: 语义正确性
    "judge_test": "deepseek-v4-pro",       # 法官B: 测试证据
    "judge_contract": "gemini-3.6-flash",  # 法官C: 架构/契约
    "arbitrator": "claude-sonnet-5",       # 仲裁器(1:1:1时)
}

DEFAULT_TEMPERATURE = {
    "head": 0.3,
    "fix": 0.3,
    "rewrite": 0.3,
    "judge_semantic": 0.3,
    "judge_test": 0.7,
    "judge_contract": 0.3,
    "arbitrator": 0.3,
}

# ================================================================
# v0.7 角色化法官 Prompt
# ================================================================
JUDGE_ROLES = {
    "semantic": {
        "name": "语义正确性法官",
        "focus": "业务逻辑、函数语义、边界条件、意图一致性",
        "system": """你是蛇群的语义正确性法官。你的角色是审查修复代码的**语义正确性**。

审查重点:
1. 修复是否真正解决了根因（而非绕过症状）
2. 函数语义是否保持一致（输入→输出关系未改变）
3. 边界条件是否被正确处理（空值/零值/负值/极大值）
4. 修复是否引入了新的逻辑错误

输出规则:
- 先列出证据，再给出判断
- 必须标注无法确认的项
- 不输出"我认为应该通过"这类主观判断
- 用JSON格式输出（见下方格式要求）""",
    },
    "test_evidence": {
        "name": "测试证据法官",
        "focus": "测试覆盖、回归验证、可复现性",
        "system": """你是蛇群的测试证据法官。你的角色是从**测试和验证证据**的角度审查修复。

审查重点:
1. 修复代码是否可以通过已有测试
2. 测试是否真正覆盖了变更路径（非虚假通过）
3. 是否存在因修复而暴露的新边界
4. 修复代码是否包含可验证的断言

输出规则:
- 基于具体测试证据，不做推测性判断
- 标注无法确认的测试盲区
- 用JSON格式输出（见下方格式要求）""",
    },
    "contract": {
        "name": "架构契约法官",
        "focus": "接口契约、模块边界、依赖关系、API兼容性",
        "system": """你是蛇群的架构契约法官。你的角色是审查修复是否**保持架构约束**。

审查重点:
1. 函数签名是否保持不变（参数/返回值类型）
2. 公共API是否被意外修改
3. 是否引入了新的外部依赖
4. 模块边界是否被破坏
5. 框架约定是否被遵守

输出规则:
- 基于diff和类型签名，不做语义推测
- 标注无法确认的兼容性风险
- 用JSON格式输出（见下方格式要求）""",
    },
}

JUDGE_OUTPUT_FORMAT = """请用以下JSON格式输出你的审查结果（只输出JSON，不要其他文字）:

{
  "verdict": "pass | fail | uncertain",
  "confidence": 0.0-1.0,
  "severity": "P0 | P1 | P2 | P3",
  "evidence_refs": ["证据1", "证据2"],
  "reasoning": "判定理由",
  "counterevidence": "对立面证据（如果有）",
  "uncertainty": ["无法确认的项"]
}"""

# L1/L2 bug 关键词 → 轻量蛇头
L1_L2_KEYWORDS = [
    "条件判断", "边界条件", "缩进错误", "语法错误",
    "condition", "boundary", "indentation", "syntax",
    "missing check", "missing guard", "missing validation",
    "typo", "off-by-one", "null check", "none check",
]


# ================================================================
# 数据结构
# ================================================================
@dataclass
class FixResult:
    """一次修复的完整结果"""
    bug_id: str
    success: bool
    patch: str = ""
    root_cause: str = ""
    fix_description: str = ""
    tokens: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)
    error: str = ""
    template_hit: Optional[str] = None
    rewrite_attempted: bool = False  # v0.7 黑箱重写是否触发
    tail_report: Optional['TailReport'] = None  # v0.7 蛇尾自述


@dataclass
class BatchResult:
    """批量修复结果"""
    results: list = field(default_factory=list)
    total_tokens: int = 0
    template_hits: int = 0
    success_count: int = 0
    fail_count: int = 0


@dataclass
class JudgeVerdict:
    """单个法官的裁决结果 (v0.7)"""
    role: str          # "semantic" | "test_evidence" | "contract"
    verdict: str       # "pass" | "fail" | "uncertain"
    confidence: float
    severity: str      # "P0" | "P1" | "P2" | "P3"
    evidence_refs: list
    reasoning: str
    counterevidence: str
    uncertainty: list


@dataclass
class AdjudicationResult:
    """三角色裁决的汇总结果 (v0.7)"""
    verdicts: list                 # [JudgeVerdict, ...]
    final_verdict: str             # "pass" | "fail" | "conflict" | "escalated"
    conflict_type: str             # "" | "2:1" | "1:1:1" | "hetero_dissent"
    minority_preserved: bool
    total_tokens: int
    summary: str


@dataclass
class TailReport:
    """蛇尾结构化自述 (v0.7)"""
    fact: dict        # 系统自动填充: modified_files, diff_lines, test_passed, test_total
    inference: dict   # 模型生成+证据: impact_scope, risk_assessment, edge_cases_covered
    uncertainty: list # 强制列出无法确认项
    validated: bool   # claims vs system records 一致性校验结果
    validation_issues: list  # 校验发现的不一致


# ================================================================
# 模板缓存 (P13)
# ================================================================
FIX_TEMPLATES = {
    "dict_get": {
        "name": "字典键安全访问",
        "detect": ["keyerror", "dict[", "['"],
        "fix": "dict.get('key')",
    },
    "truthiness_check": {
        "name": "真值判断陷阱",
        "detect": ["not max", "not min", "not count", "if not"],
        "fix": "显式比较: if param <= 0:",
    },
    "empty_separator": {
        "name": "空分隔符守卫",
        "detect": ["separator", ".split("],
        "fix": "if not separator: guard before split()",
    },
    "shallow_copy": {
        "name": "浅拷贝陷阱",
        "detect": ["] *", "shallow", "copy"],
        "fix": "copy.deepcopy()",
    },
    "broad_except": {
        "name": "宽泛异常捕获",
        "detect": ["except Exception", "try/except"],
        "fix": "缩小异常范围到每个元素",
    },
    "missing_type_check": {
        "name": "类型校验缺失",
        "detect": ["type", "isinstance", "bool", "str input"],
        "fix": "isinstance检查 + bool显式拦截",
    },
}


# ================================================================
# 核心引擎
# ================================================================
class Snakes:
    """蛇群核心引擎"""

    def __init__(self, api_key: str, base_url: str = "https://n.tokeness.io/v1",
                 models: dict = None, temperature: dict = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.models = {**DEFAULT_MODELS, **(models or {})}
        self.temp = {**DEFAULT_TEMPERATURE, **(temperature or {})}
        self._file_cache = {}  # P12 文件级缓存
        self._template_hits = 0

    # ── LLM调用 ──────────────────────────────
    def _call(self, model: str, system: str, user: str,
              temperature: float = 0.3, max_tokens: int = 4096) -> dict:
        """底层LLM调用"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "prompt_tokens": data["usage"]["prompt_tokens"],
            "completion_tokens": data["usage"]["completion_tokens"],
            "total_tokens": data["usage"]["total_tokens"],
        }

    # ── 复杂度判定 ─────────────────────────
    def _classify_complexity(self, bug_description: str, error_type: str = "") -> str:
        """判定bug复杂度: L1/L2(轻量) 或 L3+(重量)"""
        desc = (bug_description + error_type).lower()
        for kw in L1_L2_KEYWORDS:
            if kw.lower() in desc:
                return "light"
        return "heavy"

    # ── P12 文件缓存 ───────────────────────
    def _get_cached_context(self, file_path: str) -> dict:
        """获取文件的缓存上下文(函数依赖图)"""
        if file_path in self._file_cache:
            return self._file_cache[file_path]

        with open(file_path, encoding="utf-8") as f:
            code = f.read()

        # 简单函数提取
        funcs = re.findall(r'^def (\w+)\(', code, re.MULTILINE)
        cache = {
            "code": code,
            "functions": funcs,
            "line_count": len(code.split("\n")),
        }
        self._file_cache[file_path] = cache
        return cache

    # ── P11 分层蛇头 ───────────────────────
    def _run_head(self, file_path: str, function: str, bug_desc: str,
                  error_type: str = "", use_cache: bool = False) -> dict:
        """跑蛇头分析"""
        complexity = self._classify_complexity(bug_desc, error_type)
        model = self.models["light_head"] if complexity == "light" else self.models["heavy_head"]

        cache = self._get_cached_context(file_path)
        full_code = cache["code"]

        if use_cache and len(cache["functions"]) > 1:
            # 温缓存: 仅展示目标函数+摘要
            func_match = re.search(rf'(def {function}\(.*?(?=^def |\Z))', full_code,
                                   re.MULTILINE | re.DOTALL)
            target_code = func_match.group(1) if func_match else full_code
            context = (
                f"文件概要: {len(cache['functions'])}个函数, {cache['line_count']}行\n"
                f"函数签名: {', '.join(cache['functions'][:10])}...\n\n"
                f"目标函数代码:\n```python\n{target_code}\n```"
            )
        else:
            # 冷缓存: 全文件
            target_code = full_code
            context = f"完整代码:\n```python\n{full_code}\n```"

        system = "你是代码分析专家。分析bug根因，输出修复方案。"
        user = f"""{context}

Bug描述: {bug_desc}
目标函数: {function}

请分析:
1. 根因(为什么这个bug会发生?)
2. 受影响的代码行
3. 修复方案(具体的代码修改)

用中文回答。"""

        result = self._call(model, system, user, temperature=self.temp["head"])
        return {
            **result,
            "complexity": complexity,
            "cached": use_cache,
            "target_code": target_code,
        }

    # ── 模板匹配 (P13) ────────────────────
    def _match_template(self, bug_desc: str, error_type: str = "") -> Optional[str]:
        """匹配修复模板，返回模板名或None"""
        desc = (bug_desc + error_type).lower()
        for tid, tpl in FIX_TEMPLATES.items():
            hits = sum(1 for kw in tpl["detect"] if kw.lower() in desc)
            if hits >= 2:
                return tid
        return None

    # ── 修复蛇 ─────────────────────────────
    def _run_fix(self, target_code: str, function: str, bug_desc: str,
                 head_analysis: str) -> dict:
        """跑修复蛇生成修复代码"""
        system = "你是Python代码修复专家。只输出修复后的完整函数代码，不要解释。"
        user = f"""蛇头分析报告:
{head_analysis}

原始函数代码:
```python
{target_code}
```

Bug: {bug_desc}

请输出修复后的{finger}函数的完整代码(含import)。包裹在```python```中。"""

        return self._call(self.models["fix_snake"], system, user, temperature=self.temp["fix"])

    # ── 快速验证 ───────────────────────────
    def _verify_fix(self, original: str, fixed: str, function: str,
                    trigger_input: str = None) -> bool:
        """快速验证修复是否通过基础测试"""
        if not trigger_input:
            return True  # 无触发测试时不做验证
        try:
            # 在子进程中执行修复代码
            import subprocess, sys as _sys, tempfile
            test_code = f"""
{fixed}

# 快速测试
try:
    result = {function}({trigger_input})
    print("OK:" + str(result)[:100])
except Exception as e:
    print("FAIL:" + str(e)[:100])
"""
            proc = subprocess.run([_sys.executable, "-c", test_code],
                                 capture_output=True, text=True, timeout=10)
            return proc.stdout.startswith("OK:")
        except Exception:
            return False

    # ── 确定性审计 ─────────────────────────
    def _audit(self, original: str, fixed: str, function: str) -> dict:
        """L1确定性审计(零token)"""
        issues = []

        # 危险模式扫描
        import ast as _ast
        try:
            tree = _ast.parse(fixed)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.ExceptHandler) and node.type is None:
                    issues.append("裸except")
                if isinstance(node, _ast.Call) and hasattr(node.func, 'id'):
                    if node.func.id == 'isinstance':
                        # 检查bool-is-int陷阱
                        for arg in node.args[1:]:
                            if isinstance(arg, _ast.Tuple):
                                names = [e.id for e in arg.elts if isinstance(e, _ast.Name)]
                                if 'int' in names and 'bool' not in names:
                                    issues.append("bool-is-int陷阱:isinstance未排除bool")
        except SyntaxError:
            issues.append("语法错误:修复代码无法解析")

        # 范围溢出
        orig_lines = original.split("\n")
        fixed_lines = fixed.split("\n")
        if abs(len(fixed_lines) - len(orig_lines)) > 10:
            issues.append(f"范围溢出:修改行数差{abs(len(fixed_lines)-len(orig_lines))}行")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "token_cost": 0,  # L1/L2零token
        }

    # ── 生成 patch ─────────────────────────
    def _generate_patch(self, file_path: str, original: str, fixed: str) -> str:
        """生成unified diff格式patch"""
        import difflib
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(file_path)}",
            tofile=f"b/{os.path.basename(file_path)}",
        )
        return "".join(diff)

    # ══════════════════════════════════════════════════════════
    # v0.7 黑箱重写 (B阶段修复)
    # ══════════════════════════════════════════════════════════

    def _extract_contract(self, original_code: str, function: str) -> dict:
        """从原代码提取契约: 函数签名 + import + 禁止事项"""
        import ast as _ast
        contract = {
            "function": function,
            "signature": "",
            "imports": [],
            "decorators": [],
            "public_api_warning": False,
        }
        try:
            tree = _ast.parse(original_code)
            for node in _ast.walk(tree):
                # 收集import
                if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                    contract["imports"].append(_ast.unparse(node))
                # 找到目标函数
                if isinstance(node, _ast.FunctionDef) and node.name == function:
                    contract["signature"] = f"def {function}({_ast.unparse(node.args)}):"
                    contract["decorators"] = [_ast.unparse(d) for d in node.decorator_list]
                    # 检查是否为公共API (不以_开头)
                    if not function.startswith('_'):
                        contract["public_api_warning"] = True
        except SyntaxError:
            # 退而求其次: 正则提取
            sig_match = re.search(rf'def {function}\((.*?)\):', original_code)
            if sig_match:
                contract["signature"] = f"def {function}({sig_match.group(1)}):"
        return contract

    def _run_blackbox_rewrite(self, contract: dict, bug_desc: str,
                              head_analysis: str, test_code: str = "") -> dict:
        """
        B阶段: 黑箱重写。模型不看原始实现，只基于契约+bug描述+测试重写。

        输入:
          - contract: 函数签名、import、装饰器
          - bug_desc: 缺陷描述
          - head_analysis: 蛇头根因分析
          - test_code: 已有测试代码(可选)

        约束:
          - 不得修改函数签名
          - 不得修改装饰器
          - 不得新增第三方import
          - 必须通过已有测试
        """
        model = self.models["rewrite_snake"]
        temp = self.temp["rewrite"]

        system = """你是Python代码重写专家。你的任务是在【不看原始实现】的前提下，根据契约重写函数。

约束（不可违反）:
1. 保持给定的函数签名完全不变（参数名、类型注解、返回值）
2. 保持所有装饰器不变
3. 不引入新的第三方库import
4. 只使用标准库和已声明的import
5. 不修改任何不相关的代码

输出要求:
- 输出完整的函数代码(含装饰器和docstring)
- 包裹在```python```中
- 函数名必须与原函数名一致"""

        imports_text = "\n".join(contract["imports"])
        decorators_text = "\n".join(contract["decorators"]) if contract["decorators"] else "(无装饰器)"
        api_warning = ""
        if contract["public_api_warning"]:
            api_warning = "\n⚠️ 警告: 此函数为公共API，签名不可变。修改签名会破坏所有调用方。"

        user = f"""任务: 重写函数 {contract['function']}

契约:
- 函数签名: {contract['signature']}
- 装饰器: {decorators_text}
- 可用import:
```python
{imports_text}
```
{api_warning}

Bug描述: {bug_desc}

蛇头分析: {head_analysis[:800]}

{f"已有测试(必须通过):\n```python\n{test_code[:1500]}\n```" if test_code else ""}

请在不看原始实现的情况下，从零重写此函数。只输出```python```包裹的完整函数代码。"""

        return self._call(model, system, user, temperature=temp, max_tokens=4096)

    # ══════════════════════════════════════════════════════════
    # v0.7 蛇尾结构化自述
    # ══════════════════════════════════════════════════════════

    def _generate_tail(self, fixed_code: str, original_code: str,
                       function: str, test_results: str = "",
                       fix_description: str = "") -> TailReport:
        """
        蛇尾生成结构化自述。

        事实字段(系统填充, LLM不能修改):
        - diff行数、文件变更、测试结果

        推断字段(LLM生成, 必须标注证据):
        - 影响范围、风险评估、边界覆盖

        不确定字段([我无法确认]强制):
        - LLM必须列出的无法确认项
        """
        # 1. 事实字段 — 系统自动填充
        orig_lines = original_code.split("\n")
        fixed_lines = fixed_code.split("\n")
        diff_lines = abs(len(fixed_lines) - len(orig_lines))

        # 提取测试结果
        test_passed = 0; test_total = 0
        if test_results:
            for line in test_results.split("\n"):
                if "PASSED" in line or "OK" in line:
                    try:
                        test_total += 1
                        test_passed += 1
                    except: pass
                elif "FAILED" in line:
                    test_total += 1

        fact = {
            "function": function,
            "diff_lines_changed": diff_lines,
            "test_passed": test_passed,
            "test_total": test_total,
            "has_test_coverage": test_total > 0,
        }

        # 2. 推断字段 — LLM生成
        system = """你是蛇群的蛇尾自述模块。基于修复代码和原始代码，生成结构化自述报告。

规则:
- 推断字段必须标注证据来源(如"基于diff第X行"或"测试test_xxx通过")
- [我无法确认]字段必须列出所有你无法100%确定的风险
- 使用JSON格式输出"""

        user = f"""函数: {function}
修复描述: {fix_description[:300]}

原始代码行数: {len(orig_lines)}
修复后代码行数: {len(fixed_lines)}
Diff行数变化: {diff_lines}

请输出JSON:
{{
  "inference": {{
    "impact_scope": "该修复影响的代码范围(需证据)",
    "risk_assessment": "潜在风险(需证据)",
    "edge_cases_covered": "已处理的边界条件(需证据)",
    "evidence_basis": ["证据来源1", "证据来源2"]
  }},
  "uncertainty": [
    "我无法确认：XXX",
    "我无法确认：YYY"
  ]
}}"""

        try:
            result = self._call(
                self.models.get("light_head", "deepseek-v4-pro"),
                system, user, temperature=0.2, max_tokens=800)
            parsed = json.loads(re.search(r'\{.*\}', result["content"],
                                re.DOTALL).group(0) if re.search(r'\{.*\}',
                                result["content"], re.DOTALL) else "{}")
            inference = parsed.get("inference", {})
            uncertainty = parsed.get("uncertainty", [])
        except Exception:
            inference = {"impact_scope": fix_description[:200]}
            uncertainty = ["无法自动解析自述"]

        # 3. 校验: 推断声明 vs 系统记录
        validation_issues = []
        impact = inference.get("impact_scope", "").lower()
        if "已验证" in impact or "已经测试" in impact:
            if test_total == 0:
                validation_issues.append(
                    "蛇尾声称'已验证'但系统无测试记录 → 高风险标记")

        if inference.get("edge_cases_covered") and test_total == 0:
            validation_issues.append(
                "蛇尾声称覆盖边界条件但无测试验证")

        return TailReport(
            fact=fact,
            inference=inference,
            uncertainty=uncertainty,
            validated=len(validation_issues) == 0,
            validation_issues=validation_issues,
        )

    # ══════════════════════════════════════════════════════════
    # 公共API
    # ══════════════════════════════════════════════════════════

    def fix(self, file_path: str, function: str, bug_description: str,
            error_type: str = "", trigger_test: str = None,
            use_cache: bool = False, enable_judges: bool = False) -> FixResult:
        """
        修复单个bug。

        Args:
            file_path: 源代码文件路径
            function: 目标函数名
            bug_description: bug描述
            error_type: 错误类型(可选)
            trigger_test: 快速验证输入(可选,如 "'abc', 1")
            use_cache: 是否使用文件缓存(P12)

        Returns:
            FixResult
        """
        import os as _os
        bug_id = f"{_os.path.basename(file_path)}:{function}"
        tokens = {}

        try:
            # 1. 模板匹配 (P13)
            template = self._match_template(bug_description, error_type)
            if template:
                self._template_hits += 1
                return FixResult(
                    bug_id=bug_id, success=True,
                    template_hit=template,
                    fix_description=f"模板命中: {FIX_TEMPLATES[template]['name']}",
                    error="模板命中但需LLM生成具体代码——模板提供指导方向",
                )

            # 2. 蛇头分析 (P11+P12)
            head = self._run_head(file_path, function, bug_description,
                                  error_type, use_cache)
            tokens["head"] = head["total_tokens"]

            # 3. 修复蛇
            fix = self._run_fix(head["target_code"], function, bug_description,
                               head["content"])
            tokens["fix"] = fix["total_tokens"]

            # 4. 提取修复代码
            fixed_code = head["target_code"]
            match = re.search(r'```python\n(.*?)```', fix["content"], re.DOTALL)
            if match:
                fixed_code = match.group(1)

            # 5. 快速验证
            if trigger_test and not self._verify_fix(head["target_code"], fixed_code,
                                                     function, trigger_test):
                fixed_code = fix["content"]  # 使用原始输出

            # 6. 确定性审计 (L1)
            audit = self._audit(head["target_code"], fixed_code, function)
            tokens["audit"] = audit["token_cost"]

            # 7. 生成patch
            with open(file_path, encoding="utf-8") as f:
                original_full = f.read()
            patch = self._generate_patch(file_path, original_full,
                                        original_full.replace(head["target_code"], fixed_code))

            # 8. 判断是否需要黑箱重写 (B阶段)
            rewrite_attempted = False
            if not audit["passed"]:
                contract = self._extract_contract(original_full, function)
                rewrite = self._run_blackbox_rewrite(
                    contract, bug_description, head["content"],
                    test_code=trigger_test or "")
                tokens["rewrite"] = rewrite["total_tokens"]

                # 提取重写代码
                rw_match = re.search(r'```python\n(.*?)```', rewrite["content"], re.DOTALL)
                if rw_match:
                    rewritten_code = rw_match.group(1)
                    # 对重写代码做L1审计
                    audit = self._audit(original_full, rewritten_code, function)
                    fixed_code = rewritten_code
                    patch = self._generate_patch(file_path, original_full,
                                                original_full.replace(head["target_code"], rewritten_code))
                    rewrite_attempted = True

            # 9. 蛇尾自述
            tail = self._generate_tail(
                fixed_code, head["target_code"], function,
                test_results="", fix_description=fix["content"][:300])

            # 10. 判定
            success = audit["passed"]

            # 11. v0.7 角色化裁决（可选）
            adjudication = None
            if enable_judges:
                adjudication = self._adjudicate(file_path, patch, bug_id=bug_id)
                if adjudication.final_verdict == "fail":
                    success = False
                    audit["issues"].append(f"裁决未通过: {adjudication.summary}")
                elif adjudication.final_verdict == "conflict":
                    audit["issues"].append(f"裁决冲突: {adjudication.summary}")

            result = FixResult(
                bug_id=bug_id,
                success=success,
                patch=patch,
                root_cause=head["content"][:300],
                fix_description=fix["content"][:300],
                tokens=tokens,
                audit=audit,
                error="" if success else "; ".join(audit["issues"]),
                rewrite_attempted=rewrite_attempted,
                tail_report=tail,
            )
            if adjudication:
                result._adjudication = adjudication
            return result

        except Exception as e:
            return FixResult(bug_id=bug_id, success=False, error=str(e), tokens=tokens)

    def scan(self, file_path: str, bug_candidates: list[dict],
             use_cache: bool = True) -> BatchResult:
        """
        批量修复同一文件的多个bug（含批量法官P10）。

        Args:
            file_path: 源码文件
            bug_candidates: [{"function":"...", "description":"...", "trigger":"..."}, ...]
            use_cache: 首个bug冷缓存，后续温缓存

        Returns:
            BatchResult
        """
        import os as _os
        results = []
        total_tokens = 0

        for i, bug in enumerate(bug_candidates):
            cached = use_cache and i > 0
            result = self.fix(
                file_path=file_path,
                function=bug["function"],
                bug_description=bug["description"],
                error_type=bug.get("error_type", ""),
                trigger_test=bug.get("trigger"),
                use_cache=cached,
            )
            results.append(result)
            total_tokens += sum(result.tokens.values())

        # v0.7 角色化批量裁决 — 每个修复独立审查
        adjudication_results = []
        for r in results:
            if r.patch and not r.template_hit:
                adj = self._adjudicate(file_path, r.patch, bug_id=r.bug_id)
                adjudication_results.append(adj)
                total_tokens += adj.total_tokens

        return BatchResult(
            results=results,
            total_tokens=total_tokens,
            template_hits=sum(1 for r in results if r.template_hit),
            success_count=sum(1 for r in results if r.success),
            fail_count=sum(1 for r in results if not r.success),
        )

    # ══════════════════════════════════════════════════════════
    # v0.7 角色化裁决引擎
    # ══════════════════════════════════════════════════════════

    def _run_single_judge(self, role: str, file_path: str, patch: str,
                          bug_id: str = "", test_results: str = "") -> JudgeVerdict:
        """运行单个角色法官，独立裁决"""
        role_cfg = JUDGE_ROLES[role]
        model_key = f"judge_{role}"
        model = self.models.get(model_key, "deepseek-v4-pro")
        temp = self.temp.get(model_key, 0.3)

        system = role_cfg["system"] + "\n\n" + JUDGE_OUTPUT_FORMAT

        user_parts = [f"审查目标: {bug_id}"]
        if test_results:
            user_parts.append(f"\n测试结果:\n{test_results[:500]}")
        user_parts.append(f"\n修复Patch:\n{patch[:2000]}")
        user = "\n".join(user_parts)

        result = self._call(model, system, user, temperature=temp, max_tokens=1024)
        parsed = self._parse_verdict(result["content"], role)

        return JudgeVerdict(
            role=role,
            verdict=parsed.get("verdict", "uncertain"),
            confidence=parsed.get("confidence", 0.5),
            severity=parsed.get("severity", "P2"),
            evidence_refs=parsed.get("evidence_refs", []),
            reasoning=parsed.get("reasoning", result["content"][:200]),
            counterevidence=parsed.get("counterevidence", ""),
            uncertainty=parsed.get("uncertainty", []),
        )

    def _parse_verdict(self, raw: str, role: str) -> dict:
        """解析法官输出的JSON"""
        try:
            # Try direct JSON parse
            json_match = re.search(r'\{.*"verdict".*\}', raw, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except (json.JSONDecodeError, AttributeError):
            pass
        # Fallback: extract verdict from text
        raw_lower = raw.lower()
        if "fail" in raw_lower and "pass" not in raw_lower.split("fail")[0][-50:]:
            verdict = "fail"
        elif "pass" in raw_lower and "fail" not in raw_lower.split("pass")[0][-50:]:
            verdict = "pass"
        else:
            verdict = "uncertain"
        return {"verdict": verdict, "confidence": 0.5, "severity": "P2",
                "evidence_refs": [], "reasoning": raw[:200],
                "counterevidence": "", "uncertainty": []}

    def _resolve_conflict(self, verdicts: list[JudgeVerdict],
                          file_path: str, patch: str,
                          bug_id: str = "") -> AdjudicationResult:
        """冲突处理：3:0, 2:1, 1:1:1"""
        passes = sum(1 for v in verdicts if v.verdict == "pass")
        fails = sum(1 for v in verdicts if v.verdict == "fail")
        uncertains = sum(1 for v in verdicts if v.verdict == "uncertain")

        total_tokens = 0  # tokens tracked at call site

        # 3:0 fail → 进入修复层
        if fails == 3:
            return AdjudicationResult(
                verdicts=verdicts, final_verdict="fail",
                conflict_type="", minority_preserved=True,
                total_tokens=total_tokens,
                summary="3:0 一致判定失败，进入修复层")

        # 3:0 pass → 通过
        if passes == 3:
            return AdjudicationResult(
                verdicts=verdicts, final_verdict="pass",
                conflict_type="", minority_preserved=True,
                total_tokens=total_tokens,
                summary="3:0 一致判定通过")

        # 3:0 uncertain → 回到蛇头重新分析
        if uncertains == 3:
            return AdjudicationResult(
                verdicts=verdicts, final_verdict="escalated",
                conflict_type="all_uncertain", minority_preserved=True,
                total_tokens=total_tokens,
                summary="3:0 全部uncertain，建议回到蛇头重新分析")

        # 2:1 fail → 进入修复层，记录少数派
        if fails == 2:
            minority = [v for v in verdicts if v.verdict != "fail"][0]
            return AdjudicationResult(
                verdicts=verdicts, final_verdict="fail",
                conflict_type="2:1", minority_preserved=True,
                total_tokens=total_tokens,
                summary=f"2:1 判定失败（少数派{minority.role}: {minority.reasoning[:100]}）")

        # 2:1 pass → 不直接通过，检查少数派
        if passes == 2:
            minority = [v for v in verdicts if v.verdict != "pass"][0]
            if minority.severity in ("P0", "P1"):
                return AdjudicationResult(
                    verdicts=verdicts, final_verdict="conflict",
                    conflict_type="2:1_p0_risk", minority_preserved=True,
                    total_tokens=total_tokens,
                    summary=f"2:1 通过但少数派提出{minority.severity}风险: {minority.reasoning[:100]}")
            return AdjudicationResult(
                verdicts=verdicts, final_verdict="pass",
                conflict_type="2:1", minority_preserved=True,
                total_tokens=total_tokens,
                summary=f"2:1 通过（少数派{minority.role}无P0/P1风险）")

        # 1:1:1 → 触发仲裁器
        passes_detail = [(v.role, v.verdict) for v in verdicts]
        return AdjudicationResult(
            verdicts=verdicts, final_verdict="conflict",
            conflict_type="1:1:1", minority_preserved=True,
            total_tokens=total_tokens,
            summary=f"1:1:1 僵局: {passes_detail}，建议人工审查或调用仲裁器")

    def _adjudicate(self, file_path: str, patch: str,
                    bug_id: str = "", test_results: str = "",
                    enable_arbitrator: bool = False) -> AdjudicationResult:
        """三角色独立裁决 + 冲突处理"""
        verdicts = []
        total_tokens = 0

        # 三个法官独立运行（顺序调用但互不可见）
        for role in ("semantic", "test_evidence", "contract"):
            v = self._run_single_judge(role, file_path, patch, bug_id, test_results)
            verdicts.append(v)
            total_tokens += 1  # approximate — real token tracking needs call result

        result = self._resolve_conflict(verdicts, file_path, patch, bug_id)
        result.total_tokens = total_tokens

        # 1:1:1 且开启仲裁器 → 调Claude做第四次独立判断
        if result.conflict_type == "1:1:1" and enable_arbitrator:
            arb = self._run_arbitrator(file_path, patch, bug_id, verdicts)
            result.verdicts.append(arb)
            result.total_tokens += 1
            result.final_verdict = arb.verdict if arb.verdict != "uncertain" else "escalated"
            result.summary += f"\n仲裁器判定: {arb.verdict} (confidence={arb.confidence})"

        return result

    def _run_arbitrator(self, file_path: str, patch: str,
                        bug_id: str, verdicts: list[JudgeVerdict]) -> JudgeVerdict:
        """仲裁器: 1:1:1时调用高能力模型做第四次独立判断"""
        model = self.models.get("arbitrator", "claude-sonnet-5")
        temp = self.temp.get("arbitrator", 0.3)

        conflicts_text = "\n".join(
            f"法官{v.role}: {v.verdict} (置信度{v.confidence}, {v.severity})\n理由: {v.reasoning[:150]}"
            for v in verdicts
        )

        system = """你是蛇群的仲裁器。三位角色法官对同一修复产生了分歧。
你的任务是做出独立判断——不看其他法官的结论，基于证据重新审查。

输出规则: 用JSON格式（同法官格式）"""

        user = f"""审查目标: {bug_id}

Patch:
{patch[:1500]}

三位法官的分歧:
{conflicts_text}

请独立判断该修复是否通过。{JUDGE_OUTPUT_FORMAT}"""

        result = self._call(model, system, user, temperature=temp, max_tokens=1024)
        parsed = self._parse_verdict(result["content"], "arbitrator")

        return JudgeVerdict(
            role="arbitrator",
            verdict=parsed.get("verdict", "uncertain"),
            confidence=parsed.get("confidence", 0.5),
            severity=parsed.get("severity", "P2"),
            evidence_refs=parsed.get("evidence_refs", []),
            reasoning=parsed.get("reasoning", result["content"][:200]),
            counterevidence=parsed.get("counterevidence", ""),
            uncertainty=parsed.get("uncertainty", []),
        )

    @property
    def stats(self) -> dict:
        """引擎统计"""
        return {
            "template_hits": self._template_hits,
            "cached_files": len(self._file_cache),
        }
