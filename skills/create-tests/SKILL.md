---
name: create-tests
version: "1.1.0"
description: "Reads a plan document and creates a formal test suite for **one phase at a time**, derived from each task's acceptance criteria. Creates test files under `tests/{plan-name}/phase-{NN}/`, runs them, and produces results for the phase report. Use AFTER `execute-tasks` has completed implementation for the phase."
---

# Create Tests from Plan Document

This skill reads a plan document, derives **concrete, executable test cases** from each task's acceptance criteria, creates them under `tests/`, runs them, and produces results for the phase report — **one phase at a time**. It is invoked AFTER `execute-tasks` has completed implementation for the phase.

## The Complete Workflow

```
create-plan (skill)    → plans/*.md                  (plan with ACs)
                          │
create-tasks (skill)   → create Phase N tasks
execute-tasks (skill)  → implement Phase N
create-tests (skill)   → create + run Phase N tests
                      → ⏸️ results → phase report → wait for review
                          │
                          ▼  next phase...
```

## Quick Start

1. **Read the plan document** (or re-read the current phase section): Understand each task's acceptance criteria for this phase
2. **For each AC, derive test cases**: Turn "what must be true" into "how to verify it"
3. **Create test files under `tests/{plan-name}/phase-{NN}/`**: Organized per task, with clear AC-to-test mappings
4. **Cross-reference**: Each test links back to its source plan task and AC

## Core Principles

### 1. AC ⇔ Test Bijection

**Every acceptance criterion produces at least one test case.** No AC left untested.

| Plan Document | Test Artifact |
|---------------|---------------|
| Task N.M acceptance criterion #1 | One or more test cases |
| Task N.M acceptance criterion #2 | One or more test cases |
| All task ACs satisfied | All tests pass |

### 2. Tests Verify Implementation Against ACs

This skill creates tests from the plan document's ACs **after** implementation is complete. Running these tests against the implementation objectively determines whether each AC is satisfied.

- All tests passing = all ACs satisfied ✅
- Any test failing = corresponding AC not met ❌ → implementation needs fixing

### 3. Traceability

Every test must be traceable back to its originating plan task and AC. This enables:
- `execute-tasks` to know which tests to run for which task
- Clear reporting on which ACs pass/fail
- Impact analysis when the plan changes

## Test File Organization

Tests live under `tests/`, organized to mirror the plan structure:

```
tests/
├── {plan-name}/
│   ├── phase-01-{phase-name}/
│   │   ├── task-01-{task-name}/
│   │   │   ├── test_ac_01_{short_desc}.py    (or .sh, .md, etc.)
│   │   │   ├── test_ac_02_{short_desc}.py
│   │   │   └── ...
│   │   ├── task-02-{task-name}/
│   │   │   └── ...
│   │   ├── phase-ac-tests/                   (phase-level integration tests)
│   │   │   └── test_phase_integration.py
│   │   └── README.md                         (phase-level AC-to-test mapping)
│   └── phase-02-{phase-name}/
│       └── ...
```

### Naming Convention

Test files use a naming scheme that encodes their origin:

```
test_{plan}_{phase}_{task}_{ac}.{ext}
```

**Examples:**
- `test_blog_p01_t01_ac01_user_registers_successfully.py`
- `test_blog_p01_t01_ac02_email_verification.py`
- `test_blog_p01_phase_ac01_all_crud_operations.sh`

## Per-Phase Workflow

This skill is invoked **once per phase**, AFTER `execute-tasks` has completed implementation. It creates tests from the plan's ACs, runs them, and produces results for the phase report.

### Step 1: Read the Plan Document (Current Phase Section)

Read the plan document at `plans/{plan-name}.md`. Focus on the **current phase's section**:

- The phase's acceptance criteria (become integration tests)
- Each task's acceptance criteria (become task-level tests)
- Each task's steps and expected output (context for understanding what to test)

### Step 2: Analyze Each Acceptance Criterion

For each AC, ask:
- **What exactly needs to be verified?** (the observable outcome)
- **How can it be verified programmatically?** (test type)
- **What preconditions are needed?** (setup)
- **What is the expected result?** (assertion)

Map each AC to a test type:

| AC Type | Example AC | Test Approach |
|---------|------------|---------------|
| **Functional** | "User can register with email" | Unit/integration test: call register API, assert success response + DB state |
| **Behavioral** | "Clicking submit shows loading state" | UI/component test: render, trigger, assert visual state |
| **Data** | "Password is stored hashed" | Data test: inspect DB, assert hash algorithm |
| **Error handling** | "Invalid email shows error message" | Negative test: submit invalid input, assert error response |
| **Performance** | "Page loads under 2s" | Benchmark test: measure, assert under threshold |
| **Security** | "Unauthenticated access returns 401" | Security test: call without auth, assert 401 |
| **Integration** | "Order service calls payment service" | Integration test: mock payment, call order, assert interaction |
| **Verification** | "Config file is valid YAML" | Validation script: parse file, assert no error |
| **UI/UX** | "Button is accessible via keyboard" | Accessibility test: tab to element, assert focus |

