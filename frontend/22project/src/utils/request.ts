import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Session } from '/@/utils/storage';
import qs from 'qs';

// 配置新建一个 axios 实例
const service: AxiosInstance = axios.create({
	baseURL: import.meta.env.VITE_API_URL,
	timeout: 50000,
	headers: { 'Content-Type': 'application/json' },
	paramsSerializer: {
		serialize(params) {
			return qs.stringify(params, { allowDots: true });
		},
	},
});

// 添加请求拦截器
service.interceptors.request.use(
	(config: AxiosRequestConfig) => {
		// 在发送请求之前做些什么 token
		if (Session.get('token')) {
			config.headers!['Authorization'] = `${Session.get('token')}`;
		}
		return config;
	},
	(error) => {
		// 对请求错误做些什么
		return Promise.reject(error);
	}
);

// 添加响应拦截器
service.interceptors.response.use(
	(response) => {
		// 对响应数据做点什么
		const res = response.data;
		if (res.code && res.code !== 0) {
			// `token` 过期或者账号已在别处登录
			if (res.code === 401 || res.code === 4001) {
				Session.clear(); // 清除浏览器全部临时缓存
				window.location.href = '/'; // 去登录页
				ElMessageBox.alert('你已被登出，请重新登录', '提示', {})
					.then(() => {})
					.catch(() => {});
			}
			return Promise.reject(service.interceptors.response);
		} else {
			return response.data;
		}
	},
	(error) => {
		// 对响应错误做点什么
		// ⚠️ 这一段是"鉴权改造"专门要处理的：受保护的业务接口（/train、/predict、
		//    /models 的写操作…）在未登录/无权限时返回的是**裸 JSON + 真实 HTTP 状态码**
		//    （401/403），而不是 dvadmin 那套 {code,data,msg} 信封。上面那个
		//    `if (res.code …)` 分支对它们**永远不会触发**，所以必须在这里接。
		//    不加这段的后果是：令牌过期后点"训练"，用户只看到一句 "Unauthorized"，
		//    不知道自己该重新登录，也不会被领回登录页。
		const status = error.response?.status;
		const data = error.response?.data;
		if (status === 401) {
			// 未登录 / 令牌过期 → 清缓存回登录页（与 code=401 的处理保持一致）
			Session.clear();
			ElMessageBox.alert(data?.error || '登录已失效，请重新登录', '提示', {})
				.then(() => { window.location.href = '/'; })
				.catch(() => { window.location.href = '/'; });
		} else if (status === 403) {
			// 已登录但权限不够：**不要**把人踢回登录页——他是有效用户，
			// 只是这个操作需要更高角色。只提示，页面留在原地。
			ElMessage.error(data?.hint || data?.error || '当前账号没有该操作权限');
		} else if (error.message.indexOf('timeout') != -1) {
			ElMessage.error('网络超时');
		} else if (error.message == 'Network Error') {
			ElMessage.error('网络连接错误');
		} else {
			// 优先显示后端给的具体原因（"xx 不存在""版本号重复"…），
			// 拿不到再退回状态文本——原来只显示 statusText，信息量太少
			const detail = data?.error || data?.msg || error.response?.statusText;
			ElMessage.error(detail || '接口路径找不到');
		}
		return Promise.reject(error);
	}
);

// 导出 axios 实例
export default service;
