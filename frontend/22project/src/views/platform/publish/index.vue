<template>
	<div class="platform-publish">
		<!-- 顶部：一句话说明这个页面是干什么的，顺带把包存放目录亮出来 -->
		<el-alert type="info" :closable="false" show-icon class="mb">
			<template #title>
				这里汇总了本平台<b>已经发布（导出）过的模型包</b>，可直接下载拿到别的机器上使用。
			</template>
			<template #default>
				<div class="alert-body">
					每个包是一个 zip，解开后有模型文件、<code>meta.json</code>（输入/输出约定）、
					<code>README.md</code>（怎么用）、<code>requirements.txt</code> 和
					<code>example_infer.py</code>（可直接跑的例子）。
					磁盘位置：<code>{{ overview.export_dir || 'data/exports' }}</code>
					（库里记录在 <code>ModelDeployments</code> 表）
				</div>
			</template>
		</el-alert>

		<!-- KPI 四连：一眼看出家底 -->
		<el-row :gutter="16">
			<el-col :xs="12" :sm="6" v-for="k in kpis" :key="k.label">
				<el-card shadow="never" class="kpi-card">
					<div class="kpi-label">{{ k.label }}</div>
					<div class="kpi-value">{{ k.value }}</div>
					<div class="kpi-hint">{{ k.hint }}</div>
				</el-card>
			</el-col>
		</el-row>

		<!-- 库挂了也要能下载：磁盘上的包清单不依赖数据库 -->
		<el-alert v-if="overview.db_error" type="warning" :closable="false" show-icon class="mt"
			title="数据库连不上，下面只显示磁盘上实际存在的包；发布流水（版本/发布人）暂时看不到。" />

		<!-- 按模型分组的发布包 -->
		<el-card shadow="never" class="mt">
			<template #header>
				<div class="card-head">
					<span>已发布的模型包</span>
					<span class="hint">按模型分组，每个包可直接下载给外部使用</span>
					<el-button link type="primary" style="float: right" :loading="loading" @click="load">刷新</el-button>
				</div>
			</template>

			<el-empty v-if="!loading && !groups.length" description="还没有发布过任何模型包">
				<el-button type="primary" @click="goModel">去「模型管理」发布一个</el-button>
			</el-empty>

			<el-collapse v-else v-model="activeGroups" class="groups">
				<el-collapse-item v-for="g in groups" :key="g.model" :name="g.model">
					<template #title>
						<div class="group-title">
							<el-tag type="primary" effect="dark" size="small">{{ g.model }}</el-tag>
							<span class="hint">
								{{ g.deployments.length }} 条发布记录 ·
								{{ g.packages.length }} 个包在磁盘上
							</span>
							<el-tag v-if="g.downloadable" type="success" size="small">可下载 {{ g.downloadable }}</el-tag>
							<el-tag v-else type="info" size="small">无可下载包</el-tag>
							<el-tag v-if="!g.has_artifact" type="warning" size="small">模型产物已不在磁盘</el-tag>
						</div>
					</template>

					<!-- 磁盘上的包：下载的主入口 -->
					<div class="sub-title">磁盘上的包</div>
					<el-table :data="g.packages" size="small" empty-text="磁盘上已没有这个模型的包（可能被删除了）">
						<el-table-column prop="package" label="包文件名" min-width="260" show-overflow-tooltip />
						<el-table-column label="大小" width="100" align="right">
							<template #default="{ row }">{{ fmtSize(row.size_kb) }}</template>
						</el-table-column>
						<el-table-column label="生成时间" width="160">
							<template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
						</el-table-column>
						<el-table-column label="库里登记" width="100" align="center">
							<template #default="{ row }">
								<el-tag :type="row.recorded ? 'success' : 'warning'" size="small">
									{{ row.recorded ? '有' : '无' }}
								</el-tag>
							</template>
						</el-table-column>
						<el-table-column label="操作" width="150" align="center">
							<template #default="{ row }">
								<el-button link type="primary" @click="download(g.model, row.package)">下载</el-button>
								<el-button link type="primary" @click="showDetail(g.model, row.package)">看内容</el-button>
							</template>
						</el-table-column>
					</el-table>

					<!-- 库里的发布流水：档案性质，含已删除的留痕 -->
					<div class="sub-title">发布流水（含已删除记录）</div>
					<el-table :data="g.deployments" size="small" empty-text="库里没有这个模型的发布记录">
						<el-table-column prop="Version" label="版本" width="80" />
						<el-table-column label="是否最新" width="90" align="center">
							<template #default="{ row }">
								<el-tag v-if="row.IsCurrent" type="success" size="small">最新版</el-tag>
								<span v-else class="hint">历史版</span>
							</template>
						</el-table-column>
						<el-table-column label="来源训练" min-width="170">
							<template #default="{ row }">
								<span v-if="row.TrainingID">#{{ row.TrainingID }} {{ row.TrainName || '' }}</span>
								<span v-else class="hint">—</span>
							</template>
						</el-table-column>
						<el-table-column label="状态" width="90" align="center">
							<template #default="{ row }">
								<el-tag :type="row.DeployStatus === '已导出' ? 'success' : 'info'" size="small">
									{{ row.DeployStatus }}
								</el-tag>
							</template>
						</el-table-column>
						<el-table-column prop="DeployedBy" label="发布人" width="120" show-overflow-tooltip />
						<el-table-column label="发布时间" width="160">
							<template #default="{ row }">{{ fmtTime(row.DeployedDate) }}</template>
						</el-table-column>
						<el-table-column label="操作" width="90" align="center">
							<template #default="{ row }">
								<el-button link type="primary" :disabled="row.DeployStatus !== '已导出'"
									@click="download(g.model, baseName(row.DeployedPath))">下载</el-button>
							</template>
						</el-table-column>
					</el-table>
				</el-collapse-item>
			</el-collapse>
		</el-card>

		<!-- 包里有什么：列出 zip 的目录结构，让人下载前就知道拿了什么 -->
		<el-dialog v-model="detail.visible" :title="`包内容：${detail.package}`" width="640px">
			<el-descriptions v-if="detail.info" :column="2" border size="small" class="mb">
				<el-descriptions-item label="模型">{{ detail.info.model }}</el-descriptions-item>
				<el-descriptions-item label="包大小">{{ fmtSize(detail.info.size_kb) }}</el-descriptions-item>
				<el-descriptions-item label="生成时间">{{ fmtTime(detail.info.created_at) }}</el-descriptions-item>
				<el-descriptions-item label="文件数">{{ (detail.info.files || []).length }}</el-descriptions-item>
				<el-descriptions-item label="含说明文档" :span="2">
					<el-tag :type="detail.info.has_readme ? 'success' : 'warning'" size="small">
						{{ detail.info.has_readme ? '有 README.md' : '缺 README.md' }}
					</el-tag>
					<el-tag :type="detail.info.has_example ? 'success' : 'warning'" size="small" class="tag-gap">
						{{ detail.info.has_example ? '有 example_infer.py' : '缺 example_infer.py' }}
					</el-tag>
				</el-descriptions-item>
			</el-descriptions>
			<el-tree v-if="detail.info" :data="detail.info.files || []" :props="{ label: 'path' }"
				default-expand-all class="tree" empty-text="包为空" />
			<template #footer>
				<el-button @click="detail.visible = false">关闭</el-button>
				<el-button type="primary" @click="download(detail.model, detail.package)">下载这个包</el-button>
			</template>
		</el-dialog>
	</div>
