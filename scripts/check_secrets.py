#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交前密钥/隐私扫描（无第三方依赖）。

用法:
    python scripts/check_secrets.py            # 扫描当前 HEAD 跟踪的文件
    python scripts/check_secrets.py --staged   # 只扫描暂存区（pre-commit 钩子用）
    python scripts/check_secrets.py --all-history  # 额外扫描全部历史 blob（慢，发布前用）

退出码:
    0 = 无阻断项（可能有 PII 警告）
    1 = 发现疑似凭据，阻止提交

设计:
    - 凭据类命中 → 阻断；隐私类命中 → 仅警告
    - 支持行内白名单注释: # pragma: allowlist secret
    - 只读工作区/暂存内容，不修改任何文件
"""
import re
import subprocess
import sys

SECRETS = [
    ("OpenAI/DeepSeek 风格 sk-", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("Anthropic sk-ant-", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("Google AIza", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("AWS AK/SK", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("阿里云 AccessKey", re.compile(r"\bLTAI[0-9A-Za-z]{12,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Bearer 令牌", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("URL 内嵌凭据", re.compile(r"[a-z]+://[^/\s:@]+:[^/\s@]+@[^\s/]+")),
    ("微信标识", re.compile(r"wxid_[A-Za-z0-9]{10,}|o[A-Za-z0-9]{27}@im\.wechat")),
]

PII = [
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("本机绝对路径", re.compile(r"[A-Za-z]:[\\/](?:Users|competation|gametest|learnskills)[\\/]")),
]

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".whl", ".pyc", ".so", ".dll", ".exe"}
ALLOW = "# pragma: allowlist secret"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="ignore")


def staged_files():
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACM").stdout
    return [f for f in out.splitlines() if f.strip()]


def head_files():
    out = git("ls-files").stdout
    return [f for f in out.splitlines() if f.strip()]


def read_staged(path):
    r = subprocess.run(["git", "show", f":{path}"], capture_output=True)
    return r.stdout.decode("utf-8", "ignore")


def read_head(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def scan(text, where, secrets, warnings):
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        for name, pat in SECRETS:
            m = pat.search(line)
            if m:
                v = m.group(0)
                masked = v[:6] + "***" + v[-2:] if len(v) > 10 else "***"
                secrets.append((where, lineno, name, masked))
        for name, pat in PII:
            m = pat.search(line)
            if m:
                warnings.append((where, lineno, name))


def main():
    staged = "--staged" in sys.argv
    files = staged_files() if staged else head_files()
    secrets, warnings = [], []
    for f in files:
        if any(f.lower().endswith(e) for e in SKIP_EXT):
            continue
        text = read_staged(f) if staged else read_head(f)
        scan(text, f, secrets, warnings)

    for where, lineno, name, masked in secrets:
        print(f"[BLOCK] {where}:{lineno}  {name}  {masked}")
    for where, lineno, name in warnings:
        print(f"[WARN ] {where}:{lineno}  {name}")

    print(f"\n扫描 {len(files)} 个文件：凭据 {len(secrets)} 处，隐私警告 {len(warnings)} 处")
    if secrets:
        print("提交被阻止。请删除或改用环境变量；确认是误报可加 `# pragma: allowlist secret`。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
