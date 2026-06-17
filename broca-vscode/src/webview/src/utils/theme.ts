// VSCode Theme Adapter
// Maps VSCode CSS custom properties to WebView styles

export function applyVSCodeTheme() {
  const style = document.createElement('style')
  style.textContent = `
    :root {
      --bg-primary: var(--vscode-editor-background, #1e1e1e);
      --bg-secondary: var(--vscode-sideBar-background, #252526);
      --bg-tertiary: var(--vscode-input-background, #3c3c3c);
      --text-primary: var(--vscode-editor-foreground, #cccccc);
      --text-secondary: var(--vscode-descriptionForeground, #8b8b8b);
      --text-link: var(--vscode-textLink-foreground, #3794ff);
      --border-color: var(--vscode-panel-border, #3c3c3c);
      --button-bg: var(--vscode-button-background, #0e639c);
      --button-hover-bg: var(--vscode-button-hoverBackground, #1177bb);
      --button-text: var(--vscode-button-foreground, #ffffff);
      --input-bg: var(--vscode-input-background, #3c3c3c);
      --input-border: var(--vscode-input-border, #3c3c3c);
      --input-text: var(--vscode-input-foreground, #cccccc);
      --focus-border: var(--vscode-focusBorder, #007fd4);
      --badge-bg: var(--vscode-badge-background, #4d4d4d);
      --badge-text: var(--vscode-badge-foreground, #ffffff);
      --error-fg: var(--vscode-errorForeground, #f48771);
      --warning-fg: var(--vscode-editorWarning-foreground, #cca700);
      --success-fg: var(--vscode-testing-iconPassed, #73c991);
      --scrollbar-bg: var(--vscode-scrollbarSlider-background, #424242);
      --scrollbar-hover-bg: var(--vscode-scrollbarSlider-hoverBackground, #4f4f4f);
      --font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, sans-serif);
      --font-size: var(--vscode-font-size, 13px);
      --code-font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);

      /* Message type colors - VS Code native fusion */
      --message-user-bg: transparent;
      --message-user-border: var(--vscode-descriptionForeground, #8e8e8e);
      --message-agent-bg: transparent;
      --message-agent-border: #5a8fc9;
      --message-tool-bg: var(--vscode-input-background, rgba(128, 128, 128, 0.04));
      --message-tool-border: #c9a84c;
      --message-system-bg: transparent;
      --message-error-bg: var(--vscode-inputValidation-errorBackground, rgba(239, 68, 68, 0.06));
      --message-error-border: #c95a5a;

      /* List hover */
      --list-hover-bg: var(--vscode-list-hoverBackground, rgba(128, 128, 128, 0.08));

      /* Reasoning */
      --reasoning-text: var(--vscode-editorWarning-foreground, #fbbf24);

      /* Diff colors - VS Code native */
      --diff-added-bg: var(--vscode-diffEditor-insertedTextBackground, rgba(0, 200, 80, 0.15));
      --diff-added-fg: var(--vscode-editor-foreground, #166534);
      --diff-removed-bg: var(--vscode-diffEditor-removedTextBackground, rgba(200, 0, 0, 0.15));
      --diff-removed-fg: var(--vscode-editor-foreground, #991b1b);

      /* Status badge semantic colors (Crew/Orchestration) */
      --badge-pending-bg: var(--vscode-badge-background, #4d4d4d);
      --badge-pending-fg: var(--vscode-badge-foreground, #cccccc);
      --badge-running-bg: var(--vscode-activityBarBadge-background, #0e639c);
      --badge-running-fg: var(--vscode-activityBarBadge-foreground, #ffffff);
      --badge-completed-bg: var(--vscode-testing-iconPassed, #73c991);
      --badge-completed-fg: var(--vscode-badge-foreground, #ffffff);
      --badge-failed-bg: var(--vscode-testing-iconFailed, #f14c4c);
      --badge-failed-fg: var(--vscode-badge-foreground, #ffffff);
      --badge-aborted-bg: var(--vscode-testing-iconErrored, #cca700);
      --badge-aborted-fg: var(--vscode-badge-foreground, #ffffff);

      /* DAG phase indicator colors */
      --phase-completed: var(--vscode-testing-iconPassed, #73c991);
      --phase-running: var(--vscode-activityBarBadge-background, #0e639c);
      --phase-failed: var(--vscode-testing-iconFailed, #f14c4c);
      --phase-pending: var(--vscode-disabledForeground, #8b8b8b);

      /* Danger / error */
      --danger-bg: var(--vscode-inputValidation-errorBackground, #5a1d1d);
      --danger-border: var(--vscode-inputValidation-errorBorder, #c04040);
      --danger-hover-bg: var(--vscode-inputValidation-errorBorder, #c04040);
    }
  `
  document.head.appendChild(style)
}

export function getVSCodeThemeKind(): 'light' | 'dark' | 'high-contrast' {
  const body = document.body
  const bg = getComputedStyle(body).getPropertyValue('--vscode-editor-background').trim()
  if (!bg || bg === '#1e1e1e' || bg === '#252526' || bg === '#2d2d2d') {
    return 'dark'
  }
  // Check if high contrast
  if (bg === '#000000') return 'high-contrast'
  return 'light'
}