### Step 3: Create Test Files

For each task in the plan, create its test directory and files:

#### 3.1 Create the directory structure

```
tests/{plan-name}/phase-{NN}-{phase-slug}/task-{NN}-{task-slug}/
```

#### 3.2 Write individual AC test files

Each test file should be **self-documenting** — clearly stating which AC it verifies:

**Python example (unit test):**

```python
"""
Test for: Task 1.1 - User Registration
AC: "User can register with email and password"
Plan: plans/blog-platform.md
"""
import pytest
from app.auth import register_user

def test_ac01_user_registers_successfully():
    """AC: User can register with email and password"""
    result = register_user("test@example.com", "SecureP@ss1")
    assert result.success is True
    assert result.user.email == "test@example.com"
```

**Shell example (infrastructure check):**

```bash
#!/bin/bash
# Test for: Task 2.3 - Database Migration
# AC: "Migration runs without data loss"
# Plan: plans/blog-platform.md

set -e
echo "AC: Migration runs without data loss"
echo "1. Taking pre-migration snapshot..."
# ... run migration, compare snapshots
echo "✅ AC verified: data preserved after migration"
```

**Markdown example (review checklist):**

```markdown
# Task 3.2: API Documentation — AC Verification
> Plan: plans/blog-platform.md

## AC: "All public endpoints are documented"
- [ ] GET /api/users — documented
- [ ] POST /api/users — documented
- [ ] GET /api/posts — documented
- [ ] Each endpoint has: description, params, response example

## AC: "Documentation is accessible at /docs"
- [ ] /docs returns 200
- [ ] Swagger UI loads without errors
```

#### 3.3 Create a README.md per phase directory

This serves as the AC-to-test mapping for all tasks in the phase, used by `execute-tasks` during phase execution:

```markdown
# Phase {N}: {Phase Name} — Test Mapping
> Plan: plans/{plan-name}.md

## Task {N.1}: {Task Name}

| AC | Test File | Type | How to Run |
|----|-----------|------|------------|
| {AC description} | `test_ac_01_*.py` | Unit | `pytest tests/{plan}/phase-{NN}/task-{NN}-{slug}/test_ac_01_*.py` |
| {AC description} | `test_ac_02_*.py` | Unit | `pytest tests/{plan}/phase-{NN}/task-{NN}-{slug}/test_ac_02_*.py` |

## Task {N.2}: {Task Name}

| AC | Test File | Type | How to Run |
|----|-----------|------|------------|
| ... | ... | ... | ... |

## Phase Integration Tests

| Test File | What It Verifies | How to Run |
|-----------|------------------|------------|
| `test_phase_integration.py` | {phase AC description} | `pytest tests/{plan}/phase-{NN}/phase-ac-tests/` |
```

### Step 4: Create Phase-Level Integration Tests

For each phase's **phase-level acceptance criteria**, create integration tests that verify the phase as a whole:

```python
"""
Phase-level integration test for: Phase 1 - User Authentication
Phase AC: "Full registration and login flow works end-to-end"
"""
def test_phase_ac01_full_auth_flow():
    """Phase AC: Full registration and login flow works end-to-end"""
    # Register
    register_result = register_user("test@example.com", "SecureP@ss1")
    assert register_result.success
    
    # Verify email (simulate clicking link)
    verify_result = verify_email(register_result.user.verification_token)
    assert verify_result.success
    
    # Login
    login_result = login("test@example.com", "SecureP@ss1")
    assert login_result.success
    assert login_result.token is not None
```

### Step 5: Verify Completeness

Cross-reference the plan's task list against the created test directories:

- Every Task with ACs → has a test directory? ✅
- Every AC → has at least one test file? ✅
- Every Phase → has a phase-level integration test? ✅

```bash
# Example: list all tasks in plan and check for corresponding test dirs
grep "#### Task" plans/blog-platform.md | while read -r line; do
    task_num=$(echo "$line" | grep -oP 'Task \K[\d.]+')
    task_name=$(echo "$line" | grep -oP '(?<=: ).*')
    slug=$(echo "$task_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
    test_dir="tests/blog-platform/phase-*/task-${task_num}-${slug}"
    if ls $test_dir 2>/dev/null; then
        echo "✅ Task $task_num: test dir exists"
    else
        echo "❌ Task $task_num: MISSING test dir"
    fi
done
```

### Step 6: Run Tests and Collect Results

Run the created tests and capture the results for the phase report:

```bash
# Run all tests for this phase
pytest tests/{plan-name}/phase-{NN}/ --tb=short -v
```

Record the output:
- Number of tests passed / failed / skipped
- Any test failures with details
- Phase-level integration test results

These results will be included in the phase report's **Test Results** section.

## Integration with Other Skills

### With create-tasks

`create-tasks` creates the task hierarchy in Task Management. `create-tests` should reference the same task numbering:

```
create-tasks naming:    {PlanName} / Task {N.M}: {Task Name}
create-tests naming:    tests/{plan-name}/phase-{NN}/task-{NN}-{task-slug}/
```

Both use the plan's Phase/Task numbering as the common key.

### With execute-tasks

`create-tests` runs AFTER `execute-tasks` has completed implementation for the phase. The integration is tight:

```
execute-tasks finishes implementing Phase N
  → all tasks marked complete (manual AC verification done)
  → create-tests creates formal tests from plan ACs
  → create-tests runs all tests
  → test results feed into the phase report
  → phase report includes: AC-by-AC results, test outputs, pass/fail summary
```

The phase report template in `execute-tasks` includes a **Test Results** section that should be populated with the output from this skill's Step 6.

### With the Phase Report

The phase report (written by `execute-tasks` Step 5.6) includes a "Test Results" section populated by this skill:

```
## Test Results

### Unit Tests
```
pytest tests/blog-platform/phase-01/ --tb=short
→ 12 passed, 0 failed
```

### Integration Tests
```
pytest tests/blog-platform/phase-01/phase-ac-tests/ --tb=short
→ 3 passed, 0 failed
```
```

### With the Phase Report

The phase report template in `execute-tasks` includes a "Test Results" section:

```
## Test Results

### Unit Tests
```
pytest tests/blog-platform/phase-01/ --tb=short
→ 12 passed, 0 failed
```

### Integration Tests
```
pytest tests/blog-platform/phase-01/phase-ac-tests/ --tb=short
→ 3 passed, 0 failed
```
```

## Handle Special Cases

### Case: Non-code tasks (documentation, research, design)

Not all tasks produce code. For non-code tasks, use verification checklists instead:

```markdown
# tests/{plan-name}/phase-{NN}/README.md

## Task: API Design Document
### AC: "All endpoints are documented with request/response schemas"
- [x] GET /users — documented with response schema
- [x] POST /users — documented with request + response schema
- [x] DELETE /users/{id} — documented
### AC: "Design follows RESTful conventions"
- [x] Resource URLs are nouns, not verbs
- [x] HTTP methods used correctly (GET=read, POST=create, etc.)
- [x] Status codes follow standards (200, 201, 400, 404, 500)
```

### Case: Test requires external dependencies (DB, API, service)

Document the setup requirements in the test file or a `conftest.py`:

```python
# conftest.py
import pytest
import os

@pytest.fixture
def db_session():
    """Requires: running PostgreSQL on localhost:5432"""
    db_url = os.getenv("TEST_DATABASE_URL", "postgresql://localhost/testdb")
    # ... setup and teardown
```

### Case: AC cannot be fully automated

If an AC involves manual verification (e.g., visual design review), document the manual steps:

```markdown
## AC: "Color contrast meets WCAG AA standard"
### Automated check
- Run: `npx axe --stdout http://localhost:3000`
- Expect: no color-contrast violations
### Manual check (supplemental)
- [ ] Review: text against background meets 4.5:1 ratio
- [ ] Review: large text meets 3:1 ratio
```

### Case: Plan is updated after tests are created

If the plan changes, tests may become outdated:
1. Re-read the updated plan document
2. Compare old ACs vs new ACs
3. For changed ACs: update or replace the corresponding test files
4. For removed ACs: remove obsolete test files
5. For new ACs: create new test files
6. Update the phase README.md mapping

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Write tests without reading the plan first | Always anchor on the plan document's ACs |
| Create one giant test file for all ACs | Organize tests per task/per AC for traceability |
| Skip tests for "obvious" ACs | Every AC needs at least one test — no exceptions |
| Write tests that don't map back to an AC | Every test file must state which AC it verifies |
| Forget to update tests when plan changes | Revisit tests whenever the plan is updated |
| Write overly vague tests | Each test should precisely verify one AC |
| Mix unit and integration tests arbitrarily | Separate task-level unit tests from phase-level integration tests |