</template>

<script setup lang="ts" name="platformPublish">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { platformApi, fileUrl } from '/@/api/platform';

const router = useRouter();
const loading = ref(false);
const overview = ref<any>({});
// 折叠面板默认全展开：模型也就三五个，收起反而要多点一次
const activeGroups = ref<string[]>([]);

const groups = computed<any[]>(() => overview.value.groups || []);

const kpis = computed(() => {
	const t = overview.value.total || {};
	return [
		{ label: '已发布模型', value: t.models ?? 0, hint: '有发布记录的模型数' },
		{ label: '发布次数', value: t.records ?? 0, hint: 'ModelDeployments 记录数（含已删除）' },
		{ label: '磁盘上包数', value: t.packages_on_disk ?? 0, hint: 'data/exports 下实际存在的 zip' },
		{ label: '占用空间', value: fmtSize(t.size_kb), hint: '所有发布包合计' },
	];
});

const detail = reactive<any>({ visible: false, model: '', package: '', info: null });

/** 取路径最后一段。⚠️ 必须同时认 Windows 的反斜杠，库里存的是 `D:\...\x.zip`。 */
const baseName = (p: string) => String(p || '').split(/[\\/]/).pop() || '';

/** KB → 人类可读。包从几十 KB 到上百 MB 都有，统一按 KB 存、这里换算。 */
const fmtSize = (kb: any) => {
	const n = Number(kb);
	if (!n || n < 0) return '—';
	if (n < 1024) return `${n.toFixed(0)} KB`;
	return `${(n / 1024).toFixed(1)} MB`;
};

