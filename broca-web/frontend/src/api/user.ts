import request from '@/utils/request'

export interface LoginForm {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
}

export interface UserInfo {
  id: string
  name: string
  avatar: string
}

export const userApi = {
  addUserInfo(data: UserInfo): Promise<UserInfo> {
    return request.post('/user/add_info', data)
  },

  getUserInfo(): Promise<UserInfo> {
    return request.get('/user/info')
  },

  login(data: LoginForm): Promise<LoginResponse> {
    return request.post('/user/login', data)
  },

  logout(): Promise<void> {
    return request.post('/user/logout')
  },
}
