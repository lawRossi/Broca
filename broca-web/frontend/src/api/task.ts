import request from '@/utils/request'

/**
 * 任务状态
 */
export const TaskStatus = {
  PENDING: 'pending',
  IN_PROGRESS: 'in_progress',
  BLOCKED: 'blocked',
  COMPLETED: 'completed',
} as const

export type TaskStatus = (typeof TaskStatus)[keyof typeof TaskStatus]

/**
 * 任务优先级
 */
export const TaskPriority = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
} as const

export type TaskPriority = (typeof TaskPriority)[keyof typeof TaskPriority]

/**
 * 任务基础信息
 */
export interface Task {
  task_id: string
  name: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  assignee?: string
  parent_id?: string
  session_id?: string
  details?: string
  acceptance_criteria?: string[]
  context_files?: string[]
  context_links?: string[]
  context_notes?: string
  report?: string
  dependencies?: string[]
  created_at: string
  updated_at: string
}

/**
 * 任务评论
 */
export interface TaskComment {
  comment_id: string
  author: string
  content: string
  created_at: string
}

/**
 * 子任务信息
 */
export interface ChildTask {
  task_id: string
  name: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  assignee?: string
  created_at: string
  updated_at: string
}

/**
 * 任务详情（包含评论和子任务）
 */
export interface TaskDetail {
  task: Task
  comments: TaskComment[]
  children: ChildTask[]
}

/**
 * 任务列表响应
 */
export interface TasksResponse {
  tasks: Task[]
  total: number
  skip: number
  limit: number
}

/**
 * 任务评论响应
 */
export interface TaskCommentsResponse {
  comments: TaskComment[]
  total: number
  skip: number
  limit: number
}

/**
 * 子任务响应
 */
export interface TaskChildrenResponse {
  children: ChildTask[]
}

/**
 * 任务查询参数
 */
export interface TaskQueryParams {
  skip?: number
  limit?: number
  status?: TaskStatus
  priority?: TaskPriority
  assignee?: string
  session_id?: string
  parent_id?: string
  keyword?: string
  order_by?: string
}

/**
 * 任务创建请求
 */
export interface TaskCreateRequest {
  name: string
  description: string
  priority?: TaskPriority
  parent_id?: string
  assignee?: string
  dependencies?: string[]
  details?: string
  context_files?: string[]
  context_links?: string[]
  context_notes?: string
  acceptance_criteria?: string[]
  report?: string
  session_id?: string
}

/**
 * 任务更新请求
 */
export interface TaskUpdateRequest {
  name?: string
  description?: string
  status?: TaskStatus
  priority?: TaskPriority
  assignee?: string
  dependencies?: string[]
  details?: string
  context_files?: string[]
  context_links?: string[]
  context_notes?: string
  acceptance_criteria?: string[]
  report?: string
}

/**
 * 评论创建请求
 */
export interface CommentCreateRequest {
  author: string
  content: string
}

/**
 * 任务搜索参数
 */
export interface TaskSearchParams {
  query: string
  session_id?: string
  skip?: number
  limit?: number
}

/**
 * 任务API
 */
export const taskApi = {
  /**
   * 获取任务列表
   */
  async getTasks(params: TaskQueryParams = {}): Promise<TasksResponse> {
    return request.get('/task/tasks', {
      params: {
        skip: params.skip ?? 0,
        limit: params.limit ?? 20,
        status: params.status,
        priority: params.priority,
        assignee: params.assignee,
        session_id: params.session_id,
        parent_id: params.parent_id,
        keyword: params.keyword,
        order_by: params.order_by ?? 'created_at desc',
      },
    })
  },

  /**
   * 获取任务详情
   */
  async getTaskDetail(taskId: string, includeComments: boolean = true): Promise<TaskDetail> {
    return request.get(`/task/${taskId}`, {
      params: { include_comments: includeComments },
    })
  },

  /**
   * 创建任务
   */
  async createTask(data: TaskCreateRequest): Promise<{ task: Task }> {
    return request.post('/task/', data)
  },

  /**
   * 更新任务
   */
  async updateTask(taskId: string, data: TaskUpdateRequest): Promise<void> {
    return request.put(`/task/${taskId}`, data)
  },

  /**
   * 删除任务
   */
  async deleteTask(taskId: string): Promise<void> {
    return request.delete(`/task/${taskId}`)
  },

  /**
   * 获取任务评论
   */
  async getTaskComments(taskId: string, skip: number = 0, limit: number = 50): Promise<TaskCommentsResponse> {
    return request.get(`/task/${taskId}/comments`, {
      params: { skip, limit },
    })
  },

  /**
   * 添加任务评论
   */
  async addTaskComment(taskId: string, data: CommentCreateRequest): Promise<{ comment: TaskComment }> {
    return request.post(`/task/${taskId}/comments`, data)
  },

  /**
   * 获取子任务
   */
  async getTaskChildren(taskId: string): Promise<TaskChildrenResponse> {
    return request.get(`/task/${taskId}/children`)
  },

  /**
   * 搜索任务
   */
  async searchTasks(params: TaskSearchParams): Promise<TasksResponse> {
    return request.get('/task/search', {
      params: {
        query: params.query,
        session_id: params.session_id,
        skip: params.skip ?? 0,
        limit: params.limit ?? 20,
      },
    })
  },
}

export default taskApi
