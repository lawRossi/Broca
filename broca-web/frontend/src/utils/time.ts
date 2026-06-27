/**
 * 时间格式化工具 - 使用当地时间
 */

/**
 * 将输入转换为 Date 对象
 * @param date 日期对象或时间戳字符串
 * @returns Date 对象
 */
export const toDate = (date: Date | string | number | null | undefined): Date => {
  // 处理 null 和 undefined
  if (date === null || date === undefined) {
    return new Date()
  }

  let d: Date
  if (typeof date === 'string' || typeof date === 'number') {
    d = new Date(date)
  } else {
    d = date
  }

  // 检查是否是无效日期
  if (isNaN(d.getTime())) {
    return new Date()
  }

  return d
}

/**
 * 格式化为当地时间字符串
 * @param date 日期对象或时间戳字符串
 * @param options 格式化选项
 * @returns 格式化的当地时间字符串
 */
export const formatTime = (
  date: Date | string | number | null | undefined,
  options: Intl.DateTimeFormatOptions = {}
): string => {
  try {
    const localDate = toDate(date)

    const defaultOptions: Intl.DateTimeFormatOptions = {
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      ...options,
    }

    return localDate.toLocaleString(undefined, defaultOptions)
  } catch (error) {
    console.error('Error formatting time:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleString()
  }
}

/**
 * 格式化为简短的时间字符串（今天显示时间，其他显示日期）
 * @param date 日期对象或时间戳字符串
 * @returns 简化的时间字符串
 */
export const formatTimeShort = (date: Date | string | number | null | undefined): string => {
  try {
    const localDate = toDate(date)

    // 获取当前日期
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const messageDate = new Date(localDate.getFullYear(), localDate.getMonth(), localDate.getDate())

    // 判断是否是今天
    if (messageDate.getTime() === today.getTime()) {
      // 今天：只显示时间
      return localDate.toLocaleTimeString(undefined, {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
      })
    } else {
      // 不是今天：显示日期和时间
      const dateStr = localDate.toLocaleDateString(undefined, {
        month: '2-digit',
        day: '2-digit',
      })
      const timeStr = localDate.toLocaleTimeString(undefined, {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
      })
      return `${dateStr} ${timeStr}`
    }
  } catch (error) {
    console.error('Error formatting time short:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleTimeString()
  }
}

/**
 * 格式化日期（只显示日期）
 * @param date 日期对象或时间戳字符串
 * @returns 格式化的日期字符串
 */
export const formatDate = (date: Date | string | number | null | undefined): string => {
  try {
    const localDate = toDate(date)

    // 获取当前日期
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const messageDate = new Date(localDate.getFullYear(), localDate.getMonth(), localDate.getDate())

    // 判断是否是今天
    if (messageDate.getTime() === today.getTime()) {
      // 今天：显示"今天"
      return '今天'
    } else {
      // 不是今天：显示日期
      return localDate.toLocaleDateString(undefined, {
        month: '2-digit',
        day: '2-digit',
      })
    }
  } catch (error) {
    console.error('Error formatting date:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleDateString()
  }
}

/**
 * 格式化Unix时间戳为当地时间
 * @param timestamp Unix时间戳（秒）
 * @returns 格式化的当地时间字符串
 */
export const formatUnixTime = (timestamp: number): string => {
  // timestamp是秒数，需要乘以1000转换为毫秒
  return formatTime(timestamp * 1000)
}

/**
 * 格式化Unix时间戳为简短的当地时间
 * @param timestamp Unix时间戳（秒）
 * @returns 简化的当地时间字符串
 */
export const formatUnixTimeShort = (timestamp: number): string => {
  // timestamp是秒数，需要乘以1000转换为毫秒
  return formatTimeShort(timestamp * 1000)
}
