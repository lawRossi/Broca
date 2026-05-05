/**
 * Direct API client for task/job management.
 * Uses fetch() to call the backend directly since CSP allows http://localhost:* and https:.
 */

import { getInitialData } from '../api/vscode'

function getBaseConfig() {
  const data = getInitialData()
  if (!data) throw new Error('No initial data available')
  return {
    baseUrl: `${data.serverUrl}/api`,
    token: data.token,
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: any,
  params?: Record<string, any>
): Promise<T> {
  const { baseUrl, token } = getBaseConfig()

  const url = new URL(`${baseUrl}${path}`)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const fullUrl = url.toString()
  console.log(`[API] ${method} ${fullUrl}`)

  const response = await fetch(fullUrl, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    console.error(`[API] HTTP ${response.status} for ${method} ${path}:`, text.substring(0, 200))
    throw new Error(`Request failed with status code ${response.status}`)
  }

  const json = await response.json()

  // Handle wrapped response { code, data, msg }
  if (json && typeof json === 'object' && 'code' in json) {
    if (json.code === 200) {
      return json.data as T
    } else {
      throw new Error(json.msg || `Request failed with code ${json.code}`)
    }
  }

  return json as T
}

// ==================== Task API ====================

export interface TaskQueryParams {
  skip?: number
  limit?: number
  status?: string
  priority?: string
  assignee?: string
  session_id?: string
  parent_id?: string
  keyword?: string
  order_by?: string
}

export const taskApi = {
  getTasks(params: TaskQueryParams = {}) {
    return request<any>('GET', '/task/tasks', undefined, {
      skip: params.skip ?? 0,
      limit: params.limit ?? 50,
      status: params.status,
      priority: params.priority,
      assignee: params.assignee,
      session_id: params.session_id,
      parent_id: params.parent_id,
      keyword: params.keyword,
      order_by: params.order_by ?? 'created_at desc',
    })
  },

  getTaskDetail(taskId: string) {
    return request<any>('GET', `/task/${taskId}`, undefined, { include_comments: true })
  },

  createTask(data: any) {
    return request<any>('POST', '/task/', data)
  },

  updateTask(taskId: string, data: any) {
    return request<any>('PUT', `/task/${taskId}`, data)
  },

  deleteTask(taskId: string) {
    return request<any>('DELETE', `/task/${taskId}`)
  },

  addComment(taskId: string, data: { author: string; content: string }) {
    return request<any>('POST', `/task/${taskId}/comments`, data)
  },
}

// ==================== Job API ====================

export interface JobQueryParams {
  skip?: number
  limit?: number
  status?: string
  job_type?: string
  session_id?: string
  keyword?: string
  order_by?: string
}

export const jobApi = {
  getJobs(params: JobQueryParams = {}) {
    return request<any>('GET', '/job/jobs', undefined, {
      skip: params.skip ?? 0,
      limit: params.limit ?? 50,
      status: params.status,
      job_type: params.job_type,
      session_id: params.session_id,
      keyword: params.keyword,
      order_by: params.order_by ?? 'created_at desc',
    })
  },

  getJobDetail(jobId: string) {
    return request<any>('GET', `/job/${jobId}`, undefined, { execution_limit: 50 })
  },

  executeJob(jobId: string) {
    return request<any>('POST', `/job/${jobId}/execute`)
  },

  pauseJob(jobId: string) {
    return request<any>('POST', `/job/${jobId}/pause`)
  },

  resumeJob(jobId: string) {
    return request<any>('POST', `/job/${jobId}/resume`)
  },

  deleteJob(jobId: string) {
    return request<any>('DELETE', `/job/${jobId}`)
  },
}
