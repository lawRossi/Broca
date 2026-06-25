import request from '@/utils/request'

export interface LoginForm {
  username: string
  password: string
}

export interface AuthResult {
  token: string
  user_id: string
  username: string
}

export interface UserInfo {
  id: string
  name: string
  avatar: string
}

export const userApi = {
  /** 登录 */
  login(data: LoginForm): Promise<AuthResult> {
    return request.post('/auth/login', data)
  },

  /** 获取用户信息 */
  getUserInfo(): Promise<UserInfo> {
    return request.get('/user/info')
  },

  /** 添加用户信息 */
  addUserInfo(data: UserInfo): Promise<UserInfo> {
    return request.post('/user/add_info', data)
  },

    /** 本地自动登录（仅对本机部署生效，静默模式） */
  localLogin(): Promise<AuthResult> {
    return request.post('/auth/local-login', {}, { silent: true } as any)
  },
}
