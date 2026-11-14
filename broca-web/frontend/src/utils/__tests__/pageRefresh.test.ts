/**
 * 回归测试：离开页面后返回的自动刷新计时逻辑。
 *
 * Bug：pageLoadTimestamp 作为模块级常量，SPA 路由复用模块时不会重置，
 * bfcache 的 pageshow 用「应用首次加载时间」计算离开时长，误判为
 * 「离开超过 1 分钟」而触发刷新。修复后由 reset() 在每次挂载时重置基准。
 *
 * 同时覆盖基础判定：离开 < 阈值不刷新、>= 阈值刷新、多次离开返回、后台打开兜底。
 */
import { describe, it, expect } from 'vitest'
import { createLeaveTracker, LEAVE_TIMEOUT_MS } from '@/utils/pageRefresh'

const MIN = 60 * 1000

describe('createLeaveTracker', () => {
  it('默认阈值为 1 分钟', () => {
    expect(LEAVE_TIMEOUT_MS).toBe(MIN)
  })

  it('回归：reset 后（模拟重新挂载）短时间内返回不刷新，不受旧的加载时间影响', () => {
    // 模拟 tracker 早已创建（pageLoadTimestamp 很旧），但组件在 T=1_000_000 才挂载并 reset
    const tracker = createLeaveTracker()
    tracker.reset(1_000_000)
    // 挂载后 5 秒返回（期间没有离开记录），不应刷新
    expect(tracker.onVisible(1_000_000 + 5_000)).toBe(false)
  })

  it('没有离开记录、且距加载已超过阈值 → 刷新（后台打开兜底）', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    // 从未 onHidden，但已过 2 分钟 → 以加载时刻为基准，判定刷新
    expect(tracker.onVisible(2 * MIN)).toBe(true)
  })

  it('离开不足阈值不刷新', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    tracker.onHidden(1_000)
    expect(tracker.onVisible(1_000 + 10_000)).toBe(false) // 离开 10 秒
  })

  it('离开恰好达到阈值（1 分钟）刷新（>= 边界）', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    tracker.onHidden(1_000)
    expect(tracker.onVisible(1_000 + MIN)).toBe(true)
  })

  it('离开超过阈值刷新', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    tracker.onHidden(1_000)
    expect(tracker.onVisible(1_000 + 2 * MIN)).toBe(true)
  })

  it('onVisible 后离开记录被清除，下一次离开重新计时', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    // 第一次：离开 4 秒，不刷新
    tracker.onHidden(1_000)
    expect(tracker.onVisible(5_000)).toBe(false)
    // 第二次：离开 90 秒，刷新
    tracker.onHidden(20_000)
    expect(tracker.onVisible(20_000 + 90_000)).toBe(true)
  })

  it('多次 onHidden 保留最早离开时间（不被更晚的隐藏事件缩短时长）', () => {
    const tracker = createLeaveTracker()
    tracker.reset(0)
    tracker.onHidden(1_000) // 最早离开
    tracker.onHidden(50_000) // 更晚的隐藏事件不应覆盖
    // 从最早离开点算已超过阈值 → 刷新
    expect(tracker.onVisible(1_000 + MIN)).toBe(true)
  })

  it('支持自定义阈值', () => {
    const below = createLeaveTracker(5_000)
    below.reset(0)
    below.onHidden(1_000)
    expect(below.onVisible(1_000 + 4_999)).toBe(false)

    const at = createLeaveTracker(5_000)
    at.reset(0)
    at.onHidden(1_000)
    expect(at.onVisible(1_000 + 5_000)).toBe(true)
  })
})
