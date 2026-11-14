/**
 * 「离开页面后返回」自动刷新的计时逻辑。
 *
 * 背景：用户离开页面（切标签页 / Alt+Tab / bfcache 前进后退）超过阈值后再回来，
 * 需要刷新会话数据。这里把计时判定抽成纯逻辑，便于单元测试。
 *
 * 设计要点（对应一个真实 bug 的修复）：
 *   - 之前的实现把 pageLoadTimestamp 作为模块级常量，SPA 路由复用模块时不会重置，
 *     导致 bfcache 的 pageshow 用「应用首次加载时间」计算离开时长，误判为
 *     「离开超过 1 分钟」而触发整页刷新。现在由 reset() 在每次挂载时重置，
 *     保证用本次挂载时间作为兜底基准。
 */

export const LEAVE_TIMEOUT_MS = 60 * 1000 // 1 分钟

export interface LeaveTracker {
  /** 组件挂载时调用：重置离开/加载时间戳（修复 SPA 路由复用模块导致的残留）。 */
  reset(now?: number): void
  /** 页面变为隐藏时调用：记录离开时刻（多次隐藏保留最早时间）。 */
  onHidden(now?: number): void
  /**
   * 页面重新可见时调用：判断离开时长是否达到阈值，并清除离开记录。
   * @returns true 表示应当刷新
   */
  onVisible(now?: number): boolean
}

/**
 * 创建一个离开计时器。
 * @param timeoutMs 离开多久后返回才触发刷新，默认 1 分钟
 */
export function createLeaveTracker(timeoutMs: number = LEAVE_TIMEOUT_MS): LeaveTracker {
  // 0 表示本次会话尚无离开记录
  let leaveTimestamp = 0
  // 本次挂载/加载时刻，用于兜底「页面在后台标签页打开」的场景
  let pageLoadTimestamp = Date.now()

  return {
    reset(now = Date.now()) {
      leaveTimestamp = 0
      pageLoadTimestamp = now
    },
    onHidden(now = Date.now()) {
      // 若已处于离开状态则保留最早时间戳，避免被更晚的隐藏事件覆盖而缩短离开时长
      if (leaveTimestamp === 0) {
        leaveTimestamp = now
      }
    },
    onVisible(now = Date.now()) {
      // 有离开记录用离开时刻；无记录（如刚挂载 / 后台打开）用加载时刻兜底
      const lastHidden = Math.max(leaveTimestamp, pageLoadTimestamp)
      const shouldRefresh = now - lastHidden >= timeoutMs
      leaveTimestamp = 0
      return shouldRefresh
    },
  }
}
