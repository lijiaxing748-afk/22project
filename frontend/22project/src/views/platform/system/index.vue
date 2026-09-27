<template>
	<el-tabs v-model="tab" class="platform-page">
		<!-- ============ 运行信息 ============ -->
		<el-tab-pane label="运行信息" name="runtime">
			<el-row :gutter="16">
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>运行环境</span><el-button link type="primary" style="float: right" @click="loadSystem">刷新</el-button></template>
						<el-descriptions :column="1" border size="small">
							<el-descriptions-item label="Python">{{ info.runtime?.python }}</el-descriptions-item>
							<el-descriptions-item label="解释器">{{ info.runtime?.executable }}</el-descriptions-item>
							<el-descriptions-item label="平台">{{ info.runtime?.platform }}</el-descriptions-item>
						</el-descriptions>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>路径与占用</span></template>
						<el-descriptions :column="1" border size="small">
							<el-descriptions-item label="项目根">{{ info.paths?.project_dir }}</el-descriptions-item>
							<el-descriptions-item label="模型产物">{{ info.paths?.model_dir }}</el-descriptions-item>
							<el-descriptions-item label="出图目录">{{ info.figures?.dir }}（{{ info.figures?.count }} 张 / {{ info.figures?.total_kb }} KB）</el-descriptions-item>
							<el-descriptions-item label="日志目录">{{ info.logs?.dir }}（{{ info.logs?.count }} 个 / {{ info.logs?.total_kb }} KB）</el-descriptions-item>
							<el-descriptions-item label="数据库">{{ info.database?.dialect }}（{{ info.database?.ok ? '连接正常' : '连接失败' }}）</el-descriptions-item>
						</el-descriptions>
					</el-card>
				</el-col>
			</el-row>
			<el-card shadow="never" class="mt">
				<template #header><span>关键依赖版本</span></template>
				<el-table :data="packages" size="small">
					<el-table-column prop="name" label="包" width="180" />
					<el-table-column prop="version" label="版本">
						<template #default="{ row }">
							<span v-if="row.version">{{ row.version }}</span>
							<span v-else class="hint">未安装</span>
						</template>
					</el-table-column>
				</el-table>
			</el-card>
		</el-tab-pane>

		<!-- ============ 数据库 ============ -->
		<el-tab-pane label="数据库" name="database">
			<el-row :gutter="16">
				<el-col :xs="24" :md="10">
					<el-card shadow="never">
						<template #header><span>连接信息</span></template>
						<el-descriptions :column="1" border size="small">
							<el-descriptions-item label="方言">{{ info.database?.dialect }}</el-descriptions-item>
							<el-descriptions-item label="状态">
								<el-tag :type="info.database?.ok ? 'success' : 'danger'" size="small">{{ info.database?.ok ? '正常' : '失败' }}</el-tag>
							</el-descriptions-item>
							<el-descriptions-item label="目标">{{ info.paths?.db?.database }}</el-descriptions-item>
							<el-descriptions-item label="主机 / 端口">{{ info.paths?.db?.host || '本地文件' }} : {{ info.paths?.db?.port ?? '—' }}</el-descriptions-item>
						</el-descriptions>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="14">
					<el-card shadow="never">
						<template #header><span>各表行数（模型全生命周期 8 张表）</span></template>
						<el-table :data="counts" size="small">
							<el-table-column prop="table" label="表" width="200" />
							<el-table-column prop="rows" label="行数" />
						</el-table>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>

		<!-- ============ 日志 ============ -->
		<el-tab-pane label="日志" name="logs">
			<el-row :gutter="16">
				<el-col :xs="24" :md="9">
					<el-card shadow="never">
						<template #header><span>训练日志</span><el-button link type="primary" style="float: right" @click="loadLogs">刷新</el-button></template>
						<el-table :data="logs" size="small" max-height="520" empty-text="还没有日志">
							<el-table-column prop="name" label="日志" min-width="220" />
							<el-table-column prop="size_kb" label="KB" width="80" />
							<el-table-column label="操作" width="80">
								<template #default="{ row }"><el-button link type="primary" @click="openLog(row.name)">查看</el-button></template>
							</el-table-column>
						</el-table>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="15">
					<el-card shadow="never">
						<template #header>
							<span>日志内容：{{ logName || '—' }}</span>
							<el-select v-model="tail" size="small" style="width: 110px; float: right" @change="openLog(logName)">
								<el-option v-for="n in [100, 300, 1000]" :key="n" :label="`尾 ${n} 行`" :value="n" />
							</el-select>
						</template>
						<pre class="log">{{ logText || '点左侧日志查看内容' }}</pre>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>

		<!-- ============ 接口索引 ============ -->
		<el-tab-pane label="接口索引" name="api">
			<el-card shadow="never">
				<template #header><span>接口索引（来自 GET /api）</span><el-button link type="primary" style="float: right" @click="loadApi">刷新</el-button></template>
				<el-table :data="endpoints" size="small">
					<el-table-column prop="path" label="接口" width="320" />
					<el-table-column prop="desc" label="说明" />
				</el-table>
			</el-card>
		</el-tab-pane>

		<!-- ============ 维护 ============ -->
		<el-tab-pane label="维护" name="maintain">
			<el-alert type="error" :closable="false" show-icon class="mb" title="下面是破坏性操作，都会二次确认。" />
			<el-row :gutter="16">
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>清空图库</span></template>
						<div class="hint">删除 data/figures 下所有 PNG（当前 {{ info.figures?.count ?? 0 }} 张 / {{ info.figures?.total_kb ?? 0 }} KB）。下次训练/推理会重新生成。</div>
						<el-button type="danger" class="mt" @click="cleanup">清空图库</el-button>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>删除模型产物</span></template>
						<el-form inline size="small">
							<el-form-item label="模型">
								<el-select v-model="del.name" style="width: 140px">
									<el-option v-for="m in ['1dcnn', 'cwt_cnn', 'adtk']" :key="m" :label="m" :value="m" />
								</el-select>
							</el-form-item>
						</el-form>
						<div class="hint">一个模型只有一个产物，权重、scaler、meta 会一并删除（不含库表登记）。</div>
						<el-button type="danger" class="mt" @click="removeArtifact">删除产物</el-button>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>
	</el-tabs>
