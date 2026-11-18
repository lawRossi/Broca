/**
 * 简洁模式 TurnCard 的「用户消息聚合」纯逻辑（便于单测）。
 *
 * 背景（本次修复）：non-blocking 模式下，一个 turn 内可以出现多条 user_message：
 *  - 首条在 turn 开始时由 LifecycleBroadcastHook 广播；
 *  - 用户在 agent 执行途中继续输入时，engine 会在 step 之间 drain 出这些消息，
 *    以相同 turn_id 广播（_inject_user_message）。
 *
 * Web 端会把同一 turn 的每条 user_message 逐条追加到 turn.userMessages，并在
 * TurnCard 里堆叠展示。VS Code 端原来只保留第一条（`if (!turn.userMessage)`），
 * 也没有渲染 userMessages，导致 mid-turn 注入的用户消息在 turn card 里看不到。
 * 该文件把与 web 端一致的聚合逻辑抽成纯函数，供 store 调用并单测。
 */

export interface UserMessageFile {
  name: string
  url: string
  path: string
  size: number
  type: string
}

export interface UserMessagesTurn {
  userMessage: string | null
  userMessages?: string[]
  userFiles?: UserMessageFile[] | null
}

/**
 * 从一条 user_message 的 data 中提取要展示的纯文本。
 *
 * 优先 raw_input（后端下发的纯文本）；否则解析 JSON content 并取其中的 content 字段。
 * 与 web 端 `updateTurnSummaryOnMessage` 的文本提取保持一致。
 */
export function extractUserMessageText(data: Record<string, any> | undefined): string | null {
  if (!data) return null
  if (data.raw_input !== undefined) return String(data.raw_input)

  const raw = data.content
  if (!raw) return null
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    return parsed?.content ? String(parsed.content) : String(parsed)
  } catch {
    return String(raw)
  }
}

/**
 * 把一条 user_message 累积进 turn。
 *
 * - data.tool_injected=true 的内部消息（如 read_image 注入的 image message）跳过；
 * - 通过 seenIds 按 message_id 去重（mid-step 广播可能对同一条消息推送两次）；
 * - 文本追加到 turn.userMessages，turn.userMessage 始终保留第一条（向后兼容）；
 * - 附件跨多条消息累积到 turn.userFiles。
 *
 * @returns 是否真的追加了一条新消息（未跳过、未重复）
 */
export function accumulateUserMessage(
  turn: UserMessagesTurn,
  messageId: string,
  data: Record<string, any> | undefined,
  seenIds: Set<string>
): boolean {
  if (data?.tool_injected) return false
  if (seenIds.has(messageId)) return false
  seenIds.add(messageId)

  const text = extractUserMessageText(data)
  if (text !== null) {
    if (!turn.userMessages) turn.userMessages = []
    turn.userMessages.push(text)
    turn.userMessage = turn.userMessages[0] // backward compat
  }

  if (data?.files) {
    if (!turn.userFiles) turn.userFiles = []
    turn.userFiles.push(...data.files)
  }

  return true
}

/**
 * TurnCard 实际要展示的 user 消息列表。
 *
 * 兼容两种数据源：历史 API 回填的 userMessages 数组、以及只有单条 userMessage 的
 * 旧数据（socket 首条消息 / 老版本后端）。与 web 端 displayUserMessages 一致。
 */
export function getDisplayUserMessages(turn: UserMessagesTurn): string[] {
  if (turn.userMessages?.length) return turn.userMessages
  if (turn.userMessage) return [turn.userMessage]
  return []
}