/** 后端给的是 MySQL DATETIME 字符串，已经是本地时间，直接截到分钟展示即可。 */
const fmtTime = (t: any) => (t ? String(t).slice(0, 16) : '—');

/** 下载一个包。走 fileUrl() 拼绝对地址 + <a download>，与模型管理页里一致。 */
const download = (model: string, pkg: string) => {
	if (!pkg || pkg === '—') return;
	const url = fileUrl(`/models/${encodeURIComponent(model)}/exports/${encodeURIComponent(pkg)}`);
	const a = document.createElement('a');
	a.href = url;
	a.download = pkg;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
};

/** 看包内容：拉磁盘上的 zip 条目列表（不下载，只读中央目录）。 */
const showDetail = async (model: string, pkg: string) => {
	try {
		detail.model = model;
		detail.package = pkg;
		detail.info = null;
		detail.visible = true;
		// ⚠️ 必须用 inspectExport，不能用 exports()：后者返回的是**模型级**的
		//    {packages, deployments}，没有 framework/size_kb/files 这些字段，
		//    直接拿来渲染会全是「—」。
		detail.info = await platformApi.inspectExport(model, pkg);
	} catch (e: any) {
		ElMessage.error('读取包内容失败：' + (e?.response?.data?.error || e?.message || e));
		detail.visible = false;
	}
};

const goModel = () => router.push('/platform/model');

const load = async () => {
	loading.value = true;
	try {
		overview.value = await platformApi.exportOverview();
		// 默认把有包的模型展开（没包的收起来，免得页面太长）
		activeGroups.value = (overview.value.groups || [])
			.filter((g: any) => g.packages.length)
			.map((g: any) => g.model);
	} catch (e: any) {
		ElMessage.error('加载发布汇总失败：' + (e?.response?.data?.error || e?.message || e));
	} finally {
		loading.value = false;
	}
};

onMounted(load);
</script>

<style scoped lang="scss">
.mb { margin-bottom: 16px; }
.mt { margin-top: 16px; }
.alert-body { font-size: 12px; line-height: 1.8; }
.alert-body code {
	background: var(--el-fill-color);
	padding: 1px 5px;
	border-radius: 3px;
	font-family: Consolas, Monaco, monospace;
}
.kpi-card { text-align: left; }
.kpi-label { font-size: 13px; color: var(--el-text-color-secondary); }
.kpi-value { font-size: 26px; font-weight: 600; margin: 4px 0; }
.kpi-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.card-head { display: flex; align-items: baseline; gap: 12px; }
.card-head .hint { font-size: 12px; color: var(--el-text-color-secondary); }
.group-title { display: flex; align-items: center; gap: 10px; }
.group-title .hint { font-size: 12px; color: var(--el-text-color-secondary); }
.sub-title {
	font-size: 13px;
	font-weight: 600;
	margin: 12px 0 6px;
	padding-left: 8px;
	border-left: 3px solid var(--el-color-primary);
}
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.tag-gap { margin-left: 6px; }
.tree { max-height: 300px; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; }
</style>
