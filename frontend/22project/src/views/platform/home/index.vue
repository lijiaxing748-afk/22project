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
				<el-card shadow="never">
					<template #header><span>服务与数据库</span></template>
					<el-descriptions :column="1" border size="small">
						<el-descriptions-item label="服务状态">
							<el-tag :type="health.service === 'ok' ? 'success' : 'danger'" size="small">{{ health.service || '未知' }}</el-tag>
						</el-descriptions-item>
						<el-descriptions-item label="数据库">{{ db.dialect || '—' }}（{{ db.ok ? '已连接' : '不可用' }}）</el-descriptions-item>
						<el-descriptions-item label="连接目标">{{ db.target || '—' }}</el-descriptions-item>
						<el-descriptions-item label="表行数">
							<el-tag v-for="(v, k) in db.counts || {}" :key="k" size="small" class="tag-gap">{{ k }}: {{ v }}</el-tag>
						</el-descriptions-item>
						<el-descriptions-item label="模型产物">{{ artifacts.length }} 个模型</el-descriptions-item>
						<el-descriptions-item label="出图目录">{{ health.figures?.dir || '—' }}</el-descriptions-item>
					</el-descriptions>
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
					<el-divider />
					<div class="hint">已落盘产物</div>
					<div class="quick">
						<el-tag v-for="a in artifacts" :key="a.model" class="tag-gap" size="small">
							{{ a.model }} · {{ a.metrics?.test_accuracy != null ? Number(a.metrics.test_accuracy).toFixed(4) : '—' }}
						</el-tag>
						<span v-if="!artifacts.length" class="hint">还没有产物，去「模型管理 → 训练」跑一次</span>
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

const load = async () => {
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
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.tag-gap { margin: 0 6px 6px 0; }
</style>