</template>

<script setup lang="ts" name="platformSystem">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { platformApi } from '/@/api/platform';

const route = useRoute();
const tab = ref<string>((route.query.tab as string) || 'runtime');
const info = ref<any>({});
const logs = ref<any[]>([]);
const logName = ref('');
const logText = ref('');
const tail = ref(300);
const endpoints = ref<any[]>([]);
const del = reactive({ name: '1dcnn' });

const packages = computed(() => Object.entries(info.value.packages || {}).map(([name, version]) => ({ name, version })));
const counts = computed(() => Object.entries(info.value.database?.counts || {}).map(([table, rows]) => ({ table, rows })));

const loadSystem = async () => { info.value = await platformApi.system(); };
const loadLogs = async () => { logs.value = ((await platformApi.logs()) as any).logs || []; };
const openLog = async (name: string) => {
	if (!name) return;
	logName.value = name;
	const res: any = await platformApi.logFile(name, tail.value);
	logText.value = `（共 ${res.total_lines} 行，显示最后 ${res.returned} 行）\n` + (res.lines || []).join('\n');
};
const loadApi = async () => {
	const res: any = await platformApi.apiIndex();
	endpoints.value = Object.entries(res.endpoints || {}).map(([path, desc]) => ({ path, desc }));
};

const cleanup = async () => {
	// ⚠️ ElMessageBox 用 **reject** 表示"用户点了取消"：不接住就是一条未处理的 Promise 拒绝，
	//    控制台留红字、看着像 bug（其余页面的确认框都写了这个 catch，这里原来漏了）。
	try {
		await ElMessageBox.confirm('确认清空 data/figures 下所有 PNG？此操作不可撤销。', '危险操作', { type: 'warning' });
	} catch {
		return;
	}
	try {
		const res: any = await platformApi.maintenance('figures');
		ElMessage.success(`已删除 ${res.removed} 张，释放 ${res.freed_kb} KB`);
		await loadSystem();
	} catch (e: any) {
		ElMessage.error(e?.message || '清空图库失败');
	}
};
const removeArtifact = async () => {
	try {
		await ElMessageBox.confirm(`确认删除模型 ${del.name} 的产物？权重 / scaler / meta 会一并删除。`, '危险操作', { type: 'warning' });
	} catch {
		return;
	}
	try {
		const res: any = await platformApi.deleteArtifact(del.name);
		ElMessage.success(`已删除 ${res.deleted}（${res.files} 个文件）`);
		await loadSystem();
	} catch (e: any) {
		ElMessage.error(e?.message || '删除模型产物失败');
	}
};

onMounted(async () => {
	// ⚠️ 以前是裸 Promise.all：任一接口 500/断网 → 未处理拒绝 + 整页空白且零提示。
	try {
		await Promise.all([loadSystem(), loadLogs(), loadApi()]);
	} catch (e: any) {
		ElMessage.error(e?.message || '系统信息加载失败，请确认后端服务已启动后刷新重试');
	}
});
</script>

<style scoped lang="scss">
.mt { margin-top: 12px; }
.mb { margin-bottom: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.log { max-height: 520px; overflow: auto; background: #141413; color: #ede9e0; padding: 12px; border-radius: 6px; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
</style>
