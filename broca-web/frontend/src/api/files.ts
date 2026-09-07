import request from '@/utils/request'

export interface FileItem {
  name: string
  path: string
  is_dir: boolean
  size?: number
  modified_time: number
  permissions: string
  readable: boolean
}

export interface FileListResponse {
  current_path: string
  parent_path?: string
  files: FileItem[]
  total: number
}

export interface FileInfo {
  name: string
  path: string
  is_dir: boolean
  size?: number
  modified_time: number
  created_time: number
  accessed_time: number
  permissions: string
  readable: boolean
  writable: boolean
  executable: boolean
  inode: number
  device: number
  hard_links: number
  uid: number
  gid: number
}

export interface FilePreview {
  path: string
  size: number
  preview?: string
  message?: string
  truncated: boolean
  total_lines?: number
}

export interface FileEditResponse {
  path: string
  size: number
  modified_time: number
  backup_created: boolean
  backup_path?: string
}

export interface FileCompleteItem {
  name: string
  path: string
  is_dir: boolean
}

export interface FileCompleteResponse {
  base: string
  prefix: string
  completions: FileCompleteItem[]
  total: number
  truncated?: boolean
}

export const filesApi = {
  /**
   * 获取文件列表
   */
  async listFiles(path: string = '.'): Promise<FileListResponse> {
    return request.get('/files', {
      params: { path },
    })
  },

  /**
   * 文件路径补全（供 ChatInput 输入 # 触发）
   * @param base 补全根目录（通常为会话 workspace）；为空则后端回退 cwd
   * @param prefix 相对 base 的路径前缀，如 "src/comp"、"src/"、""（空串 = 根目录）
   */
  async completeFiles(base: string, prefix: string): Promise<FileCompleteResponse> {
    return request.get('/files/complete', {
      params: { base, prefix },
    })
  },

  /**
   * 获取文件信息
   */
  async getFileInfo(path: string): Promise<FileInfo> {
    return request.get('/files/info', {
      params: { path },
    })
  },

  /**
   * 预览文件内容
   */
  async previewFile(path: string): Promise<FilePreview> {
    return request.get('/files/preview', {
      params: { path },
    })
  },

  /**
   * 编辑文件
   */
  async editFile(path: string, content: string): Promise<FileEditResponse> {
    return request.put(
      '/files/edit',
      { content },
      {
        params: { path },
      }
    )
  },

  /**
   * 获取用户的home目录
   */
  async getHomeDirectory(): Promise<{ home_dir: string }> {
    return request.get('/files/home')
  },
}

export default filesApi
