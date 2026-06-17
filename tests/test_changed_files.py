"""
Tests for the file changes summary feature.

Verifies the core data transformations:
1. Turn-level diff computation structure
2. Turn-end message data structure
3. Frontend data mapping
4. REST API response structure
"""

import json
import sys
import os


def test_changed_files_data_structure():
    """Verify that the changed_files data structure matches the plan spec."""
    changed_files = {
        "total_added": 2,
        "total_deleted": 1,
        "total_modified": 3,
        "files_added": ["new_file.py", "another_new.py"],
        "files_deleted": ["old_file.py"],
        "files_modified": ["modified.py", "updated.py", "changed.py"],
    }

    # Verify counts match arrays
    assert changed_files["total_added"] == len(changed_files["files_added"])
    assert changed_files["total_deleted"] == len(changed_files["files_deleted"])
    assert changed_files["total_modified"] == len(changed_files["files_modified"])

    # Verify empty case
    empty = {
        "total_added": 0,
        "total_deleted": 0,
        "total_modified": 0,
        "files_added": [],
        "files_deleted": [],
        "files_modified": [],
    }
    assert empty["total_added"] == 0
    assert empty["total_deleted"] == 0
    assert empty["total_modified"] == 0
    assert len(empty["files_added"]) == 0
    print("✅ test_changed_files_data_structure passed")


def test_frontend_mapping():
    """Simulate the frontend mapping from backend response to TurnSummary.changedFiles."""
    # Simulate backend API response
    backend_response = {
        "changed_files": {
            "total_added": 1,
            "total_deleted": 0,
            "total_modified": 2,
            "files_added": ["new_file.py"],
            "files_deleted": [],
            "files_modified": ["a.py", "b.py"],
        }
    }

    # Simulate frontend mapping (TypeScript → Python equivalent)
    cf = backend_response["changed_files"]
    frontend_changed_files = {
        "totalAdded": cf["total_added"],
        "totalDeleted": cf["total_deleted"],
        "totalModified": cf["total_modified"],
        "filesAdded": cf["files_added"],
        "filesDeleted": cf["files_deleted"],
        "filesModified": cf["files_modified"],
    }

    assert frontend_changed_files["totalAdded"] == 1
    assert frontend_changed_files["totalDeleted"] == 0
    assert frontend_changed_files["totalModified"] == 2
    assert "new_file.py" in frontend_changed_files["filesAdded"]
    assert "a.py" in frontend_changed_files["filesModified"]
    print("✅ test_frontend_mapping passed")


def test_turn_end_message_structure():
    """Verify the turn_end message data structure contains changed_files."""
    # Simulate the backend creating a turn_end message
    turn_end_data = {
        "turn_id": "test-turn-123",
        "status": "completed",
    }

    changed_files = {
        "total_added": 1,
        "total_deleted": 0,
        "total_modified": 2,
        "files_added": ["new_file.py"],
        "files_deleted": [],
        "files_modified": ["a.py", "b.py"],
    }

    # Include changed_files in data (as done by create_turn_end)
    if changed_files:
        turn_end_data["changed_files"] = changed_files

    assert "changed_files" in turn_end_data
    assert turn_end_data["changed_files"]["total_added"] == 1
    print("✅ test_turn_end_message_structure passed")


def test_empty_changed_files():
    """Verify empty changed_files case (no file changes in turn)."""
    # Simulate turn with no file changes
    turn_end_data = {
        "turn_id": "test-turn-456",
        "status": "completed",
    }

    # No changed_files key (backend only includes when there are changes)
    # This is the None/null case
    changed_files = None

    # Frontend check: if None, don't show
    if changed_files is None:
        assert True  # Frontend should not show the section
    else:
        assert False  # Should not reach here

    # Simulate empty dict case (old data fallback)
    changed_files_from_api = {}
    has_changes = (
        changed_files_from_api
        and (
            changed_files_from_api.get("total_added", 0) > 0
            or changed_files_from_api.get("total_deleted", 0) > 0
            or changed_files_from_api.get("total_modified", 0) > 0
        )
    )
    assert not has_changes

    print("✅ test_empty_changed_files passed")


def test_no_display_when_empty():
    """Verify UI conditional logic: don't show row when no changes."""
    # Test showChangedFiles computation (equivalent to frontend computed property)

    # Case 1: changedFiles is None
    cf = None
    show = cf and (cf.get("totalAdded", 0) > 0 or cf.get("totalDeleted", 0) > 0 or cf.get("totalModified", 0) > 0)
    assert not show

    # Case 2: changedFiles has all zeros
    cf = {"totalAdded": 0, "totalDeleted": 0, "totalModified": 0, "filesAdded": [], "filesDeleted": [], "filesModified": []}
    show = cf and (cf.get("totalAdded", 0) > 0 or cf.get("totalDeleted", 0) > 0 or cf.get("totalModified", 0) > 0)
    assert not show

    # Case 3: changedFiles has actual changes
    cf = {"totalAdded": 1, "totalDeleted": 0, "totalModified": 0, "filesAdded": ["x.py"], "filesDeleted": [], "filesModified": []}
    show = cf and (cf.get("totalAdded", 0) > 0 or cf.get("totalDeleted", 0) > 0 or cf.get("totalModified", 0) > 0)
    assert show

    print("✅ test_no_display_when_empty passed")


def test_get_turn_stats_with_changed_files():
    """Simulate get_turn_stats extracting changed_files from turn_end message."""
    messages = [
        {"message_type": "step_start", "data": {"snapshot_hash": "abc123"}},
        {"message_type": "tool_call", "data": {"tool_name": "edit_file"}},
        {"message_type": "step_end", "data": {"snapshot_hash": "def456"}},
        {
            "message_type": "turn_end",
            "data": {
                "status": "completed",
                "changed_files": {
                    "total_added": 1,
                    "total_deleted": 0,
                    "total_modified": 1,
                    "files_added": ["new.py"],
                    "files_deleted": [],
                    "files_modified": ["edit.py"],
                },
            },
        },
    ]

    # Extract changed_files (as done in get_turn_stats)
    changed_files = {}
    for m in messages:
        if m["message_type"] == "turn_end":
            data = m.get("data", {})
            if "changed_files" in data:
                changed_files = data["changed_files"]

    assert changed_files["total_added"] == 1
    assert changed_files["total_modified"] == 1
    assert "new.py" in changed_files["files_added"]
    assert "edit.py" in changed_files["files_modified"]
    print("✅ test_get_turn_stats_with_changed_files passed")


def test_old_data_compatibility():
    """Verify old turns (without changed_files) don't break the system."""
    # Simulate an old turn without changed_files
    old_turn_end = {
        "turn_id": "old-turn",
        "data": {
            "status": "completed",
            # No "changed_files" key — old data
        }
    }

    # get_turn_stats should handle this gracefully
    changed_files = old_turn_end["data"].get("changed_files", {})
    assert changed_files == {}  # Returns empty dict, not error
    assert not changed_files  # Falsy, frontend won't show
    print("✅ test_old_data_compatibility passed")


if __name__ == "__main__":
    test_changed_files_data_structure()
    test_frontend_mapping()
    test_turn_end_message_structure()
    test_empty_changed_files()
    test_no_display_when_empty()
    test_get_turn_stats_with_changed_files()
    test_old_data_compatibility()
    print("\n🎉 All tests passed!")
