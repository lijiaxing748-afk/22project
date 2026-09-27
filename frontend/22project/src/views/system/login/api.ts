import { request } from "/@/utils/service";

export function getCaptcha() {
    return request({
        url: '/api/captcha/',
        method: 'get',
    });
}
export function login(params: object) {
    return request({
        url: '/api/login/',
        method: 'post',
        data: params
    });
}

/**
 * 自助注册。
 *
 * ⚠️ 后端**刻意不在这里签发令牌**：注册成功后由前端拿同一份凭据再走一次 login()。
 *    这样"登录成功之后要做什么"（初始化动态路由/字典/按钮权限）只有一条路径。
 * ⚠️ 后端会把角色**强制成"普通用户"**，前端传 role 也会被忽略（防止注册即提权）。
 *    是否开放注册由 `GET /api/init/settings/` 的 `base.register_state` 决定，
 *    关闭时登录页不显示「注册」页签。
 */
export function register(params: object) {
    return request({
        url: '/api/register/',
        method: 'post',
        data: params
    });
}

export function loginChangePwd(data: object) {
    return request({
        url: '/api/system/user/login_change_password/',
        method: 'post',
        data: data
    });
}

export function getUserInfo() {
    return request({
        url: '/api/system/user/user_info/',
        method: 'get',
    });
}

export function getBackends() {
    return request({
        url: '/api/dvadmin3_social_oauth2/backend/get_login_backend/',
        method: 'get',
    });
}