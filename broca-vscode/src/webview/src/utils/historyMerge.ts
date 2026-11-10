/**
 * 历史消息「整页重载」的合并策略（与 Web 端 `broca-web/frontend/src/stores/chat.ts`
 * 的 loadHistory 语义保持一致）。
 *
 * 背景（Bug：明细模式下撤销成功后页面不刷新）：
 *   撤销/重做/清空历史后，WebView 会调用 loadHistory(skip=0) 重新拉取消息。
 *   服务端 `/session/{id}/messages` 会过滤 `reverted=True`，被撤销的消息不再出现在
 *   响应里。若重载时仍以「旧列表」为 base 合并，这些消息会被当成 live 消息保留下来，
 *   导致撤销成功后列表看起来毫无变化。
 *
 * 约定（关键）：
 *   调用方 `loadHistory(skip=0)` **必须在发请求前清空 `messages`**。
 *   因此传进来的 `liveMessages` 只可能包含「请求往返期间 socket 新到」的消息，
 *   服务端返回的数据是唯一权威 base。
 */

export interface HasMessageId {
  message_id: string
}

export interface ApplyHistoryReloadParams<T extends HasMessageId> {
  /** 服务端返回（并已通过 processMessage 过滤）的消息，顺序即最终展示顺序 */
  apiMessages: T[]
  /** 请求往返期间新到的消息（调用方清空列表后、响应返回前 socket 推送的） */
  liveMessages: T[]
}

/**
 * 构造整页重载后的消息列表：服务端数据在前，请求期间新到的消息追加在后（按 id 去重）。
 */
export function applyHistoryReload<T extends HasMessageId>({
  apiMessages,
  liveMessages,
}: ApplyHistoryReloadParams<T>): T[] {
  if (liveMessages.length === 0) return apiMessages
  const apiIds = new Set(apiMessages.map((m) => m.message_id))
  const extras = liveMessages.filter((m) => !apiIds.has(m.message_id))
  return extras.length > 0 ? [...apiMessages, ...extras] : apiMessages
}
