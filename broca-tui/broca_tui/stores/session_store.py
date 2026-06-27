"""
Session list state management.

Manages session list data, CRUD operations, and search/filter state.
Each page creates its own SessionStore instance.
"""

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

from broca_tui.api.session import SessionAPI


def _clean_error_message(raw: str) -> str:
    """Extract a user-friendly error message from raw API error text.

    Handles formats like:
    - "Client error 400 for POST /session/sessions: {\"detail\":\"msg\"}"
    - "API error 400: some message"
    - "Connection refused"
    - Raw JSON: {"detail": "msg"}

    Returns:
        Clean, human-readable error message.
    """
    # Try to extract JSON detail from the error message
    # Pattern: ... :  {"detail":"actual message"}  or  {"detail": "actual message"}
    json_match = re.search(r'\{.*"detail"\s*:\s*"([^"]+)".*\}', raw, re.DOTALL)
    if json_match:
        return json_match.group(1)

    # Try to extract msg from "API error N: msg"
    api_msg_match = re.search(r'API error \d+: (.+)', raw)
    if api_msg_match:
        return api_msg_match.group(1).strip()

    # Try to extract from "Client error N for METHOD path: body"
    client_msg_match = re.search(r'Client error \d+ for [A-Z]+ [^:]+:\s*(.+)', raw)
    if client_msg_match:
        body = client_msg_match.group(1).strip()
        # If body is JSON, try to parse it
        if body.startswith("{"):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    # FastAPI style
                    if "detail" in parsed:
                        detail = parsed["detail"]
                        if isinstance(detail, list):
                            return "; ".join(str(e) for e in detail)
                        return str(detail)
                    # Other common fields
                    for key in ("message", "error", "msg"):
                        if key in parsed:
                            return str(parsed[key])
            except (json.JSONDecodeError, ValueError):
                pass
        return body

    # Fallback: return original but trim common prefixes
    return raw


class SessionStore:
    """Store for session list state."""

    def __init__(self, api: Optional[SessionAPI] = None):
        """Initialize session store.

        Args:
            api: SessionAPI instance. Creates a new one if not provided.
        """
        self._api = api or SessionAPI()

        # State
        self.sessions: List[Dict[str, Any]] = []
        self.total: int = 0
        self.skip: int = 0
        self.limit: int = 10
        self.keyword: Optional[str] = None
        self.loading: bool = False
        self.has_more: bool = True
        # Generation counter to ignore stale responses from cancelled workers
        self._gen: int = 0

        # Track last error for inline handling
        self.last_error: Optional[str] = None

        # Callbacks for UI updates
        self._on_change: Optional[Callable[[], None]] = None

    def on_change(self, callback: Callable[[], None]):
        """Register callback for state changes."""
        self._on_change = callback

    def _notify_change(self):
        """Notify UI of state change."""
        if self._on_change:
            self._on_change()

    def _set_error(self, message: str):
        """Store the last error message.

        Screen should check self.last_error after a failed operation.
        """
        self.last_error = message

    async def load_sessions(self, keyword: Optional[str] = None):
        """Load sessions from API.

        Args:
            keyword: Optional search keyword. If provided, resets pagination.
        """
        self._gen += 1
        gen = self._gen

        # Always reset pagination for a fresh load
        if keyword is not None:
            self.keyword = keyword
        elif self.keyword is not None:
            self.keyword = None
        self.skip = 0
        self.sessions = []

        self.loading = True
        self._notify_change()

        try:
            result = await self._api.list_sessions(
                skip=self.skip,
                limit=self.limit,
                keyword=self.keyword,
            )

            # Ignore stale response if a newer request has started
            if gen != self._gen:
                return

            self.sessions = result.get("sessions", [])
            self.total = result.get("total", len(result.get("sessions", [])))
            self.skip += self.limit
            self.has_more = self.skip < self.total
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raw_msg = getattr(e, 'message', str(e))
            self._set_error(f"加载会话列表失败: {_clean_error_message(raw_msg)}")
        finally:
            self.loading = False
            self._notify_change()

    async def load_more(self):
        """Load next page of sessions (preserves current search keyword)."""
        if self.loading or not self.has_more:
            return
        self._gen += 1
        gen = self._gen
        self.loading = True
        self._notify_change()
        try:
            result = await self._api.list_sessions(
                skip=self.skip,
                limit=self.limit,
                keyword=self.keyword,
            )
            if gen != self._gen:
                return
            self.sessions.extend(result.get("sessions", []))
            self.total = result.get("total", len(result.get("sessions", [])))
            self.skip += self.limit
            self.has_more = self.skip < self.total
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raw_msg = getattr(e, 'message', str(e))
            self._set_error(f"加载更多会话失败: {_clean_error_message(raw_msg)}")
        finally:
            self.loading = False
            self._notify_change()

    async def create_session(
        self,
        description: Optional[str] = None,
        workspace: Optional[str] = None,
        category: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new session.

        Args:
            description: Optional session name/description
            workspace: Optional workspace path. If None, backend creates a temp dir.
            category: Session category ('normal' or 'agent-orchestration')
            provider: Optional LLM provider. If None, backend uses default.
            model: Optional LLM model. If None, backend uses default.

        Returns:
            Created session dict, or None on error.
        """
        try:
            result = await self._api.create_session(
                description=description,
                workspace=workspace,
                category=category,
                provider=provider,
                model=model,
            )
            # Refresh session list
            self.skip = 0
            await self.load_sessions()
            return result
        except Exception as e:
            raw_msg = getattr(e, 'message', str(e))
            self._set_error(f"创建会话失败: {_clean_error_message(raw_msg)}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Returns:
            True if successful.
        """
        try:
            await self._api.delete_session(session_id)
            self.sessions = [
                s for s in self.sessions if s.get("session_id") != session_id
            ]
            self.total = max(0, self.total - 1)
            self._notify_change()
            return True
        except Exception as e:
            raw_msg = getattr(e, 'message', str(e))
            self._set_error(f"删除会话失败: {_clean_error_message(raw_msg)}")
            return False

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID from local state."""
        for s in self.sessions:
            if s.get("session_id") == session_id:
                return s
        return None

    async def refresh(self):
        """Refresh session list from API."""
        self.skip = 0
        await self.load_sessions()

    async def close(self):
        """Close the underlying API client."""
        await self._api.close()
