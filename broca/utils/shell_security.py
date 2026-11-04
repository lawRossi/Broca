"""
Shell 命令安全检测模块

提供危险的 Shell 命令检测功能
"""

import re
from typing import List, Tuple
from broca.logging_config import get_logger

logger = get_logger(__name__)

# ===========================================================================
# 危险命令正则模式（通用版）
# ===========================================================================
# 每条：(pattern, description)
DANGEROUS_COMMAND_PATTERNS: List[Tuple[str, str]] = [
    # Python 危险调用（优先匹配，避免 rm -rf 在字符串中被误归因）
    (r"^\s*os\.system\s*\(", "Python os.system() call"),
    (r"^\s*subprocess\.call\s*\(", "Python subprocess.call()"),
    # Git 破坏性操作（优先于通用 rm，给出更具体的原因）
    (r"\bgit\s+rm\s+", "Git file removal"),
    (r"^\s*git\s+reset\s+", "Git reset operation"),
    (r"^\s*git\s+restore\s+", "Git restore operation"),
    # 文件删除 — 使用 \b 匹配 rm 出现在命令中任意位置（行首、&& 之后、管道、子 shell 等）
    (r"\brm\s+-[rRf]+\b", "File deletion with 'rm' command"),
    (r"\brm\s+--(recursive|force)\b", "File deletion with 'rm' command"),
    (r"(?:^\s*|&&\s*|\|\|\s*|[;&|]\s*)rm\s+\S", "File deletion with 'rm' command (no flags)"),
    (r"^\s*del\s+", "File deletion with 'del' command"),
    (r"^\s*rd\s+", "Directory removal with 'rd' command"),
    # 系统操作
    (r"^\s*format\s+", "Disk formatting with 'format' command"),
    (r"^\s*shutdown(?:\s+|$)", "System shutdown"),
    (r"^\s*reboot(?:\s+|$)", "System reboot"),
    (r"^\s*halt(?:\s+|$)", "System halt"),
    (r"^\s*poweroff(?:\s+|$)", "System poweroff"),
    (r"^\s*init\s+[06]", "System shutdown/reboot via init"),
    # 网络安全
    (r"^\s*iptables\s+", "Firewall manipulation with 'iptables'"),
    # 权限
    (r"\bsudo\s+\S", "Privilege escalation with 'sudo'"),
    (r"^\s*chmod\s+[0-7]{3,4}\s+", "Dangerous permission changes with 'chmod'"),
    (r"^\s*chown\s+", "Ownership changes with 'chown'"),
    (r"^\s*su\s+", "User switching with 'su'"),
    # 磁盘
    (r"^\s*dd\s+", "Disk data operation with 'dd'"),
    (r"^\s*mkfs\s+", "Filesystem creation with 'mkfs'"),
    (r"^\s*fdisk\s+", "Partition manipulation with 'fdisk'"),
]

# ===========================================================================
# Tree-sitter（可选，模块级单例）
# ===========================================================================
_tree_sitter_available: bool = False
_parser = None


def init_tree_sitter() -> bool:
    """初始化 tree-sitter bash 解析器（模块级单例）。

    只在需要更精确的 AST 解析时调用；初始化失败自动降级为 regex。
    """
    global _tree_sitter_available, _parser

    if _tree_sitter_available:
        return True

    try:
        from tree_sitter import Language, Parser

        Language.build_library("build/my-languages.so", ["vendor/tree-sitter-bash"])  # type: ignore[attr-defined]
        lang = Language("build/my-languages.so", "bash")  # type: ignore[call-overload]
        _parser = Parser()
        _parser.language = lang  # type: ignore[attr-defined]
        _tree_sitter_available = True
        logger.info("Tree-sitter bash parser initialized successfully")
    except Exception as e:
        logger.warning(
            f"Tree-sitter initialization failed: {e}. Falling back to regex."
        )
        _tree_sitter_available = False

    return _tree_sitter_available


# ===========================================================================
# 公共检测函数
# ===========================================================================


