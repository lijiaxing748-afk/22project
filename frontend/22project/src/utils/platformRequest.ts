/**
 * 平台业务接口专用的 axios 实例
 *
 * 为什么不用 /@/utils/service：
 *   那个实例是给 dvadmin 的 Django 接口用的，响应拦截器会校验 `{code, data, msg}` 信封，
 *   遇到裸 JSON 会抛 `非标准返回：[object Object]` 并把请求 reject —— 我们的
 *   model_service（Flask）业务接口返回的就是裸 JSON（/models、/trainings、/predict…），
 *   所以 5 个页面全部报错。这里单独建一个实例：直接返回 response.data，不做信封校验。
 *
 * 与框架保持一致的地方：baseURL 同样取 VITE_API_URL；token 同样放 Authorization 头。
 * ⚠️ 两个实例的 Authorization 头都必须用标准的 `Bearer <token>`。
 *    之前这里发**裸值**、service.ts 发 `JWT `、后端认 `Bearer `，三家各说各话：
 *    dvadmin 那几个接口（登录、user_info）全挂，而平台业务接口恰好蒙对了。
 *    现在统一成 Bearer，别再各自发挥。
 */
import axios from 'axios';
import { Session } from '/@/utils/storage';

const platformRequest = axios.create({
	baseURL: import.meta.env.VITE_API_URL as string,
	timeout: 180000, // 训练/推理是同步阻塞的，给足时间
	headers: { 'Content-Type': 'application/json' },
});

platformRequest.interceptors.request.use((config) => {
	const token = Session.get('token');
	// 统一成标准 Bearer 格式（见文件头说明）
	if (token) config.headers!['Authorization'] = `Bearer ${token}`;
	return config;
});

platformRequest.interceptors.response.use(
	(response) => response.data, // 裸 JSON 直接返回，不校验信封
	(error) => {
		const data = error?.response?.data;
		const status = error?.response?.status;
		const msg = (data && (data.error || data.msg)) || error?.message || '请求失败';
		// ⚠️ 鉴权失败要在这里**统一处理**，不能只把错误往后抛：
		//    令牌过期(401)时如果页面各自处理，就会出现"有的地方弹提示、有的地方
		//    静默失败"，用户不知道该重新登录。清缓存 + 跳登录页只在 401 时做。
		//    403（已登录但权限不够）**不跳登录页**——页面得留着，否则操作员点一下
		//    "训练"就被弹出去，体验很莫名。提示交给调用方或下面这行。
		if (status === 401) {
			Session.clear();
			window.location.href = '/';
		}
		const err = new Error(msg);
		(err as any).payload = data;
		(err as any).status = status;
		return Promise.reject(err);
	}
);

export default platformRequest;
