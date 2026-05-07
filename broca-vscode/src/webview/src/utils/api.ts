/**
 * API client for task/job management.
 * Routes requests through the VSCode extension host via postMessage.
 * Follows the same pattern as existing chat API calls (loadHistory, fetchRunnerStatus, etc.)
 */

import { postMessage, onMessage } from '../api/vscode'

// Generic request-response helper using specific message types
interface PendingRequest {
  resolve: (data: any) => void
  reject: (err: Error) => void
}

const pendingMap = new Map<string, PendingRequest>()
let requestCounter = 0

// Response types that contain task/job data
const RESPONSE_TYPES = new Set([
  'tasks', 'taskDetail', 'taskCreated', 'taskUpdated', 'taskDeleted', 'taskCommentAdded',
  'jobs', 'jobDetail', 'jobExecuted', 'jobPaused', 'jobResumed', 'jobDeleted',
])

let listenerInitialized = false

function initListener() {
  if (listenerInitialized) return
  listenerInitialized = true

  onMessage((data: any) => {
    if (!data || !data.type) return

    // Handle task/job response types
    if (RESPONSE_TYPES.has(data.type)) {
      const pending = pendingMap.get(data.type)
      if (pending) {
        pendingMap.delete(data.type)
        pending.resolve(data.payload)
      }
    }
  })
}

function sendRequest(requestType: string, responseType: string, payload: any): Promise<any> {
  initListener()

  return new Promise((resolve, reject) => {
    // Set timeout
    const timeout = setTimeout(() => {
      if (pendingMap.has(responseType)) {
        pendingMap.delete(responseType)
        reject(new Error(`请求超时 (${requestType})`))
      }
    }, 15000)

    pendingMap.set(responseType, {
      resolve: (data: any) => {
        clearTimeout(timeout)
        resolve(data)
      },
      reject: (err: Error) => {
        clearTimeout(timeout)
        reject(err)
      },
    })

    postMessage({ type: requestType, payload })
  })
}

// ==================== Task API ====================

export const taskApi = {
  getTasks(params: {
    skip?: number; limit?: number; status?: string; priority?: string; keyword?: string; session_id?: string
  } = {}) {
    return sendRequest('fetchTasks', 'tasks', {
      skip: params.skip ?? 0,
      limit: params.limit ?? 50,
      status: params.status,
      priority: params.priority,
      keyword: params.keyword,
      session_id: params.session_id,
    })
  },

  getTaskDetail(taskId: string) {
    return sendRequest('fetchTaskDetail', 'taskDetail', { taskId })
  },

  createTask(data: any) {
    return sendRequest('createTask', 'taskCreated', data)
  },

  updateTask(taskId: string, data: any) {
    return sendRequest('updateTask', 'taskUpdated', { taskId, data })
  },

  deleteTask(taskId: string) {
    return sendRequest('deleteTask', 'taskDeleted', { taskId })
  },

  addComment(taskId: string, data: { author: string; content: string }) {
    return sendRequest('addTaskComment', 'taskCommentAdded', { taskId, ...data })
  },
}

// ==================== Job API ====================

export const jobApi = {
  getJobs(params: {
    skip?: number; limit?: number; status?: string; job_type?: string; keyword?: string; session_id?: string
  } = {}) {
    return sendRequest('fetchJobs', 'jobs', {
      skip: params.skip ?? 0,
      limit: params.limit ?? 50,
      status: params.status,
      job_type: params.job_type,
      keyword: params.keyword,
      session_id: params.session_id,
    })
  },

  getJobDetail(jobId: string) {
    return sendRequest('fetchJobDetail', 'jobDetail', { jobId })
  },

  executeJob(jobId: string) {
    return sendRequest('executeJob', 'jobExecuted', { jobId })
  },

  pauseJob(jobId: string) {
    return sendRequest('pauseJob', 'jobPaused', { jobId })
  },

  resumeJob(jobId: string) {
    return sendRequest('resumeJob', 'jobResumed', { jobId })
  },

  deleteJob(jobId: string) {
    return sendRequest('deleteJob', 'jobDeleted', { jobId })
  },
}
