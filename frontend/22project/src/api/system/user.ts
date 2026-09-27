/**
 * 已登录状态下的「个人」相关接口（dvadmin 兼容层，返回 `{code,data,msg}` 信封）。
 *
 * ⚠️ 这两个接口都只动**自己**，不接受用户 ID 参数：
 *   · `update_user_info` 后端会**显式丢弃 role** 字段 —— 请求体是客户端可控的，
 *     原样透传给 update_user() 就等于任何登录用户都能把自己改成 admin。
 *   · `change_password` 只改当前令牌对应的那个人，改完 TokenVersion +1（旧令牌作废）。
 *
 * 管理员改**别人**的口令是另一条路：`/api/system/user/<id>/reset_password/`，
 * 在「用户管理」页里，需要 user:manage 权限。
 */
import { request } from '/@/utils/service';

export interface ProfilePayload {
	name?: string;
	email?: string;
	mobile?: string;
}

/** 改个人资料（显示名 / 邮箱 / 手机）。⚠️ 不改角色、不改密码。 */
export function updateUserInfo(data: ProfilePayload) {
	return request({
		url: '/api/system/user/update_user_info/',
		method: 'post',
		data,
	});
}

export interface ChangePasswordPayload {
	old_password: string;
	password: string;
	password_regain: string;
}

/**
 * 改自己的密码。
 *
 * ⚠️ 后端会返回一个**新令牌**（`data.access`），调用方**必须**把它写回 Session：
 *    改密会让 TokenVersion +1、旧令牌立即失效，不换令牌的话下一次请求就是
 *    "登录已失效"，人会被弹回登录页——等于白改一次。
 */
export function changePassword(data: ChangePasswordPayload) {
	return request({
		url: '/api/system/user/change_password/',
		method: 'post',
		data,
	});
}
