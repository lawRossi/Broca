"""
Broca CLI — Git Worktree Management

Manages git worktrees under `<repo-root>/.worktrees/` with automatic
Broca session creation/deletion via the Web API.

Commands:
    broca worktree create <branch>   Create a worktree + session
    broca worktree delete <branch>   Delete a worktree + session
    broca worktree list              List all Broca-managed worktrees
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Git helper functions
# ---------------------------------------------------------------------------


def get_repo_root() -> Path:
    """Get the root directory of the current git repository.

    Raises:
        RuntimeError: If the current directory is not inside a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("git not found. Please install git.")

    if result.returncode != 0:
        raise RuntimeError("Not in a git repository")

    return Path(result.stdout.strip())


def get_worktrees_dir(repo_root: Path) -> Path:
    """Return the managed worktrees directory: <repo_root>/.worktrees."""
    return repo_root / ".worktrees"


def _branch_to_dirname(branch: str) -> str:
    """Convert a branch name to a safe directory name.

    Replaces '/' with '_' to avoid nested directories.
    e.g. "feature/auth" -> "feature_auth"
    """
    return branch.replace("/", "_")


def git_worktree_add(repo_root: Path, branch: str, worktree_path: Path) -> None:
    """Add a git worktree. Creates the branch if it doesn't exist.

    Args:
        repo_root: The git repository root directory.
        branch: The branch name to checkout in the worktree.
        worktree_path: The target path for the worktree.

    Raises:
        RuntimeError: If any git command fails.
    """
    # Check if branch exists
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        # Branch doesn't exist — create it based on HEAD
        result = subprocess.run(
            ["git", "branch", branch],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create branch '{branch}': {result.stderr.strip()}"
            )

    # Add the worktree
    result = subprocess.run(
        ["git", "worktree", "add", str(worktree_path), branch],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to add worktree at '{worktree_path}': {result.stderr.strip()}"
        )


def git_worktree_remove(repo_root: Path, worktree_path: Path, force: bool = False) -> None:
    """Remove a git worktree and prune stale references.

    Args:
        repo_root: The git repository root directory.
        worktree_path: The worktree path to remove.
        force: If True, force removal even with uncommitted changes.

    Raises:
        RuntimeError: If the git worktree remove command fails.
    """
    cmd = ["git", "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(worktree_path))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to remove worktree '{worktree_path}': {result.stderr.strip()}"
        )

    # Prune stale worktree references
    subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )


