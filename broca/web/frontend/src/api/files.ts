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

export const filesApi = {
  /**
   * 获取文件列表
   */
  async listFiles(path: string = '.'): Promise<FileListResponse> {
    return request.get('/files', {
      params: { path }
    })
  },

  /**
   * 获取文件信息
   */
  async getFileInfo(path: string): Promise<FileInfo> {
    return request.get('/files/info', {
      params: { path }
    })
  },

  /**
   * 预览文件内容
   */
  async previewFile(path: string): Promise<FilePreview> {
    return request.get('/files/preview', {
      params: { path }
    })
  },

  /**
   * 编辑文件
   */
  async editFile(path: string, content: string): Promise<FileEditResponse> {
    return request.put('/files/edit', { content }, {
      params: { path }
    })
  }
}

export default filesApi