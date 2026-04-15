import request from '@/utils/request'

/**
 * 任务类型
 */
export const JobType = {
  REMINDER: 'reminder',
  COMMAND: 'command',
} as const

export type JobType = (typeof JobType)[keyof typeof JobType]

/**
 * 任务状态
 */
export const JobStatus = {
  ACTIVE: 'active',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  CANCELLED: 'cancelled',
} as const

export type JobStatus = (typeof JobStatus)[keyof typeof JobStatus]

/**
 * 触发器类型
 */
export const TriggerType = {
  CRON: 'cron',
  INTERVAL: 'interval',
  DATE: 'date',
} as const

export type TriggerType = (typeof TriggerType)[keyof typeof TriggerType]

/**
 * 触发器配置基类
 */
export interface BaseTriggerConfig {
  [key: string]: any
}

/**
 * Cron触发器配置
 */
export interface CronTriggerConfig extends BaseTriggerConfig {
  minute?: string
  hour?: string
  day?: string
  month?: string
  day_of_week?: string
}

/**
 * Interval触发器配置
 */
export interface IntervalTriggerConfig extends BaseTriggerConfig {
  seconds?: number
  minutes?: number
  hours?: number
  days?: number
  weeks?: number
}

/**
 * Date触发器配置
 */
export interface DateTriggerConfig extends BaseTriggerConfig {
  run_date?: string
}

export type TriggerConfig = CronTriggerConfig | IntervalTriggerConfig | DateTriggerConfig

/**
 * 任务基础信息
 */
export interface Job {
  job_id: string
  name: string
  job_type: JobType
  status: JobStatus
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  content: string
  session_id?: string
  agent_id?: string
  created_at: string
  updated_at: string
  next_run_time?: string
}

/**
 * 任务执行记录
 */
export interface JobExecution {
  execution_id: string
  executed_at: string
  success: boolean
  result?: string
}

/**
 * 任务详情（包含执行历史）
 */
export interface JobDetail {
  job: Job
  executions: JobExecution[]
}

/**
 * 任务列表响应
 */
export interface JobsResponse {
  jobs: Job[]
  total: number
  skip: number
  limit: number
}

/**
 * 任务执行历史响应
 */
export interface JobExecutionsResponse {
  executions: JobExecution[]
  total: number
  skip: number
  limit: number
}

/**
 * 任务查询参数
 */
export interface JobQueryParams {
  skip?: number
  limit?: number
  status?: JobStatus
  job_type?: JobType
  session_id?: string
  keyword?: string
  order_by?: string
}

/**
 * 任务更新请求
 */
export interface JobUpdateRequest {
  name?: string
  content?: string
}

/**
 * 任务API
 */
export const jobApi = {
  /**
   * 获取任务列表
   */
  async getJobs(params: JobQueryParams = {}): Promise<JobsResponse> {
    return request.get('/job/jobs', {
      params: {
        skip: params.skip ?? 0,
        limit: params.limit ?? 20,
        status: params.status,
        job_type: params.job_type,
        session_id: params.session_id,
        keyword: params.keyword,
        order_by: params.order_by ?? 'created_at desc',
      },
    })
  },

  /**
   * 获取任务详情
   */
  async getJobDetail(jobId: string, executionLimit: number = 10): Promise<JobDetail> {
    return request.get(`/job/${jobId}`, {
      params: { execution_limit: executionLimit },
    })
  },

  /**
   * 获取任务执行历史
   */
  async getJobExecutions(
    jobId: string,
    skip: number = 0,
    limit: number = 50,
    success?: boolean
  ): Promise<JobExecutionsResponse> {
    return request.get(`/job/${jobId}/executions`, {
      params: { skip, limit, success },
    })
  },

  /**
   * 立即执行任务
   */
  async executeJobNow(jobId: string): Promise<void> {
    return request.post(`/job/${jobId}/execute`)
  },

  /**
   * 更新任务
   */
  async updateJob(jobId: string, data: JobUpdateRequest): Promise<void> {
    return request.put(`/job/${jobId}`, data)
  },

  /**
   * 删除任务
   */
  async deleteJob(jobId: string): Promise<void> {
    return request.delete(`/job/${jobId}`)
  },

  /**
   * 暂停任务
   */
  async pauseJob(jobId: string): Promise<void> {
    return request.post(`/job/${jobId}/pause`)
  },

  /**
   * 恢复任务
   */
  async resumeJob(jobId: string): Promise<void> {
    return request.post(`/job/${jobId}/resume`)
  },
}

export default jobApi
