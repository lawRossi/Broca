"""
SkillStore — Skill 元数据管理（来源标记、状态、使用统计、归档/恢复）

纯代码，不依赖 LLM。所有 Skill 创建/维护操作的底层数据层。
"""

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from broca.logging_config import get_logger
from broca.errors import ValidationError

logger = get_logger(__name__)

# ─── 默认路径 ─────────────────────────────────────────

DEFAULT_SKILLS_DIR = Path.home() / ".broca" / "skills"
STORE_FILENAME = ".skill_store.json"
ARCHIVE_DIR_NAME = ".archive"


# ─── SkillStore ───────────────────────────────────────


class SkillStore:
    """Skill 元数据存储。

    管理单个 JSON 文件（.skill_store.json），包含：
    - 来源标记（builtin | agent）
    - 生命周期状态（active | archived）
    - 使用统计（use_count, view_count）
    - 归档/恢复操作

    使用 fcntl.flock 保证并发安全。
    """

    def __init__(self, skills_dir: str | Path | None = None):
        self.skills_dir = Path(skills_dir or DEFAULT_SKILLS_DIR).resolve()
        self.archive_dir = self.skills_dir / ARCHIVE_DIR_NAME
        self.store_path = self.skills_dir / STORE_FILENAME

        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ─── Store 读写（含文件锁） ────────────────────────

    @contextmanager
    def _file_lock(self):
        """fcntl.flock 排他锁上下文管理器。"""
        lock_path = self.store_path.with_suffix(".json.lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            # 清理锁文件
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _ensure_store(self):
        """确保 store 文件存在。"""
        if not self.store_path.exists():
            self.store_path.write_text("{}", encoding="utf-8")

    def read(self) -> dict[str, dict]:
        """读取全部 store 数据。"""
        self._ensure_store()
        with self._file_lock():
            try:
                raw = self.store_path.read_text(encoding="utf-8")
                return json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to read skill store: {e}")
                return {}

    def save(self, data: dict[str, dict]):
        """写入全部 store 数据（原子写：先写临时文件再 rename）。"""
        self._ensure_store()
        with self._file_lock():
            tmp = self.store_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self.store_path)

    # ─── 单条操作 ─────────────────────────────────────

    def get(self, name: str) -> Optional[dict]:
        """获取指定 Skill 的元数据，不存在返回 None。"""
        data = self.read()
        return data.get(name)

    def update(self, name: str, **fields):
        """更新指定 Skill 的字段。"""
        data = self.read()
        if name not in data:
            raise ValidationError(f"Skill '{name}' not found in store.")
        data[name].update(fields)
        self.save(data)

    def ensure(self, name: str, created_by: str = "agent"):
        """确保 Skill 记录存在（首次创建时写入，不覆盖已有字段）。"""
        data = self.read()
        if name not in data:
            now = _now_iso()
            data[name] = {
                "created_by": created_by,
                "state": "active",
                "pinned": False,
                "use_count": 0,
                "view_count": 0,
                "created_at": now,
                "updated_at": now,
                "last_used_at": None,
                "last_viewed_at": None,
            }
            self.save(data)

    # ─── 便捷统计 ─────────────────────────────────────

    def record_use(self, name: str):
        """记录一次使用。"""
        self.update(
            name,
            use_count=self.get(name)["use_count"] + 1,
            last_used_at=_now_iso(),
            updated_at=_now_iso(),
        )

    def record_view(self, name: str):
        """记录一次查看。"""
        self.update(
            name,
            view_count=self.get(name)["view_count"] + 1,
            last_viewed_at=_now_iso(),
            updated_at=_now_iso(),
        )

    # ─── 归档/恢复 ────────────────────────────────────

    def _check_agent_created(self, name: str) -> tuple[bool, str]:
        """检查是否为 agent-created Skill。"""
        meta = self.get(name)
        if meta is None:
            return False, f"Skill '{name}' not found in store."
        if meta.get("created_by") != "agent":
            return (
                False,
                f"Skill '{name}' is {meta.get('created_by')}, only agent-created skills can be modified.",
            )
        return True, ""

    def archive_skill(self, name: str) -> tuple[bool, str]:
        """归档 Skill：移入 .archive/ 目录 + 状态更新。"""
        ok, msg = self._check_agent_created(name)
        if not ok:
            return False, msg

        src = self.skills_dir / name
        dst = self.archive_dir / name

        if not src.exists():
            return False, f"Skill directory not found: {src}"

        if dst.exists():
            return False, f"Archive target already exists: {dst}"

        shutil.move(str(src), str(dst))
        self.update(name, state="archived", updated_at=_now_iso())
        logger.info(f"Archived skill '{name}' → {dst}")
        return True, f"Archived skill '{name}'"

    def restore_skill(self, name: str) -> tuple[bool, str]:
        """恢复 Skill：从 .archive/ 恢复到 skills/ + 状态更新。"""
        src = self.archive_dir / name
        dst = self.skills_dir / name

        if not src.exists():
            return False, f"Archived skill not found: {src}"

        if dst.exists():
            return False, f"Target directory already exists: {dst}"

        shutil.copytree(str(src), str(dst), dirs_exist_ok=False)
        self.update(name, state="active", updated_at=_now_iso())
        logger.info(f"Restored skill '{name}' → {dst}")
        return True, f"Restored skill '{name}'"

    # ─── 查询 ─────────────────────────────────────────

    def all(self) -> dict[str, dict]:
        """返回全部 Skill 元数据。"""
        return self.read()

    def agent_created(self) -> dict[str, dict]:
        """返回所有 agent-created 的 Skill。"""
        return {k: v for k, v in self.read().items() if v.get("created_by") == "agent"}

    def get_by_state(self, state: str) -> dict[str, dict]:
        """按状态过滤。"""
        return {k: v for k, v in self.read().items() if v.get("state") == state}

    def is_registered(self, name: str) -> bool:
        """检查 Skill 是否已在 store 中注册。"""
        return name in self.read()

    def list_all_skills(self) -> list[dict]:
        """列出所有 Skill 的摘要信息（合并目录扫描 + store 数据）。"""
        # 扫描 skills 目录
        found: dict[str, dict] = {}

        # active: skills/ 下所有含 SKILL.md 的目录
        self._scan_dir(self.skills_dir, "active", found)
        # archived: .archive/ 下所有含 SKILL.md 的目录
        self._scan_dir(self.archive_dir, "archived", found)

        # 合并 store 元数据
        store = self.read()
        for name, meta in found.items():
            if name in store:
                meta.update(store[name])

        return list(found.values())

    def _scan_dir(self, base_dir: Path, default_state: str, result: dict):
        """扫描目录下的 Skill 目录。"""
        if not base_dir.exists():
            return
        for entry in base_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.exists():
                continue
            # 简单解析 frontmatter 获取 name
            name = self._parse_skill_name(skill_file) or entry.name
            result[name] = {
                "name": name,
                "path": str(entry),
                "state": default_state,
            }

    def _parse_skill_name(self, skill_file: Path) -> Optional[str]:
        """从 SKILL.md 的 YAML frontmatter 中提取 name。"""
        try:
            content = skill_file.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            import yaml

            header = yaml.safe_load(parts[1].strip())
            if isinstance(header, dict):
                return header.get("name")
        except Exception:
            pass
        return None


# ─── 辅助函数 ────────────────────────────────────────


def _now_iso() -> str:
    """返回 ISO 格式的当前时间字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_skill_name(name: str) -> str:
    """清洗 Skill 名称：只保留 a-z0-9-。"""
    import re

    slug = re.sub(r"[^a-z0-9-]", "-", name.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug
