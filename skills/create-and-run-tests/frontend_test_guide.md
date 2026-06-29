## 🎯 Frontend Testing Guide

Frontend testing is **equally important** as backend testing. Many plans involve UI components, user interactions, and visual verification — these all need concrete automated tests.

### Frontend vs Backend: What's Different

| Aspect             | Backend Tests                             | Frontend Tests                                          |
| --------------------| -------------------------------------------| ---------------------------------------------------------|
| **What's tested**  | API endpoints, business logic, data layer | Components, pages, user interactions, visuals           |
| **Test runner**    | pytest (Python)                           | Vitest, Playwright, Cypress, Jest (JS/TS)               |
| **DOM required?**  | No                                        | Yes (jsdom for unit, real browser for E2E)              |
| **Async patterns** | `async/await` on DB/HTTP calls            | `userEvent`, `waitFor`, `findBy*` for user interactions |
| **Assertions**     | `assert x == y`                           | `expect(screen.getByText('...')).toBeVisible()`         |
| **Mocking**        | `unittest.mock`, `pytest-mock`            | `vi.mock()`, MSW (Mock Service Worker) for API mocking  |

### Frontend Test Types

| Test Type | What It Tests | Tools | Speed | When to Use |
|-----------|--------------|-------|-------|-------------|
| **Unit Test** | Pure functions, utilities, hooks | Vitest, Jest | ⚡ Fast | Every non-trivial function or util |
| **Component Test** | Single component: render, props, events | Vitest + Testing Library | 🟡 Fast | Every interactive component |
| **E2E Test** | Full user journeys across pages | Playwright, Cypress | 🐢 Slow | Critical user paths |
| **Visual Regression** | Pixel-perfect screenshot comparison | Playwright `.toHaveScreenshot()` | 🐢 Slow | UI with strict visual requirements |
| **Accessibility** | WCAG compliance, keyboard nav | `@axe-core/playwright` | 🟡 Medium | Every page and key component |

### Quick Guide: AC → Test Type

| Acceptance Criteria Example | Test Approach |
|----------------------------|---------------|
| "Clicking submit shows a loading spinner" | Component test: render button, click, assert spinner |
| "Form validates email format on blur" | Component test: type invalid email, blur, assert error |
| "User can navigate to profile page" | E2E test: click link, assert URL |
| "Button is accessible via keyboard Tab" | Accessibility test: tab to element, assert focus |
| "Layout switches to single column on mobile" | E2E test: set viewport 375px, assert layout |
| "API error shows a toast notification" | Component test: mock API failure, assert toast |

### Testing Stack Detection

```bash
# Detect framework
cat package.json | grep -E '"vue|"react|"next|"nuxt|"svelte|"angular"'

# Detect test tools
cat package.json | grep -E '"vitest|"jest|"playwright|"cypress|"@testing-library"'

# Detect config files
ls vitest.config.* playwright.config.* 2>/dev/null
```

If no test tools detected, install them as part of the testing task.

### Vue 3 Examples

#### Component Test: Interactive Component (3 ACs)

```typescript
// components/__tests__/DeleteButton.test.ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import DeleteButton from '../DeleteButton.vue'

describe('DeleteButton', () => {
  it('AC1: clicking delete button shows confirmation dialog', async () => {
    const user = userEvent.setup()
    render(DeleteButton, { props: { onConfirm: vi.fn() } })
    await user.click(screen.getByRole('button', { name: /delete/i }))
    expect(screen.getByRole('dialog')).toBeVisible()
  })

  it('AC2: clicking confirm calls onConfirm callback', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(DeleteButton, { props: { onConfirm } })
    await user.click(screen.getByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('AC3: clicking cancel hides the dialog', async () => {
    const user = userEvent.setup()
    render(DeleteButton, { props: { onConfirm: vi.fn() } })
    await user.click(screen.getByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
```

#### E2E Test with Playwright

```typescript
// e2e/login.spec.ts
import { test, expect } from '@playwright/test'

test('AC: full login flow redirects to dashboard', async ({ page }) => {
  await page.goto('/login')
  await page.fill('[data-testid="email-input"]', 'user@example.com')
  await page.fill('[data-testid="password-input"]', 'CorrectP@ss1')
  await page.click('[data-testid="login-button"]')
  await expect(page).toHaveURL(/\/dashboard/)
})
```

#### Accessibility Test

```typescript
// e2e/accessibility.spec.ts
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('AC: login page has no critical a11y violations', async ({ page }) => {
  await page.goto('/login')
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(results.violations.filter(v => v.impact === 'critical')).toEqual([])
})
```

### React Examples

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

it('shows confirmation dialog on click', async () => {
  const user = userEvent.setup()
  render(<DeleteButton onConfirm={vi.fn()} />)
  await user.click(screen.getByRole('button', { name: /delete/i }))
  expect(screen.getByRole('dialog')).toBeVisible()
})
```

### Frontend Test File Organization

```
tests/
├── {plan-name}/
│   ├── phase-01-{phase-name}/
│   │   ├── test_task_01_user_registration.py    (backend)
│   │   ├── test_task_02_login_page.py           (frontend)
│   │   ├── test_task_03_home_page.py            (frontend)
│   │   └── phase-ac-tests/
│   │       └── test_phase_integration.py
│   └── ...
├── setup.ts
├── vitest.config.ts
└── playwright.config.ts
```

Or co-located inside `src/` if the project already has that convention:

```
src/
├── components/
│   ├── LoginForm.vue
│   └── __tests__/
│       └── LoginForm.test.ts
├── composables/
│   └── __tests__/
│       └── useAuth.test.ts
```

When the project already has a test convention, **follow the existing convention**.

### Frontend Test Anti-Patterns

| Don't                                        | Do Instead                                                |
| ----------------------------------------------| -----------------------------------------------------------|
| Test internal state / implementation details | Test behavior: what the user sees and does                |
| Use `wrapper.vm` to check internal state     | Use `screen.getByText()`, `screen.getByRole()`            |
| Single giant E2E test                        | Focused E2E tests per user journey                        |
| Only do E2E, no component tests              | Component tests for fast feedback, E2E for critical paths |
| Overuse `data-testid`                        | Prefer accessible queries (`getByRole`, `getByLabelText`) |
| Skip mocking API calls (flaky tests)         | Mock at network level with MSW or `vi.mock()`             |
| Only test the happy path                     | Include loading, empty, error, and validation states      |
