/**
 * Turn 卡片状态是否还能被「实时消息」改写（纯函数，便于单测）。
 *
 * 背景一（本次修复）：`turn_end` 是卡片进入「已完成/中断」的权威信号，但流式
 * `agent_response` 可能在 `turn_end` **之后**才到达（后端残余 chunk 的延迟 flush）。
 * 前端 `updateTurnSummaryOnMessage` 对 `agent_response` 会把状态置为 `thinking`、
 * 对 `tool_call` 置为 `calling_tool`，若此时 turn 已经结束，卡片就会从「已完成」
 * 被打回「进行中」，且之后再没有任何事件把它改回来（只能靠切模式或整页刷新重新
 * 拉取历史），表现为「turn 明明结束了，卡片还是进行中」。
 *
 * 背景二（为什么不能按 status 判断）：`status === 'error'` **不是**终态。
 * LLM 调用失败会自动重试，重试期间后端会广播 error 通知（"LLM 调用失败，正在重试..."
 * / "请求频率过高，N 秒后自动重试..."，见 `RetryLLMStrategy`），重试成功后 turn 继续跑。
 * （现在 error 消息已经完全不改卡片状态，只由 ChatMessageList 独立渲染；
 * `status === 'error'` 只可能来自 `turn_end` 或历史数据。）
 *
 * 因此：**`isActive` 是「turn 是否已结束」的唯一权威标记** —— 只有 `turn_end`
 * 事件（以及历史加载）可以把它置为 false。已结束的 turn 不再接受「进行中」类状态，
 * 但迟到的消息仍可追加内容（最终回复、工具统计等）。
 */

export interface TurnStatusSnapshot {
  /** turn 是否仍在进行中（仅 turn_end / 历史加载可置 false） */
  isActive: boolean
  status: string
}

/**
 * 该 turn 是否允许被实时消息改写成「进行中」类状态（active / thinking / calling_tool）。
 *
 * @param turn 目标 turn 的当前状态快照
 * @returns true 表示可以改写；false 表示 turn 已结束（收到过 turn_end），忽略降级
 */
export function canUpdateTurnRunningStatus(turn: TurnStatusSnapshot): boolean {
  return turn.isActive
}
