/**
 * 时间格式化工具 - 北京时间 (UTC+8)
 */

/**
 * 将时间转换为北京时间
 * @param date 日期对象或时间戳字符串
 * @returns 北京时间对象
 */
export const toBeijingTime = (date: Date | string | number | null | undefined): Date => {
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
  
  // 直接返回 Date 对象，不进行时区偏移
  // 时区转换应在 toLocaleString 等格式化函数中通过 timeZone 参数处理
  return d
}

/**
 * 格式化时间为北京时间字符串
 * @param date 日期对象或时间戳字符串
 * @param options 格式化选项
 * @returns 格式化的北京时间字符串
 */
export const formatBeijingTime = (
  date: Date | string | number | null | undefined,
  options: Intl.DateTimeFormatOptions = {}
): string => {
  try {
    const beijingTime = toBeijingTime(date)
    
    const defaultOptions: Intl.DateTimeFormatOptions = {
      timeZone: 'Asia/Shanghai',
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      ...options
    }
    
    return beijingTime.toLocaleString('zh-CN', defaultOptions)
  } catch (error) {
    console.error('Error formatting Beijing time:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleString('zh-CN')
  }
}

/**
 * 格式化时间为简短的北京时间（今天显示时间，其他显示日期）
 * @param date 日期对象或时间戳字符串
 * @returns 简化的北京时间字符串
 */
export const formatBeijingTimeShort = (date: Date | string | number | null | undefined): string => {
  try {
    const beijingTime = toBeijingTime(date)
    
    // 获取当前日期
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const messageDate = new Date(beijingTime.getFullYear(), beijingTime.getMonth(), beijingTime.getDate())
    
    // 判断是否是今天
    if (messageDate.getTime() === today.getTime()) {
      // 今天：只显示时间
      return beijingTime.toLocaleTimeString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit'
      })
    } else {
      // 不是今天：显示日期和时间
      const dateStr = beijingTime.toLocaleDateString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit'
      })
      const timeStr = beijingTime.toLocaleTimeString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit'
      })
      return `${dateStr} ${timeStr}`
    }
  } catch (error) {
    console.error('Error formatting Beijing time short:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleTimeString()
  }
}

/**
 * 格式化日期为北京时间（只显示日期）
 * @param date 日期对象或时间戳字符串
 * @returns 格式化的日期字符串
 */
export const formatBeijingDate = (date: Date | string | number | null | undefined): string => {
  try {
    const beijingTime = toBeijingTime(date)
    
    // 获取当前日期
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const messageDate = new Date(beijingTime.getFullYear(), beijingTime.getMonth(), beijingTime.getDate())
    
    // 判断是否是今天
    if (messageDate.getTime() === today.getTime()) {
      // 今天：显示"今天"
      return '今天'
    } else {
      // 不是今天：显示日期
      return beijingTime.toLocaleDateString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit'
      })
    }
  } catch (error) {
    console.error('Error formatting Beijing date:', error)
    if (!date) {
      return '-'
    }
    const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date
    return d.toLocaleDateString('zh-CN')
  }
}

/**
 * 格式化Unix时间戳为北京时间
 * @param timestamp Unix时间戳（秒）
 * @returns 格式化的北京时间字符串
 */
export const formatUnixTimestamp = (timestamp: number): string => {
  // timestamp是秒数，需要乘以1000转换为毫秒
  return formatBeijingTime(timestamp * 1000)
}

/**
 * 格式化Unix时间戳为简短的北京时间
 * @param timestamp Unix时间戳（秒）
 * @returns 简化的北京时间字符串
 */
export const formatUnixTimestampShort = (timestamp: number): string => {
  // timestamp是秒数，需要乘以1000转换为毫秒
  return formatBeijingTimeShort(timestamp * 1000)
}