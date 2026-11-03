"""SkillManager ABC — interface for skill discovery and loading.

Manages discovery, loading, and listing of skills (prompt templates
that extend agent capabilities).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class SkillManager(ABC):
    """Abstract base class for skill management.

    Implementations discover skills from filesystem locations and
    provide loading/listing capabilities.
    """

    @abstractmethod
    def get_skills(
        self, workspace: str, skill_names: Optional[str] = None
    ) -> Dict[str, Dict]:
        """Get skills by name (or all if skill_names is None).

        Returns a dict mapping skill name → skill metadata.
        """
        ...

    @abstractmethod
    def load_skill(self, name: str) -> Optional[str]:
        """Load a skill's content by name. Returns the skill text or None."""
        ...

    @abstractmethod
    def list_skills(self, workspace: str) -> List[str]:
        """List all available skill names for the given workspace."""
        ...
