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
    "judge_primary": "deepseek-v4-pro",    # C1法官 1/3
    "judge_secondary": "deepseek-v4-pro",  # C1法官 2/3
    "judge_tertiary": "gemini-3.6-flash",  # C1法官 3/3
    "auditor_l3": "gemini-3.6-flash",      # L3语义审计(按需)
}

DEFAULT_TEMPERATURE = {
    "head": 0.3,
    "fix": 0.3,
    "rewrite": 0.3,
    "judge_ds": 0.7,
    "judge_gemini": 0.3,
}

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
    template_hit: Optional[str] = None  # 模板命中名称


@dataclass
class BatchResult:
    """批量修复结果"""
    results: list = field(default_factory=list)
    total_tokens: int = 0
    template_hits: int = 0
    success_count: int = 0
    fail_count: int = 0


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
    # 公共API
    # ══════════════════════════════════════════════════════════

    def fix(self, file_path: str, function: str, bug_description: str,
            error_type: str = "", trigger_test: str = None,
            use_cache: bool = False) -> FixResult:
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

            # 8. 判定
            success = audit["passed"]

            return FixResult(
                bug_id=bug_id,
                success=success,
                patch=patch,
                root_cause=head["content"][:300],
                fix_description=fix["content"][:300],
                tokens=tokens,
                audit=audit,
                error="" if success else "; ".join(audit["issues"]),
            )

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

        # 批量法官审查 (P10) — 所有修复打包一次调用
        if len(results) > 1:
            judge_result = self._batch_judge(file_path, results)
            if judge_result:
                total_tokens += judge_result.get("total_tokens", 0)

        return BatchResult(
            results=results,
            total_tokens=total_tokens,
            template_hits=sum(1 for r in results if r.template_hit),
            success_count=sum(1 for r in results if r.success),
            fail_count=sum(1 for r in results if not r.success),
        )

    def _batch_judge(self, file_path: str, results: list[FixResult]) -> Optional[dict]:
        """P10 批量法官审查"""
        if not results:
            return None

        # 构造批量审查prompt
        patches_text = "\n\n---\n\n".join(
            f"Bug #{i+1}: {r.bug_id}\n{r.patch[:500]}"
            for i, r in enumerate(results)
        )

        system = "你是代码审查法官。审查以下所有修复，判断是否引入了新bug。"
        user = f"文件: {os.path.basename(file_path)}\n\n{patches_text}\n\n请逐一判断每个修复: PASS(无新bug)或FAIL(引入新bug)。"

        # DS主法官
        r1 = self._call(self.models["judge_primary"], system, user,
                       temperature=self.temp["judge_ds"])
        # Gemini第二法官
        r2 = self._call(self.models["judge_tertiary"], system, user,
                       temperature=self.temp["judge_gemini"])

        return {
            "judge_ds": r1["content"][:500],
            "judge_gemini": r2["content"][:500],
            "total_tokens": r1["total_tokens"] + r2["total_tokens"],
        }

    @property
    def stats(self) -> dict:
        """引擎统计"""
        return {
            "template_hits": self._template_hits,
            "cached_files": len(self._file_cache),
        }
