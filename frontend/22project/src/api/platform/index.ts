/**
 * 平台业务接口（对接 testRestfulProject/model_service 的 Flask 服务）
 *
 * 说明：本工程的 VITE_API_URL 指向 Flask（http://127.0.0.1:5000），
 *   - /api/**  是 dvadmin 兼容接口（登录、用户信息、动态菜单…）
 *   - 其余路径是 model_service 的业务接口（裸 JSON，不带 {code,data,msg} 信封，
 *     utils/request.ts 的拦截器会直接放行）
 */
import platformRequest from '/@/utils/platformRequest';
const request = platformRequest as any;

const q = (params: Record<string, any>) =>
	Object.entries(params)
		.filter(([, v]) => v !== undefined && v !== null && v !== '')
		.map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
		.join('&');

export const platformApi = {
	// ---------- 概览 ----------
	health: () => request({ url: '/health', method: 'get' }),
	apiIndex: () => request({ url: '/api', method: 'get' }),
	system: () => request({ url: '/system', method: 'get' }),

	// ---------- 模型 ----------
	models: () => request({ url: '/models', method: 'get' }),
	artifact: (name: string) => request({ url: `/models/${encodeURIComponent(name)}`, method: 'get' }),
	// 增删改查（Models 表登记行）
	createModel: (data: any) => request({ url: '/models', method: 'post', data }),
	// 上传模型文件夹（权重 + 可选 scaler.npz / meta.json），落盘到 data/models/<名>/
	// 一个模型只有一个产物：同名再上传会直接替换旧产物（后端在 warnings 里说明）
	uploadModel: (form: FormData) =>
		request({ url: '/models/upload', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' } }),
	updateModel: (name: string, data: any) =>
		request({ url: `/models/${encodeURIComponent(name)}`, method: 'put', data }),
	modelReferences: (name: string) =>
		request({ url: `/models/${encodeURIComponent(name)}/references`, method: 'get' }),
	// 模型档案：登记信息 + 产物参数(meta) + 最近训练 + 引用统计，一次拿全
	modelOverview: (name: string) =>
		request({ url: `/models/${encodeURIComponent(name)}/overview`, method: 'get' }),
	deleteModelRecord: (name: string, force = false) =>
		request({ url: `/models/${encodeURIComponent(name)}?scope=record${force ? '&force=true' : ''}`, method: 'delete' }),
	// 删除该模型的产物文件（权重/scaler/meta，不动库表登记）；没有版本号，删的就是唯一那个产物
	deleteArtifact: (name: string) =>
		request({ url: `/models/${encodeURIComponent(name)}?scope=artifact`, method: 'delete' }),

	// ---------- 模型发布（导出下载）----------
	// 全平台发布汇总（「模型发布」独立页面用）：按模型分组的发布流水 + 磁盘包
	exportOverview: () => request({ url: '/exports', method: 'get' }),
	// 发布历史：磁盘上的 zip（packages）+ 库里的发布流水（deployments）
	exports: (name: string) => request({ url: `/models/${encodeURIComponent(name)}/exports`, method: 'get' }),
	// 打包发布：生成 zip 并登记 ModelDeployments，返回 download_url
	// body 可选：{ training_id, version, description, deployed_by }
	exportModel: (name: string, data: any = {}) =>
		request({ url: `/models/${encodeURIComponent(name)}/exports`, method: 'post', data }),
	// 看某个包里有什么（列 zip 条目，不解压）
	inspectExport: (name: string, pkg: string) =>
		request({ url: `/models/${encodeURIComponent(name)}/exports/${encodeURIComponent(pkg)}/inspect`, method: 'get' }),
	// 删除某个发布包（只删磁盘文件，库记录标成「已删除」留痕）
	deleteExport: (name: string, pkg: string) =>
		request({ url: `/models/${encodeURIComponent(name)}/exports/${encodeURIComponent(pkg)}`, method: 'delete' }),

	train: (data: any) => request({ url: '/train', method: 'post', data }),
	trainings: (limit = 20) => request({ url: `/trainings?limit=${limit}`, method: 'get' }),

	// ---------- 推理 ----------
	predict: (data: any) => request({ url: '/predict', method: 'post', data }),
	tasks: (limit = 20) => request({ url: `/inference-tasks?limit=${limit}`, method: 'get' }),
	taskDetail: (id: number) => request({ url: `/inference-tasks/${id}`, method: 'get' }),

	// ---------- 数据集 ----------
	datasets: () => request({ url: '/datasets', method: 'get' }),
	datasetDb: () => request({ url: '/datasets/db', method: 'get' }),
	registerDataset: (data: any) => request({ url: '/datasets/db', method: 'post', data }),
	// 原先这里还声明了 updateDataset(id, data) / deleteDataset(id, force)，对应后端的
	// PUT/DELETE /datasets/db/<id>。两者从来没有被任何页面调用过，后端那组路由也已删除，
	// 留着只会让人以为"登记信息可以改/可以删"。要改登记就重新 registerDataset（幂等）。
	tablePreview: (path: string, rows = 20, column = '') =>
		request({ url: `/datasets/table?${q({ path, rows, column })}`, method: 'get' }),
	signal: (params: { dataset: string; file: string; column?: string; points?: number; start?: number }) =>
		request({ url: `/datasets/signal?${q(params)}`, method: 'get' }),
	upload: (form: FormData) =>
		request({ url: '/datasets/upload', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' } }),

	// ---------- 图 ----------
	figures: (limit = 300) => request({ url: `/figures?limit=${limit}`, method: 'get' }),

	// ---------- 日志 / 维护 ----------
	logs: () => request({ url: '/system/logs', method: 'get' }),
	logFile: (name: string, tail = 300) =>
		request({ url: `/system/logs/${encodeURIComponent(name)}?tail=${tail}`, method: 'get' }),
	maintenance: (target: string) => request({ url: '/system/maintenance', method: 'post', data: { target } }),
};

/** 图/文件的完整地址（VITE_API_URL 可能是绝对地址，也可能是 /api 这样的前缀） */
export function fileUrl(path: string) {
	if (!path) return '';
	if (/^https?:\/\//.test(path)) return path;
	const base = (import.meta.env.VITE_API_URL as string) || '';
	return `${base.replace(/\/$/, '')}${path}`;
}
