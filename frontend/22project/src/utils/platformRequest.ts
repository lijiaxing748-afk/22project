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
import { describeHttpError, isSessionExpiredText } from '/@/utils/httpError';
import { forceRelogin } from '/@/utils/relogin';

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
	(response) => {
		const data = response.data;
		// ⚠️ 平台业务接口回裸 JSON，但**有一部分接口走 dvadmin 兼容层的 `{code,data,msg}` 信封**，
		//    而那个信封**失败也回 HTTP 200**：令牌无效时这 6 个接口（/api/system/user/、/role/、
		//    /user/create/、/user/<id>/、/reset_password/、/operation_log/）回的是
		//    `200 + {"code":4000,"msg":"登录已失效，请重新登录"}`（见 dvadmin.py，实测复现）。
		//    只看 HTTP 状态码，这里就会把它当成**成功数据**交给页面 ——
		//    页面只显示一行红字，令牌不清、也不跳登录页，用户卡在"已失效却仍显示在线"的界面里。
		//    所以信封里的"登录已失效"必须与 401 同样收尾。
		// ⚠️ 只在**确实是鉴权失效**时才动令牌：code=4000 同时被"没有查看用户列表的权限"
		//    这类业务拒绝复用，那些必须留在原页（按文案区分，见 httpError.isSessionExpiredText）。
		if (data && typeof data.code === 'number' && data.code !== 2000 && isSessionExpiredText(data.msg)) {
			const text = String(data.msg || '登录已失效，请重新登录');
			forceRelogin(text);
			const expired = new Error(text);
			(expired as any).payload = data;
			(expired as any).status = response.status;
			return Promise.reject(expired);
		}
		// 其余一律原样返回：**不解包**。调用方（如 user/index.vue）自己读 `.data` / `.code`，
		// 在这里偷偷解包会让那些页面全部读空，而且它们自己判断权限失败的分支也会失效。
		return data;
	},
	(error) => {
		const data = error?.response?.data;
		const status = error?.response?.status;
		// ⚠️ 这里**不要**再用 `error?.message`：axios 的原文是英文
		//    （"Request failed with status code 405"、"Network Error"），而后端没回 JSON body 时
		//    （405 / 502 / HTML 错误页）必然走到它，界面上就会冒出英文提示。
		//    统一交给 describeHttpError：后端文字 → 状态码中文 → 网络层中文，见其文件头。
		const msg = describeHttpError(error);
		// ⚠️ 鉴权失败在这里**统一处理**，不能只把错误往后抛：
		//    令牌过期(401)时如果页面各自处理，就会出现"有的地方弹提示、有的地方静默失败"。
		//    ⚠️ 以前这里是**静默**清令牌 + 跳转 —— 用户被踢回登录页却不知道发生了什么，
		//       现在改走 forceRelogin（弹一句中文 + 清令牌 + 回登录页，两个实例共用一份实现）。
		//    403（已登录但权限不够）**不跳登录页**——页面得留着，否则操作员点一下
		//    "训练"就被弹出去，体验很莫名。提示交给调用方或下面这行。
		if (status === 401) {
			forceRelogin(msg || '登录已失效，请重新登录');
		}
		const err = new Error(msg);
		(err as any).payload = data;
		(err as any).status = status;
		// 原始 axios 错误留在 cause 上：提示是给用户的中文，排查时还能在控制台看到英文原文
		(err as any).cause = error;
		return Promise.reject(err);
	}
);

export default platformRequest;
