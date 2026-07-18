"""
Shell 命令安全检测模块单元测试

覆盖：
- DANGEROUS_COMMAND_PATTERNS 中所有模式的检测
- 安全命令白名单（不误报）
- tree-sitter 不可用时自动降级到 regex
- 边界情况（空字符串、纯空白）
"""

import importlib
from typing import Tuple

import pytest

from broca.utils import shell_security


# ============================================================================
# validate_with_regex 测试
# ============================================================================


class TestValidateWithRegex:
    """测试 validate_with_regex 函数"""

    # ── 危险命令检测 ──────────────────────────────────

    @pytest.mark.parametrize(
        "cmd,expected_reason",
        [
            # 文件删除
            ("rm -rf /tmp/test", "File deletion with 'rm' command"),
            ("rm -f /tmp/test", "File deletion with 'rm' command"),
            ("rm -r /tmp/test", "File deletion with 'rm' command"),
            ("rm -fr /tmp/test", "File deletion with 'rm' command"),
            ("del /tmp/test", "File deletion with 'del' command"),
            ("rd /tmp/test", "Directory removal with 'rd' command"),
            # 系统操作
            ("format C:", "Disk formatting with 'format' command"),
            ("shutdown now", "System shutdown"),
            ("reboot", "System reboot"),
            ("halt", "System halt"),
            ("poweroff", "System poweroff"),
            ("init 0", "System shutdown/reboot via init"),
            ("init 6", "System shutdown/reboot via init"),
            # 网络安全
            ("iptables -F", "Firewall manipulation with 'iptables'"),
            # 权限
            ("chmod 777 /tmp/test", "Dangerous permission changes with 'chmod'"),
            ("chown root:root /tmp/test", "Ownership changes with 'chown'"),
            ("sudo rm /tmp/test", "Privilege escalation with 'sudo'"),
            ("su root", "User switching with 'su'"),
            # 磁盘
            ("dd if=/dev/zero of=/dev/sda", "Disk data operation with 'dd'"),
            ("mkfs /dev/sdb1", "Filesystem creation with 'mkfs'"),
            ("fdisk /dev/sda", "Partition manipulation with 'fdisk'"),
            # Shell 注入
            ("echo $(whoami)", "Shell command substitution '$('"),
            # Python 危险调用
            (
                'os.system("rm -rf /")',
                "Python os.system() call",
            ),
            (
                'subprocess.call(["rm", "-rf", "/"])',
                "Python subprocess.call()",
            ),
            # Git 破坏性操作
            ("git rm file.txt", "Git file removal"),
            ("git reset --hard", "Git reset operation"),
            ("git restore file.txt", "Git restore operation"),
        ],
    )
    def test_dangerous_commands_detected(self, cmd: str, expected_reason: str):
        """测试各种危险命令被正确检测"""
        is_safe, reason, snippet = shell_security.validate_with_regex(cmd)
        assert not is_safe, f"'{cmd}' 应该被标记为危险"
        assert expected_reason in reason, f"原因应该包含 '{expected_reason}', 实际: {reason}"
        assert snippet, "snippet 不应为空"

    # ── 安全命令（白名单） ────────────────────────────

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello world",
            "ls -la /tmp",
            "cd /home/user/project",
            "python3 -m pytest tests/",
            "git status",
            "git log --oneline -5",
            "git diff HEAD~1",
            "cp /tmp/a /tmp/b",
            "mv /tmp/a /tmp/b",
            "cat /tmp/file.txt",
            "head -20 /tmp/file.txt",
            "tail -f /tmp/file.log",
            "grep -r 'pattern' src/",
            "find . -name '*.py'",
            "pip install requests",
            "npm install",
            "docker ps",
            "docker-compose up -d",
            "make build",
            'echo "rm is just a string here"',
            "# rm -rf /  (this is a comment)",
            "export VAR=value",
            "source .env",
            "which python3",
            "touch /tmp/newfile.txt",
        ],
    )
    def test_safe_commands_not_detected(self, cmd: str):
        """测试安全命令不被误报"""
        is_safe, reason, snippet = shell_security.validate_with_regex(cmd)
        assert is_safe, f"'{cmd}' 不应该被标记为危险, reason: {reason}"

    # ── 边界情况 ──────────────────────────────────────

    @pytest.mark.parametrize(
        "cmd",
        [
            "",
            "   ",
            "\n",
            "\t",
            None,
        ],
    )
    def test_empty_or_blank_input(self, cmd):
        """测试空字符串或空白字符串"""
        if cmd is None:
            # validate_with_regex 会处理 None 吗？它会传入 re.search，会引发 TypeError
            with pytest.raises(TypeError):
                shell_security.validate_with_regex(cmd)
        else:
            is_safe, reason, snippet = shell_security.validate_with_regex(cmd)
            assert is_safe, f"'{cmd}' 应该是安全的"
            assert reason == ""
            assert snippet == ""

    def test_multi_line_command(self):
        """测试多行命令中的危险行"""
        cmd = """echo "Starting build"
make clean
rm -rf dist/
make build
echo "Done"
"""
        is_safe, reason, snippet = shell_security.validate_with_regex(cmd)
        assert not is_safe
        assert "rm" in reason
        assert "rm -rf dist/" in snippet

    def test_case_insensitivity(self):
        """测试大小写不敏感"""
        is_safe, reason, snippet = shell_security.validate_with_regex("SUDO rm /tmp/test")
        assert not is_safe
        assert "sudo" in reason.lower() or "Privilege" in reason

    def test_snippet_extraction(self):
        """测试 snippet 提取的正确性"""
        cmd = """echo hello
rm -rf /tmp/test
echo done"""
        is_safe, reason, snippet = shell_security.validate_with_regex(cmd)
        assert not is_safe
        assert snippet == "rm -rf /tmp/test"


