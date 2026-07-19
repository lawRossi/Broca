/**
 * Shared error handling utilities for Broca VS Code extension.
 *
 * Provides consistent error message extraction from various error formats
 * (Axios HTTP errors, network errors, generic JS errors) and helper methods
 * for displaying errors to the user.
 */

import * as vscode from 'vscode'

// ─── Types ───────────────────────────────────────────────────────────────────

/** Error-like object that may come from Axios, fetch, or generic sources */
interface ErrorLike {
  message?: string
  code?: string
  response?: {
    status?: number
    data?: any
  }
}

// ─── Extractors ──────────────────────────────────────────────────────────────

/**
 * Extract a human-readable error message from any error-like object.
 *
 * Handles multiple response formats:
 * - Axios: error.response.data = { detail, msg, message } or plain string
 * - Network: error.code === 'ECONNABORTED' (timeout), or no response (offline)
 * - Generic: error.message
 *
 * @param error  The caught error (any shape)
 * @param fallback  Fallback message if nothing can be extracted
 */
export function extractErrorMessage(error: ErrorLike | null | undefined, fallback: string = 'Unknown error'): string {
  if (!error) return fallback

  // No response → network-level failure
  if (!error.response) {
    if (error.code === 'ECONNABORTED') {
      return '请求超时，请检查网络连接'
    }
    if (error.code === 'ERR_NETWORK' || error.code === 'ECONNREFUSED') {
      return '无法连接服务器，请检查服务是否在运行'
    }
    // No specific network code
    if (!error.response && error.message) {
      // Could be a generic network error
      return error.message
    }
    return '无法连接服务器'
  }

  // Has response → try to extract server message
  const { data } = error.response
  if (data) {
    if (typeof data === 'string') return data
    return data.detail || data.msg || data.message || fallback
  }

  return error.message || fallback
}

/**
 * Show a VS Code error notification with a message derived from the error.
 * Also logs the full error to console for debugging.
 *
 * @param error  The caught error
 * @param contextLabel  Human-readable label like "打开聊天失败"
 * @param fallback  Optional fallback message
 */
export function showErrorNotification(
  error: ErrorLike | null | undefined,
  contextLabel: string,
  fallback?: string
): void {
  const message = extractErrorMessage(error, fallback)
  console.error(`[${contextLabel}]`, error)
  vscode.window.showErrorMessage(`${contextLabel}: ${message}`)
}

/**
 * Show an informational toast, typically for success feedback.
 */
export function showInfo(message: string): void {
  vscode.window.showInformationMessage(message)
}

/**
 * Show a warning notification.
 */
export function showWarning(message: string): void {
  vscode.window.showWarningMessage(message)
}
