"""
安全工具函数

提供内容安全检测功能，用于检测和阻止提示注入、数据泄露等安全威胁。
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# 威胁模式定义
# ---------------------------------------------------------------------------

# 提示注入 / 角色劫持类
CONTENT_THREAT_PATTERNS = [
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (
        r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+'
        r'(restrictions|limits|rules)',
        "bypass_restrictions",
    ),
    # 数据泄露类
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # 后门持久化
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
]

# 不可见 Unicode 字符（零宽字符等，可用于隐藏注入载荷）
INVISIBLE_UNICODE_CHARS = {
    '\u200b',  # ZERO WIDTH SPACE
    '\u200c',  # ZERO WIDTH NON-JOINER
    '\u200d',  # ZERO WIDTH JOINER
    '\u2060',  # WORD JOINER
    '\ufeff',  # ZERO WIDTH NO-BREAK SPACE (BOM)
    '\u202a',  # LEFT-TO-RIGHT EMBEDDING
    '\u202b',  # RIGHT-TO-LEFT EMBEDDING
    '\u202c',  # POP DIRECTIONAL FORMATTING
    '\u202d',  # LEFT-TO-RIGHT OVERRIDE
    '\u202e',  # RIGHT-TO-LEFT OVERRIDE
}


def scan_content_security(content: str) -> Optional[str]:
    """
    扫描内容中的安全威胁。

    检测以下安全风险：
    - 提示注入（忽略指令、角色劫持等）
    - 数据泄露（通过 curl/wget/cat 窃取敏感信息）
    - SSH 后门
    - 不可见 Unicode 字符隐藏的注入载荷

    Args:
        content: 要扫描的文本内容

    Returns:
        如果检测到威胁，返回描述错误信息的字符串
        如果内容安全，返回 None
    """
    if not content:
        return None

    # 检查不可见 Unicode 字符
    for char in INVISIBLE_UNICODE_CHARS:
        if char in content:
            return (
                f"安全阻断：内容包含不可见 Unicode 字符 U+{ord(char):04X}，"
                f"可能存在注入风险。"
            )

    # 检查威胁模式
    for pattern, threat_id in CONTENT_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return (
                f"安全阻断：内容匹配威胁模式 '{threat_id}'。"
                f"内容将被注入到系统提示中，不得包含注入或泄露载荷。"
            )

    return None