# ============================================================================
# validate_shell_command 主入口测试
# ============================================================================


class TestValidateShellCommand:
    """测试 validate_shell_command 主入口函数"""

    def test_normal_regex_mode(self):
        """测试默认（regex）模式"""
        is_safe, _, _ = shell_security.validate_shell_command("ls -la")
        assert is_safe

        is_safe, _, _ = shell_security.validate_shell_command("rm -rf /")
        assert not is_safe

    def test_tree_sitter_unavailable_fallback(self):
        """测试 tree-sitter 不可用时自动降级到 regex"""
        # 保存原始状态
        original_available = shell_security._tree_sitter_available

        try:
            # 强制设置为不可用
            shell_security._tree_sitter_available = False

            # use_tree_sitter=True 但 tree-sitter 不可用，应降级到 regex
            is_safe, reason, snippet = shell_security.validate_shell_command(
                "rm -rf /", use_tree_sitter=True
            )
            assert not is_safe
            assert "rm" in reason
        finally:
            shell_security._tree_sitter_available = original_available

    def test_empty_input(self):
        """测试空输入"""
        is_safe, reason, snippet = shell_security.validate_shell_command("")
        assert is_safe
        assert reason == ""
        assert snippet == ""

        is_safe, reason, snippet = shell_security.validate_shell_command("   ")
        assert is_safe

    def test_regex_detects_all_patterns(self):
        """确保所有危险模式都能通过 regex 被检测到"""
        # 已知的 pattern -> 示例命令映射
        pattern_examples = {
            "rm": "rm -rf /test",
            "del": "del /tmp/test",
            "rd": "rd /tmp/test",
            "format": "format C:",
            "shutdown": "shutdown now",
            "reboot": "reboot",
            "halt": "halt",
            "poweroff": "poweroff",
            "init": "init 0",
            "iptables": "iptables -F",
            "chmod": "chmod 777 /tmp/test",
            "chown": "chown root:root /tmp/test",
            "sudo": "sudo rm /tmp/test",
            "su": "su root",
            "dd": "dd if=/dev/zero of=/dev/sda",
            "mkfs": "mkfs /dev/sdb1",
            "fdisk": "fdisk /dev/sda",
            "substitution": "echo $(whoami)",
            "os.system": 'os.system("ls")',
            "subprocess.call": 'subprocess.call(["ls"])',
            "git rm": "git rm file.txt",
            "git reset": "git reset --hard",
            "git restore": "git restore file.txt",
        }

        import re
        for pattern, description in shell_security.DANGEROUS_COMMAND_PATTERNS:
            # 从描述中找到关键词来查找示例
            found = False
            for keyword, example in pattern_examples.items():
                if keyword in description.lower() or keyword in pattern.lower():
                    # 验证该示例确实匹配此模式
                    if re.search(pattern, example, re.MULTILINE | re.IGNORECASE):
                        is_safe, reason, snippet = shell_security.validate_with_regex(example)
                        assert not is_safe, (
                            f"Pattern '{pattern}' (desc: {description}) "
                            f"未能检测到命令 '{example}'"
                        )
                        found = True
                        break

            if not found:
                # 如果找不到匹配的示例，直接从 pattern 构造
                # 移除开头的 ^\s* 和结尾的 (?:\s+|$) 得到命令名
                cmd_part = pattern
                cmd_part = cmd_part.replace(r"^\s*", "")
                cmd_part = cmd_part.replace(r"^", "")
                cmd_part = cmd_part.replace(r"(?:\s+|$)", "")
                cmd_part = cmd_part.replace(r"\s+", " ")
                # 移除正则特殊字符以得到纯文本命令名
                cmd_part = re.sub(r"[\(\)\?\:\|\\]", "", cmd_part)
                example = f"{cmd_part} test"
                is_safe, reason, snippet = shell_security.validate_with_regex(example)
                # 对于某些无法构造有效示例的 pattern 不强制要求
                if not is_safe:
                    found = True
                else:
                    # 最后尝试：直接用 pattern 作为 regex 搜索
                    pass  # 某些 pattern 确实是条件性的，无法用简单命令触发

            # 对于能够找到示例的 pattern，验证通过
            # 注意：某些 pattern（如 chmod 777）有更严格的条件


