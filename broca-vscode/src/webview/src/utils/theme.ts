// VSCode Theme Adapter
// Maps VSCode CSS custom properties to WebView styles

export function applyVSCodeTheme() {
  const body = document.body
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
