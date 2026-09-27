<template>
	<div class="platform-home">
		<el-row :gutter="16">
			<el-col :xs="24" :sm="12" :md="6" v-for="k in kpis" :key="k.label">
				<el-card shadow="never" class="kpi-card">
					<div class="kpi-label">{{ k.label }}</div>
					<div class="kpi-value">{{ k.value }}</div>
					<div class="kpi-hint">{{ k.hint }}</div>
				</el-card>
			</el-col>
		</el-row>

		<el-row :gutter="16" class="mt">
			<el-col :xs="24" :md="12">
				<!-- 原「服务与数据库」卡片 → 改为项目说明文档入口。
				     服务/库的实时状态仍然可见：上面四张 KPI 卡就读自同一个 /health。 -->
				<el-card shadow="never">
					<template #header>
						<span>项目说明文档</span>
						<el-tag size="small" type="info" style="margin-left: 8px">离线可看</el-tag>
					</template>
					<p class="doc-lede">
						一页讲清这套平台：系统架构、三个模型的指标与超参、两套数据集、
						训练 → 产物 → 推理 → 落库 → 展示的完整链路、11 张表、28 条接口、
						登录与注册、启动部署方式，以及当前已知限制。
					</p>
					<div class="doc-jump">
						<el-button link type="primary" @click="openDocs('#arch')">系统架构</el-button>
						<el-button link type="primary" @click="openDocs('#models')">三个模型</el-button>
						<el-button link type="primary" @click="openDocs('#flow')">完整链路</el-button>
						<el-button link type="primary" @click="openDocs('#api')">接口一览</el-button>
						<el-button link type="primary" @click="openDocs('#auth')">登录与会话</el-button>
						<el-button link type="primary" @click="openDocs('#deploy')">启动部署</el-button>
						<el-button link type="primary" @click="openDocs('#faq')">常见问题</el-button>
						<el-button link type="primary" @click="openDocs('#limits')">已知限制</el-button>
					</div>
					<el-button type="primary" class="doc-open" @click="openDocs()">打开说明文档 →</el-button>
				</el-card>
			</el-col>
			<el-col :xs="24" :md="12">
				<el-card shadow="never">
					<template #header>
						<span>快捷入口</span>
						<el-button link type="primary" style="float: right" @click="load">刷新</el-button>
					</template>
					<div class="quick">
						<el-button type="primary" @click="go('/platform/model', 'train')">开始训练</el-button>
						<el-button @click="go('/platform/model', 'predict')">开始推理</el-button>
						<el-button @click="go('/platform/publish')">模型发布</el-button>
						<el-button @click="go('/platform/dataset', 'tabular')">表格数据集</el-button>
						<el-button @click="go('/platform/visual', 'signal')">看原始信号</el-button>
						<el-button @click="go('/platform/visual', 'gallery')">看图库</el-button>
						<el-button @click="go('/platform/system', 'logs')">看训练日志</el-button>
					</div>
				</el-card>
			</el-col>
		</el-row>

		<el-card shadow="never" class="mt">
			<template #header><span>最近训练</span></template>
			<el-table :data="trainings" size="small" empty-text="还没有训练记录">
				<el-table-column prop="TrainingID" label="ID" width="70" />
				<el-table-column prop="ModelName" label="模型" width="110" />
				<el-table-column prop="TrainName" label="训练名" min-width="200" />
				<el-table-column prop="Epochs" label="轮次" width="80" />
				<el-table-column label="准确率" width="110">
					<template #default="{ row }">{{ row.Accuracy != null ? Number(row.Accuracy).toFixed(4) : '—' }}</template>
				</el-table-column>
				<el-table-column label="状态" width="100">
					<template #default="{ row }">
						<el-tag :type="row.Status === '成功' ? 'success' : 'danger'" size="small">{{ row.Status }}</el-tag>
					</template>
				</el-table-column>
				<el-table-column prop="StartedDate" label="开始时间" min-width="150" />
			</el-table>
		</el-card>

		<el-card shadow="never" class="mt">
			<template #header><span>最近推理任务</span></template>
			<el-table :data="tasks" size="small" empty-text="还没有推理任务">
				<el-table-column prop="InferenceTaskID" label="ID" width="70" />
				<el-table-column prop="ModelName" label="模型" width="110" />
				<el-table-column prop="TaskType" label="类型" width="160" />
				<el-table-column prop="TrainingID" label="锚点训练" width="100" />
				<el-table-column prop="Progress" label="进度" width="80" />
				<el-table-column label="状态" width="100">
					<template #default="{ row }">
						<el-tag :type="row.Status === '成功' ? 'success' : 'danger'" size="small">{{ row.Status }}</el-tag>
					</template>
				</el-table-column>
				<el-table-column prop="CompletedDate" label="完成时间" min-width="150" />
			</el-table>
		</el-card>
	</div>