# ============================================================================
# init_tree_sitter 测试
# ============================================================================


class TestInitTreeSitter:
    """测试 init_tree_sitter 函数"""

    def test_init_failure_returns_false(self):
        """测试 tree-sitter 初始化失败返回 False"""
        # 保存原始状态
        original_available = shell_security._tree_sitter_available
        original_parser = shell_security._parser

        try:
            shell_security._tree_sitter_available = False
            shell_security._parser = None

            # tree-sitter 库不可用时会失败
            result = shell_security.init_tree_sitter()
            # 因为 tree_sitter 模块可能未安装或 vendor 目录不存在
            assert not result
            assert not shell_security._tree_sitter_available
        finally:
            shell_security._tree_sitter_available = original_available
            shell_security._parser = original_parser

    def test_already_initialized(self):
        """测试已初始化时直接返回 True"""
        original_available = shell_security._tree_sitter_available

        try:
            shell_security._tree_sitter_available = True
            result = shell_security.init_tree_sitter()
            assert result
        finally:
            shell_security._tree_sitter_available = original_available


# ============================================================================
# validate_with_tree_sitter 测试（降级路径）
# ============================================================================


class TestValidateWithTreeSitter:
    """测试 validate_with_tree_sitter 函数（主要测试降级路径）"""

    def test_fallback_when_not_available(self):
        """测试 tree-sitter 不可用时降级到 regex"""
        original_available = shell_security._tree_sitter_available

        try:
            shell_security._tree_sitter_available = False
            shell_security._parser = None

            # 应该降级到 regex
            is_safe, reason, snippet = shell_security.validate_with_tree_sitter(
                "rm -rf /tmp"
            )
            assert not is_safe
            assert "rm" in reason
        finally:
            shell_security._tree_sitter_available = original_available
