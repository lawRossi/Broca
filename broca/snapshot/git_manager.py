import hashlib
from pathlib import Path
from git import Repo
from git.exc import InvalidGitRepositoryError

SNAPSHOT_DIR = Path.home() / ".local" / "share" / "broca" / "snapshot"


def get_workspace_hash(workspace: str) -> str:
    return hashlib.sha256(workspace.encode()).hexdigest()[:12]


def get_git_dir(workspace: str) -> Path:
    workspace_hash = get_workspace_hash(workspace)
    return SNAPSHOT_DIR / workspace_hash


class SnapshotGitManager:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.git_dir = get_git_dir(workspace)
        self.repo: Repo | None = None

    def ensure_initialized(self) -> bool:
        if self.repo is not None:
            return True
        self.git_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.repo = Repo(self.git_dir)
        except InvalidGitRepositoryError:
            self.repo = Repo.init(self.git_dir)
            self._config_git()
        return True

    def _config_git(self):
        with self.repo.config_writer() as config:
            config.set_value("core", "autocrlf", "false")
            config.set_value("core", "longpaths", "true")
            config.set_value("core", "symlinks", "true")
            config.set_value("core", "fsmonitor", "false")

    def get_tree_hash(self) -> str | None:
        if not self.ensure_initialized():
            return None
        git = self.repo.git
        git.update_environment(GIT_WORK_TREE=self.workspace)
        try:
            return git.write_tree().strip()
        except Exception:
            return None