def _strip_comments_for_validation(code: str) -> str:
    """去除 shell 注释（行首 # 和词边界处的行内 #），避免注释内容触发误报。"""
    _WORD_BREAK = " \t\r\n;&|()<>"
    lines = code.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # 整行注释 → 替换为空（保留行结构）
            cleaned.append("")
            continue
        # 去除行内注释：第一个「词首位置」的 # 及其后内容
        in_single = in_double = False
        cut = -1
        for i, ch in enumerate(line):
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double:
                if i == 0 or line[i - 1] in _WORD_BREAK:
                    cut = i
                    break
        if cut != -1:
            line = line[:cut]
        cleaned.append(line)
    return "\n".join(cleaned)


def validate_with_regex(code: str) -> Tuple[bool, str, str]:
    """使用正则表达式检测危险命令。

    Args:
        code: 待检测的 shell 命令

    Returns:
        (is_safe, reason, snippet)
        - is_safe: True 表示安全，False 表示检测到危险
        - reason: 危险原因描述（安全时为空字符串）
        - snippet: 触发了检测的代码片段（安全时为空字符串）
    """
    # 去除注释，避免注释中的危险命令文本触发误报
    if code is not None:
        code = _strip_comments_for_validation(code)
    for pattern, description in DANGEROUS_COMMAND_PATTERNS:
        match = re.search(pattern, code, re.MULTILINE | re.IGNORECASE)
        if match:
            # 提取触发检测的代码行作为 snippet
            line_start = code.rfind("\n", 0, match.start()) + 1
            line_end = code.find("\n", match.end())
            if line_end == -1:
                line_end = len(code)
            snippet = code[line_start:line_end].strip()
            return (False, f"{description} detected", snippet)

    return (True, "", "")


def validate_with_tree_sitter(code: str) -> Tuple[bool, str, str]:
    """使用 tree-sitter AST 解析检测危险命令（更准确）。

    Args:
        code: 待检测的 shell 命令

    Returns:
        (is_safe, reason, snippet)
    """
    if not _tree_sitter_available or _parser is None:
        return validate_with_regex(code)

    try:
        tree = _parser.parse(bytes(code, "utf8"))
        root_node = tree.root_node

        dangerous_commands = {
            "rm",
            "del",
            "rd",
            "format",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "iptables",
            "dd",
            "mkfs",
            "fdisk",
            "sudo",
            "su",
        }

        def check_node(node):
            if node.type == "command":
                command_node = node.child_by_field_name("name")
                if command_node and command_node.type == "word":
                    command_name = code[command_node.start_byte : command_node.end_byte]
                    if command_name in dangerous_commands:
                        snippet = code[node.start_byte : node.end_byte].strip()
                        return (
                            False,
                            f"Command '{command_name}' is flagged as dangerous",
                            snippet,
                        )

                    if command_name == "rm":
                        for child in node.children:
                            if (
                                child.type == "word"
                                and child.start_byte < child.end_byte
                            ):
                                flag = code[child.start_byte : child.end_byte]
                                if flag in ["-rf", "-r", "-f", "-fr"]:
                                    snippet = code[
                                        node.start_byte : node.end_byte
                                    ].strip()
                                    return (
                                        False,
                                        f"'rm' with dangerous flag '{flag}'",
                                        snippet,
                                    )

            if node.type == "string" and (
                "`" in code[node.start_byte : node.end_byte]
                or "$(" in code[node.start_byte : node.end_byte]
            ):
                snippet = code[node.start_byte : node.end_byte].strip()
                return (False, "Shell injection pattern detected", snippet)

            for child in node.children:
                result = check_node(child)
                if isinstance(result, tuple) and not result[0]:
                    return result
            return (True, "", "")

        return check_node(root_node)

    except Exception as e:
        logger.warning(f"Tree-sitter validation failed: {e}. Falling back to regex.")
        return validate_with_regex(code)


def validate_shell_command(
    code: str, use_tree_sitter: bool = False
) -> Tuple[bool, str, str]:
    """检测 shell 命令是否包含危险操作。

    这是本模块的主入口函数，供 bash tool 和 scheduler 等调用。

    Args:
        code: 待检测的 shell 命令
        use_tree_sitter: 是否使用 tree-sitter AST 解析（更准确，但需前置初始化）

    Returns:
        (is_safe, reason, snippet)
        - is_safe: True=安全, False=检测到危险
        - reason: 描述为什么危险
        - snippet: 触发了检测的代码片段
    """
    if not code or not code.strip():
        return (True, "", "")

    if use_tree_sitter and _tree_sitter_available:
        return validate_with_tree_sitter(code)
    else:
        return validate_with_regex(code)
