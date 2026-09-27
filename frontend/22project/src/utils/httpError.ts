/**
 * 把 HTTP / 网络层错误翻成**中文**提示。
 *
 * 为什么要有这个文件：axios 自己抛的 `error.message` 是**英文**的 ——
 *   `Request failed with status code 405`、`Network Error`、`timeout of 180000ms exceeded`。
 * 而前端很多地方是 `'删除失败：' + e.message` 这种拼法，于是界面上就出现
 * 半句中文 + 半句英文；**后端没返回 JSON body 时**（405 / 502 / HTML 错误页）
 * 必然走到这条兜底。现场用户看到 "Request failed with status code 405" 是没有任何用处的。
 *
 * 取文案的优先级（从准到糙）：
 *   ① **后端自己给的文字** —— 裸 JSON 的 `{error}`、兼容层信封的 `{msg}`。
 *      它知道具体是哪一步失败（"模型 xx 不存在""版本号重复"），比任何通用文案都准。
 *   ② **按 HTTP 状态码** 给一句中文（见 STATUS_TEXT）。
 *   ③ **网络层兜底** —— 请求根本没到服务端（超时/连接失败/被取消）。
 *      ⚠️ 这一步绝不把 axios 原文抛给用户：它是英文，而且 `status code` 这种词对现场没意义。
 */
import type { AxiosError } from 'axios';

/** HTTP 状态码 → 中文说明。只列**真的可能出现**的码，别为了凑数把 1xx 也写进去。 */
const STATUS_TEXT: Record<number, string> = {
	400: '请求参数有误',
	401: '登录已失效，请重新登录',
	403: '当前账号没有该操作的权限',
	404: '接口或资源不存在',
	// 405 在本项目几乎总是同一个原因：前端已经是新代码、后端进程还是旧版本（路由没这个方法）。
	// 把"重启后端"直接写进提示里，省掉一轮"这是什么错误"的排查。
	405: '接口不支持这种操作方式（405）：若刚更新过后端代码，请重启后端服务再试',
	406: '服务端无法按要求的格式返回',
	408: '请求超时',
	409: '数据冲突，可能已被别处改动，刷新后再试',
	413: '上传内容太大，超过服务端限制',
	415: '不支持这种数据类型',
	422: '数据校验没通过',
	429: '操作太频繁，请稍后再试',
	500: '服务端内部错误（具体原因看后端控制台的报错）',
	501: '服务端还没实现这个功能',
	502: '网关错误：后端进程可能没起来',
	503: '服务暂时不可用',
	504: '网关超时',
	505: 'HTTP 版本不受支持',
};

/** 后端给的文字（如果有）。识别不出就回空串。 */
function serverText(data: any): string {
	// ⚠️ data 可能是**字符串**：Flask 出错时回的是 HTML 错误页、`abort()` 回的是纯文本。
	//    这种不要往提示里塞（一大段 HTML 会撑爆消息框，也读不懂）。
	if (!data || typeof data !== 'object') return '';
	const text = data.error || data.msg;      // 裸 JSON 用 error；dvadmin 信封用 msg
	if (!text) return '';
	if (Array.isArray(text)) return text.map(String).join('；');   // 少数框架会回数组
	return String(text);
}

/**
 * 生成给用户看的中文错误文案。
 *
 * @param error axios 抛出的错误对象（也可以是任意 Error）。
 */
export function describeHttpError(error: any): string {
	const data = (error as AxiosError)?.response?.data;
	const fromServer = serverText(data);
	if (fromServer) return fromServer;

	const status = (error as AxiosError)?.response?.status;
	if (status) return STATUS_TEXT[status] || `请求失败（HTTP ${status}）`;

	// 走到这里说明请求没能到达服务端拿到响应
	const raw = String(error?.message || '');
	if (/timeout/i.test(raw)) {
		// 这个平台的训练/推理是同步阻塞的，超时最常见的真实原因就是"它还在跑"
		return '请求超时：服务端可能还在训练/推理，稍后到记录里看结果';
	}
	if (/network error|err_network|failed to fetch/i.test(raw)) {
		return '连不上后端服务，请确认后端已启动、端口没被改';
	}
	if (/canceled|aborted/i.test(raw)) return '请求已取消';
	return '请求失败，请稍后重试';
}

/**
 * 这句话里有没有中文。用来判断"这条文案是不是还没被本地化过"。
 *
 * 用途：兼容层 `service.ts` 的错误分支里，已被 switch 覆盖的状态码有中文文案，
 * 没覆盖到的（405 / 409 / 418 / 502…）会留着 axios 的英文原文。
 * 判"有没有中文"而不是列状态码，以后 axios 改文案也不会漏。
 */
export function isLocalized(text: any): boolean {
	return /[\u4e00-\u9fa5]/.test(String(text ?? ''));
}
