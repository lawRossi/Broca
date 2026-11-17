/**
 * Media URL resolution for display.
 *
 * Local media (read_image / user uploads when cloud storage is off) is stored as
 * a lightweight ref whose display url is a backend path like
 * `/files/raw?path=...`. The backend mounts these routes under `/api`, and
 * `<img src>` / `window.open` cannot use the axios baseURL, so we must prefix
 * `/api` explicitly. Cloud urls (public https) and blob/data urls pass through.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api'

export function resolveMediaUrl(url?: string | null): string {
  if (!url) return ''

  // Absolute / already-resolved urls pass through unchanged.
  if (/^https?:\/\//i.test(url) || url.startsWith('data:') || url.startsWith('blob:')) {
    return url
  }

  // Backend local media endpoints live under the API base (/api/files/...).
  if (url.startsWith('/files/')) {
    return `${API_BASE.replace(/\/+$/, '')}${url}`
  }

  return url
}