</template>

<script setup lang="ts" name="platformHome">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { platformApi } from '/@/api/platform';

const router = useRouter();
const health = ref<any>({});
const artifacts = ref<any[]>([]);
const trainings = ref<any[]>([]);
const tasks = ref<any[]>([]);
const db = computed(() => health.value.database || {});

const kpis = computed(() => [
	{ label: '模型产物', value: artifacts.value.length, hint: 'data/models 下已落盘的模型数' },
	{ label: '训练次数', value: db.value.counts?.Trainings ?? '—', hint: 'Trainings 表行数' },
	{ label: '推理任务', value: db.value.counts?.InferenceTasks ?? '—', hint: 'InferenceTasks 表行数' },
	{ label: '结果明细', value: db.value.counts?.InferenceResults ?? '—', hint: 'InferenceResults 表行数' },
]);

const go = (path: string, tab?: string) => router.push({ path, query: tab ? { tab } : {} });

/**
 * 打开项目说明文档（新标签页）。
 *
 * ⚠️ 文档是 `frontend/22project/public/docs.html` 这份**静态单文件**：
 *    Vite 会把 public/ 原样拷到 dist/，而后端 web.py 的 SPA 兜底（`/<path:path>`）
 *    也是"真实存在的文件优先"，所以**开发模式与单端口生产都能直接打开**，
 *    不需要后端加路由、也不需要注册菜单。
 *    它自带样式、不引任何 CDN 或外部字体，可以拷到不能上网的实验室机器直接看。
 *
 * ⚠️ 用 `window.location.origin` 拼绝对地址，**不能**用相对路径：
 *    当前地址是 `/platform/home`，`./docs.html` 会被解析成 `/platform/docs.html`（不存在）。
 *    本项目各 .env 都把前端挂在根路径下，所以 origin + /docs.html 是对的；
 *    若将来要部署到子路径，这里得跟着改成对应的 base。
 */
const openDocs = (hash = '') => {
	window.open(`${window.location.origin}/docs.html${hash}`, '_blank', 'noopener');
};

const load = async () => {
	// ⚠️ 这里以前是**裸 await Promise.all**：任一接口 500 / 断网就变成"未处理的 Promise 拒绝"，
	//    页面停在空白、用户一句话都看不到，只能刷新碰运气。加载失败必须说出来。
	try {
		const [h, m, t, k] = await Promise.all([
			platformApi.health(),
			platformApi.models(),
			platformApi.trainings(5),
			platformApi.tasks(5),
		]);
		health.value = h as any;
		artifacts.value = (m as any).artifacts || [];
		trainings.value = (t as any).trainings || [];
		tasks.value = (k as any).tasks || [];
	} catch (e: any) {
		// e.message 已被 platformRequest/httpError 统一成中文（后端文案 → 状态码中文 → 网络层中文）
		ElMessage.error(e?.message || '首页数据加载失败，请确认后端服务已启动后刷新重试');
	}
};

onMounted(load);
</script>

<style scoped lang="scss">
.kpi-card { text-align: left; }
.kpi-label { font-size: 13px; color: var(--el-text-color-secondary); }
.kpi-value { font-size: 28px; font-weight: 600; margin: 4px 0; }
.kpi-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.mt { margin-top: 16px; }
.quick { margin-top: 8px; }
.quick .el-button { margin: 0 8px 8px 0; }
/* ⚠️ 原来这里还有 `.hint` 与 `.tag-gap` 两条规则，是给「快捷入口」卡片下半部分那个
   「已落盘产物」标签列表用的。那块已按需求去掉，两条规则也一并删除（留着就是死样式）。 */
/* ---- 项目说明文档卡片 ---- */
.doc-lede {
	font-size: 13px;
	line-height: 1.8;
	color: var(--el-text-color-regular);
	margin: 0 0 10px;
}
.doc-jump { margin: 0 0 4px; }
.doc-jump .el-button { margin: 0 10px 6px 0; }
.doc-open { margin-top: 6px; }
</style>
