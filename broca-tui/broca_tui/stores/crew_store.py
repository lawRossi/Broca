"""
Crew execution state management.

Manages crew execution list, submission, and real-time progress updates.
Each crew page creates its own CrewStore instance.
"""

from typing import Any, Callable, Dict, List, Optional

from broca_tui.api.crew import CrewAPI


class CrewStore:
    """Store for crew execution state."""

    def __init__(self, api: Optional[CrewAPI] = None):
        """Initialize crew store.

        Args:
            api: CrewAPI instance. Creates a new one if not provided.
        """
        self._api = api or CrewAPI()

        # State
        self.executions: List[Dict[str, Any]] = []
        self.total: int = 0
        self.loading: bool = False
        self.submitting: bool = False

        # Filters
        self.session_id_filter: Optional[str] = None
        self.status_filter: Optional[str] = None

        # Config files for submission
        self.config_files: List[Dict[str, Any]] = []
        self.config_files_loading: bool = False

        # Selected execution detail
        self.selected_execution: Optional[Dict[str, Any]] = None
        self.detail_loading: bool = False

        # Callbacks
        self._on_change: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None

    def on_change(self, callback: Callable[[], None]):
        """Register callback for state changes."""
        self._on_change = callback

    def on_error(self, callback: Callable[[str], None]):
        """Register callback for errors."""
        self._on_error = callback

    def _notify_change(self):
        """Notify UI of state change."""
        if self._on_change:
            self._on_change()

    def _notify_error(self, message: str):
        """Notify UI of error."""
        if self._on_error:
            self._on_error(message)

    async def load_executions(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ):
        """Load crew executions.

        Args:
            session_id: Optional session ID filter
            status: Optional status filter
        """
        if self.loading:
            return

        self.loading = True
        if session_id is not None:
            self.session_id_filter = session_id
        if status is not None:
            self.status_filter = status
        self._notify_change()

        try:
            result = await self._api.list_executions(
                session_id=self.session_id_filter,
                status=self.status_filter,
            )
            self.executions = result.get("executions", [])
            self.total = result.get("total", 0)
        except Exception as e:
            self._notify_error(f"加载编排执行列表失败: {e}")
        finally:
            self.loading = False
            self._notify_change()

    async def load_execution_detail(self, execution_id: str):
        """Load detail of a specific execution.

        Args:
            execution_id: Execution ID
        """
        self.detail_loading = True
        self._notify_change()

        try:
            result = await self._api.get_execution_detail(execution_id)
            self.selected_execution = result
        except Exception as e:
            self._notify_error(f"加载执行详情失败: {e}")
        finally:
            self.detail_loading = False
            self._notify_change()

    async def load_config_files(self, workspace: str):
        """Load crew config files from workspace.

        Args:
            workspace: Workspace path
        """
        self.config_files_loading = True
        self._notify_change()

        try:
            result = await self._api.list_config_files(workspace)
            self.config_files = result.get("configs", [])
        except Exception as e:
            self._notify_error(f"加载配置文件列表失败: {e}")
        finally:
            self.config_files_loading = False
            self._notify_change()

    async def submit_execution(
        self,
        session_id: str,
        yaml_path: Optional[str] = None,
        yaml_content: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Submit a new crew execution.

        Args:
            session_id: Session ID
            yaml_path: Path to YAML config file
            yaml_content: Inline YAML content

        Returns:
            Created execution dict, or None on error.
        """
        if self.submitting:
            return None

        # Check for running executions
        for execution in self.executions:
            if execution.get("status") == "running" and execution.get("session_id") == session_id:
                self._notify_error("该会话已有编排正在执行，请等待完成后再试")
                return None

        self.submitting = True
        self._notify_change()

        try:
            result = await self._api.submit_execution(
                session_id=session_id,
                yaml_path=yaml_path,
                yaml_content=yaml_content,
            )
            # Refresh list
            await self.load_executions(session_id=self.session_id_filter)
            return result
        except Exception as e:
            self._notify_error(f"提交编排执行失败: {e}")
            return None
        finally:
            self.submitting = False
            self._notify_change()

    async def abort_execution(self, execution_id: str) -> bool:
        """Abort a running execution.

        Args:
            execution_id: Execution ID

        Returns:
            True if successful.
        """
        try:
            await self._api.abort_execution(execution_id)
            # Update local state
            for execution in self.executions:
                if execution.get("execution_id") == execution_id:
                    execution["status"] = "aborted"
            self._notify_change()
            return True
        except Exception as e:
            self._notify_error(f"中止执行失败: {e}")
            return False

    async def delete_execution(self, execution_id: str) -> bool:
        """Delete an execution record.

        Args:
            execution_id: Execution ID

        Returns:
            True if successful.
        """
        try:
            await self._api.delete_execution(execution_id)
            self.executions = [
                e for e in self.executions if e.get("execution_id") != execution_id
            ]
            self.total = max(0, self.total - 1)
            self._notify_change()
            return True
        except Exception as e:
            self._notify_error(f"删除执行记录失败: {e}")
            return False

    def update_execution_status(self, execution_id: str, status: str):
        """Update execution status from Socket event."""
        for execution in self.executions:
            if execution.get("execution_id") == execution_id:
                execution["status"] = status
                self._notify_change()
                return

    async def refresh(self):
        """Refresh execution list."""
        await self.load_executions(
            session_id=self.session_id_filter,
            status=self.status_filter,
        )

    async def close(self):
        """Close the underlying API client."""
        await self._api.close()