def git_worktree_list(repo_root: Path) -> list[dict[str, Any]]:
    """List all git worktrees, parsed from --porcelain output.

    Returns:
        A list of dicts, each with keys: path, branch, bare, detached.
        - path: absolute path (str)
        - branch: branch name or None (for detached)
        - bare: bool
        - detached: bool

    Raises:
        RuntimeError: If the git command fails.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to list worktrees: {result.stderr.strip()}"
        )

    # Parse porcelain output:
    # worktree /path/to/main
    # HEAD abc123
    # branch refs/heads/main
    #
    # worktree /path/to/feature
    # HEAD def456
    # branch refs/heads/feature
    #
    # worktree /path/to/detached
    # HEAD 123456
    # detached
    #
    # blank lines separate entries

    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    for line in result.stdout.splitlines():
        if line == "":
            if current:
                worktrees.append(current)
                current = {}
            continue

        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            # "branch refs/heads/feature-x" -> "feature-x"
            ref = line[len("branch "):]
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line.strip() == "detached":
            current["detached"] = True
        elif line.startswith("bare"):
            current["bare"] = True

    # Last entry (no trailing blank line)
    if current:
        worktrees.append(current)

    # Normalize: ensure all expected keys exist
    for wt in worktrees:
        wt.setdefault("branch", None)
        wt.setdefault("bare", False)
        wt.setdefault("detached", False)

    return worktrees


# ---------------------------------------------------------------------------
# Web API helper functions
# ---------------------------------------------------------------------------

DEFAULT_API_BASE_URL = "http://localhost:9000"


def api_request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    base_url: str = DEFAULT_API_BASE_URL,
    timeout: int = 15,
) -> dict:
    """Make an HTTP request to the Broca Web API.

    Args:
        method: HTTP method (GET, POST, DELETE, PUT).
        path: API path starting with '/api/...' (e.g. '/api/session/sessions').
        body: Optional JSON request body.
        base_url: Base URL of the API server.
        timeout: Request timeout in seconds.

    Returns:
        The 'data' field from the API response.

    Raises:
        RuntimeError: If the API returns a non-200 code or an HTTP error occurs.
        ConnectionRefusedError: If the API server is not running.
    """
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Try to parse error body
        try:
            err_body = json.loads(e.read())
            msg = err_body.get("msg", str(e))
        except Exception:
            msg = str(e)
        raise RuntimeError(f"API error ({e.code}): {msg}") from e

    if result.get("code") != 200:
        raise RuntimeError(f"API error: {result.get('msg', 'Unknown error')}")

    return result.get("data")


def find_session_by_workspace(
    workspace: str, base_url: str = DEFAULT_API_BASE_URL
) -> Optional[dict]:
    """Find a Broca session by its workspace path.

    Args:
        workspace: The absolute workspace path to search for.
        base_url: Base URL of the API server.

    Returns:
        The matching session dict, or None if not found / API unreachable.
    """
    try:
        data = api_request("GET", "/api/session/sessions?limit=200", base_url=base_url)
    except (RuntimeError, ConnectionRefusedError, OSError):
        return None

    sessions = data.get("sessions", []) if isinstance(data, dict) else data
    if not isinstance(sessions, list):
        return None

    for session in sessions:
        if session.get("workspace") == workspace:
            return session

    return None


# ---------------------------------------------------------------------------
# .gitignore helper
# ---------------------------------------------------------------------------


def ensure_worktrees_gitignored(repo_root: Path) -> None:
    """Ensure `.worktrees/` is listed in the repo's .gitignore.

    Creates .gitignore if it doesn't exist. Appends the entry if missing.
    """
    gitignore = repo_root / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text()
        lines = content.splitlines()
        # Check if .worktrees/ is already in .gitignore
        for line in lines:
            if line.strip() == ".worktrees/" or line.strip() == ".worktrees":
                return  # Already present
        # Append
        if content and not content.endswith("\n"):
            content += "\n"
        content += ".worktrees/\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(".worktrees/\n")


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------


def cmd_worktree_create(args: Any) -> None:
    """Handle `broca worktree create <branch>`.

    Creates a git worktree for the given branch and a Broca session
    (via Web API) with the worktree path as workspace.
    """
    branch = args.branch
    if not branch:
        print("Error: branch name is required")
        print("Usage: broca worktree create <branch>")
        sys.exit(1)

    try:
        repo_root = get_repo_root()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Ensure .worktrees/ is in .gitignore
    ensure_worktrees_gitignored(repo_root)

    worktrees_dir = get_worktrees_dir(repo_root)
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    # Compute worktree path (replace / with _ in branch name)
    dir_name = _branch_to_dirname(branch)
    worktree_path = worktrees_dir / dir_name

    # Check if worktree already exists
    if worktree_path.exists():
        # Check if it's a registered git worktree
        try:
            worktrees = git_worktree_list(repo_root)
            for wt in worktrees:
                if Path(wt["path"]).resolve() == worktree_path.resolve():
                    print(f"Error: Worktree for branch '{branch}' already exists at {worktree_path}")
                    sys.exit(1)
        except RuntimeError:
            pass
        # Residual directory (not a git worktree) — try prune and retry
        print(f"Note: Residual directory found at {worktree_path}, attempting prune...")
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True, text=True, cwd=str(repo_root), check=False,
        )

    # Create the worktree
    try:
        git_worktree_add(repo_root, branch, worktree_path)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    resolved_path = str(worktree_path.resolve())

    # Create session via Web API
    session_id: Optional[str] = None
    try:
        body: dict[str, Any] = {
            "description": f"worktree:{branch}",
            "workspace": resolved_path,
        }
        if args.description:
            body["description"] = args.description
        if args.provider:
            body["provider"] = args.provider
        if args.model:
            body["model"] = args.model

        data = api_request("POST", "/api/session/sessions", body=body)
        session_id = data.get("session_id") if isinstance(data, dict) else None
    except (RuntimeError, ConnectionRefusedError, OSError) as e:
        print(f"\n⚠ Warning: Could not create Broca session via Web API: {e}")
        print("  The worktree was created, but no session was started.")
        print("  Start Broca services and create a session manually if needed.")
        session_id = None

    # Output result
    separator = "━" * 42
    print(f"\n{separator}")
    print(" ✓ Worktree created")
    print(f" Branch:     {branch}")
    print(f" Path:       {worktree_path}")
    if session_id:
        print(f" Session:    {session_id}")
    print(f" Workspace:  {resolved_path}")
    print(f"{separator}\n")


def cmd_worktree_delete(args: Any) -> None:
    """Handle `broca worktree delete <branch>`.

    Deletes the Broca session (via Web API) and removes the git worktree.
    """
    branch = args.branch
    if not branch:
        print("Error: branch name is required")
        print("Usage: broca worktree delete <branch>")
        sys.exit(1)

    try:
        repo_root = get_repo_root()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Compute worktree path
    worktrees_dir = get_worktrees_dir(repo_root)
    dir_name = _branch_to_dirname(branch)
    worktree_path = worktrees_dir / dir_name

    # Verify worktree exists in git
    try:
        worktrees = git_worktree_list(repo_root)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    worktree_found = False
    for wt in worktrees:
        if Path(wt["path"]).resolve() == worktree_path.resolve():
            worktree_found = True
            break

    if not worktree_found:
        print(f"Error: No worktree found for branch '{branch}'")
        sys.exit(1)

    # Find and delete associated session
    resolved_path = str(worktree_path.resolve())
    session_deleted = False
    session_id_str = "-"

    session = find_session_by_workspace(resolved_path)
    if session:
        session_id_str = session.get("session_id", "unknown")
        print(f"Deleting session: {session_id_str}")
        try:
            api_request("DELETE", f"/api/session/{session_id_str}")
            session_deleted = True
        except (RuntimeError, ConnectionRefusedError, OSError) as e:
            print(f"⚠ Warning: Could not delete session via API: {e}")
            print("  The worktree will still be removed.")
    else:
        print("No Broca session found for this worktree.")

    # Remove the git worktree
    force = getattr(args, "force", False)
    try:
        git_worktree_remove(repo_root, worktree_path, force=force)
    except RuntimeError as e:
        if not force:
            # Check if it's a "not empty" error
            if "not empty" in str(e).lower() or "contains local changes" in str(e).lower() or "uncommitted" in str(e).lower():
                print(f"Error: Worktree has uncommitted changes. Use --force to discard.")
            else:
                print(f"Error: {e}")
        else:
            print(f"Error: {e}")
        sys.exit(1)

    # Clean up empty .worktrees directory if it becomes empty
    if worktrees_dir.exists():
        remaining = [p for p in worktrees_dir.iterdir() if p.is_dir()]
        if not remaining:
            worktrees_dir.rmdir()

    # Output result
    separator = "━" * 42
    print(f"\n{separator}")
    print(" ✓ Worktree deleted")
    print(f" Branch:     {branch}")
    print(f" Path:       {worktree_path}")
    if session_deleted:
        print(f" Session:    {session_id_str} (deleted)")
    elif session:
        print(f" Session:    {session_id_str} (deletion failed)")
    print(f"{separator}\n")


def cmd_worktree_list(args: Any) -> None:
    """Handle `broca worktree list`.

    Lists all Broca-managed worktrees with their associated session info.
    """
    try:
        repo_root = get_repo_root()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    worktrees_dir = get_worktrees_dir(repo_root)

    try:
        all_worktrees = git_worktree_list(repo_root)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Prune stale worktrees
    subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True, text=True, cwd=str(repo_root), check=False,
    )

    # Filter: only Broca-managed worktrees (under .worktrees/)
    broca_worktrees = []
    worktrees_dir_resolved = worktrees_dir.resolve()
    for wt in all_worktrees:
        wt_path = Path(wt["path"]).resolve()
        try:
            wt_path.relative_to(worktrees_dir_resolved)
            broca_worktrees.append(wt)
        except ValueError:
            continue

    if not broca_worktrees:
        print("No Broca worktrees found.")
        return

    # Fetch sessions (graceful degradation)
    sessions_by_workspace: dict[str, dict] = {}
    try:
        data = api_request("GET", "/api/session/sessions?limit=200")
        sessions = data.get("sessions", []) if isinstance(data, dict) else data
        if isinstance(sessions, list):
            for s in sessions:
                ws = s.get("workspace")
                if ws:
                    sessions_by_workspace[ws] = s
    except (RuntimeError, ConnectionRefusedError, OSError):
        pass  # API unavailable — degrade gracefully

    # Print table
    headers = ("BRANCH", "PATH", "SESSION", "STATUS")
    rows = []
    for wt in broca_worktrees:
        wt_path = Path(wt["path"]).resolve()
        branch_display = wt.get("branch") or ("DETACHED" if wt.get("detached") else "unknown")

        # Relative path from repo_root
        try:
            rel_path = str(wt_path.relative_to(repo_root.resolve()))
        except ValueError:
            rel_path = wt_path.name

        # Find matching session
        session = sessions_by_workspace.get(str(wt_path))
        if session:
            session_display = session.get("session_id", "-")
            status_display = session.get("runner_status", "stopped")
        else:
            session_display = "-"
            status_display = "-"

        rows.append((branch_display, rel_path, session_display, status_display))

    # Calculate column widths
    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(4)]

    # Print header
    header_line = "  ".join(headers[i].ljust(col_widths[i]) for i in range(4))
    print(header_line)
    print("  ".join("─" * col_widths[i] for i in range(4)))

    # Print rows
    for row in rows:
        print("  ".join(row[i].ljust(col_widths[i]) for i in range(4)))

    # Summary
    print(f"\n{len(rows)} worktree{'s' if len(rows) != 1 else ''}")

