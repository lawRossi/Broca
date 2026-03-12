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

// API functions
export const listFiles = async (path: string = '.'): Promise<FileListResponse> => {
  const response = await fetch(`/api/files?path=${encodeURIComponent(path)}`)
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  const data = await response.json()
  
  if (data.code !== 200) {
    throw new Error(data.msg || 'Failed to load files')
  }
  
  return data.data
}

export const getFileInfo = async (path: string): Promise<FileInfo> => {
  const response = await fetch(`/api/files/info?path=${encodeURIComponent(path)}`)
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  const data = await response.json()
  
  if (data.code !== 200) {
    throw new Error(data.msg || 'Failed to get file info')
  }
  
  return data.data
}

export const previewFile = async (path: string, maxLines: number = 100): Promise<FilePreview> => {
  const response = await fetch(`/api/files/preview?path=${encodeURIComponent(path)}&max_lines=${maxLines}`)
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  const data = await response.json()
  
  if (data.code !== 200) {
    throw new Error(data.msg || 'Failed to preview file')
  }
  
  return data.data
}