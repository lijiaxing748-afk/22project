<template>
	<el-tabs v-model="tab" class="platform-page">
		<!-- ============ 数据集体检 ============ -->
		<el-tab-pane label="数据集体检" name="inspect">
			<el-card shadow="never">
				<template #header>
					<span>数据集（内置 .mat + data/datasets 下上传的表格数据集）</span>
					<el-button link type="primary" style="float: right" @click="loadDatasets">刷新</el-button>
				</template>
				<el-select v-model="current" style="width: 420px" @change="() => {}">
					<el-option v-for="k in datasetKeys" :key="k" :label="k" :value="k" />
				</el-select>
				<el-row :gutter="16" class="mt">
					<el-col :xs="12" :md="6" v-for="k in kpis" :key="k.label">
						<el-card shadow="never">
							<div class="hint">{{ k.label }}</div>
							<div class="kpi">{{ k.value }}</div>
							<div class="hint">{{ k.hint }}</div>
						</el-card>
					</el-col>
				</el-row>
				<el-table :data="currentFiles" size="small" class="mt" empty-text="没有文件">
					<el-table-column prop="filename" label="文件" min-width="240" />
					<el-table-column prop="label" label="类别（文件名即标签）" min-width="130" />
					<el-table-column v-if="isTabular" prop="rows" label="行数" width="100" />
					<el-table-column v-if="isTabular" prop="cols" label="列数" width="80" />
					<el-table-column v-if="isTabular" prop="signal_column" label="信号列" width="120" />
					<el-table-column v-if="!isTabular" prop="class_id" label="class_id" width="90" />
					<el-table-column v-if="!isTabular" prop="samples_in_file" label="采样点" width="110" />
					<el-table-column v-if="!isTabular" label="按 784 可切窗口" width="140">
						<template #default="{ row }">{{ Math.floor((row.samples_in_file || 0) / 784) }}</template>
					</el-table-column>
					<el-table-column label="状态" width="110">
						<template #default="{ row }">
							<el-tag :type="row.error ? 'danger' : 'success'" size="small">{{ row.error ? '读取失败' : '正常' }}</el-tag>
						</template>
					</el-table-column>
				</el-table>
			</el-card>
		</el-tab-pane>

		<!-- ============ 表格数据集 ============ -->
		<el-tab-pane label="表格数据集" name="tabular">
			<el-row :gutter="16">
				<el-col :xs="24" :md="10">
					<el-card shadow="never">
						<template #header><span>上传表格文件（一个文件 = 一个类别，文件名即标签）</span></template>
						<el-form label-width="90px" size="small">
							<el-form-item label="数据集名">
								<el-input v-model="upload.name" placeholder="data/datasets/<名称>/" />
							</el-form-item>
							<el-form-item label="文件">
								<input ref="fileInput" type="file" multiple accept=".csv,.txt,.xlsx,.xls,.xlsm" class="file-input" />
							</el-form-item>
							<el-button type="primary" :loading="uploading" @click="doUpload">上传</el-button>
							<span class="hint ml">支持 .csv/.txt/.xlsx/.xls；CSV 自动试 utf-8 / GBK 编码。</span>
						</el-form>
						<el-divider />
						<div class="hint">已上传的表格数据集</div>
						<div class="mt">
							<el-tag v-for="k in tabularKeys" :key="k" size="small" class="tag-gap" @click="preview(k, tabularFiles(k)[0]?.filename)">
								{{ k }}（{{ datasets[k].file_count }} 文件 / {{ datasets[k].classes }} 类）
							</el-tag>
							<span v-if="!tabularKeys.length" class="hint">还没有上传表格数据集</span>
						</div>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="14">
					<el-card shadow="never">
						<template #header><span>表格预览：{{ previewData?.file || '—' }}</span></template>
						<div v-if="previewData">
							<el-descriptions :column="2" border size="small">
								<el-descriptions-item label="格式">{{ previewData.format }} {{ previewData.sheets?.length ? '· ' + previewData.sheets.join(', ') : '' }}</el-descriptions-item>
								<el-descriptions-item label="规模">{{ previewData.rows }} 行 × {{ previewData.cols }} 列（{{ previewData.size_kb }} KB）</el-descriptions-item>
								<el-descriptions-item label="信号列" :span="2">
									<el-select v-model="previewColumn" size="small" style="width: 220px" @change="reloadPreview">
										<el-option label="自动识别" value="" />
										<el-option v-for="c in previewData.numeric_columns" :key="c" :label="c" :value="c" />
									</el-select>
									<el-tag size="small" type="success" class="ml">当前：{{ previewData.signal_column || '未识别' }}</el-tag>
								</el-descriptions-item>
							</el-descriptions>
							<el-table :data="previewData.columns" size="small" class="mt" max-height="260">
								<el-table-column prop="name" label="列名" min-width="120">
									<template #default="{ row }">
										<b>{{ row.name }}</b>
										<el-tag v-if="row.is_signal" size="small" type="success" class="ml">信号列</el-tag>
									</template>
								</el-table-column>
								<!-- 表头统一用中文：这张表是我们自己算的统计量（如 pandas describe），
								     不是用户文件里的原始列名，没有理由显示成 dtype/mean。
								     下面「前 N 行」那张表的 :label="c" 才是**原始列名**，必须保持原样。 -->
								<el-table-column prop="dtype" label="类型" width="100" />
								<el-table-column label="数值列" width="80"><template #default="{ row }">{{ row.numeric ? '是' : '否' }}</template></el-table-column>
								<el-table-column prop="non_null" label="非空" width="80" />
								<el-table-column prop="nulls" label="缺失" width="80" />
								<el-table-column prop="unique" label="唯一值" width="80" />
								<el-table-column prop="min" label="最小" width="110" />
								<el-table-column prop="max" label="最大" width="110" />
								<el-table-column prop="mean" label="均值" width="110" />
								<el-table-column prop="std" label="标准差" width="110" />
							</el-table>
							<div class="hint mt">前 {{ previewData.head_rows }} 行</div>
							<el-table :data="headRows" size="small" max-height="240">
								<el-table-column v-for="c in previewData.column_names" :key="c" :prop="c" :label="c" min-width="120" />
							</el-table>
						</div>
						<div v-else class="empty">点左侧数据集或文件查看预览</div>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>

		<!-- ============ 库表登记 ============ -->
		<el-tab-pane label="库表登记" name="register">
			<el-row :gutter="16">
				<el-col :xs="24" :md="14">
					<el-card shadow="never">
						<template #header><span>Datasets 表登记记录</span><el-button link type="primary" style="float: right" @click="loadDatasetDb">刷新</el-button></template>
						<el-table :data="dbDatasets" size="small" empty-text="还没有登记记录">
							<el-table-column prop="DatasetID" label="ID" width="70" />
							<el-table-column prop="DatasetName" label="名称" min-width="150" />
							<el-table-column prop="Source" label="来源" min-width="160" />
							<el-table-column prop="ClassCount" label="类别" width="80" />
							<el-table-column prop="SampleCount" label="样本" width="90" />
							<el-table-column prop="DataPath" label="路径" min-width="200" />
							<el-table-column prop="CreatedDate" label="登记时间" width="170" />
						</el-table>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="10">
					<el-card shadow="never">
						<template #header><span>登记新数据集</span></template>
						<el-form label-width="90px" size="small">
							<el-form-item label="名称 *"><el-input v-model="reg.name" placeholder="唯一键，例如 CWRU-1HP" /></el-form-item>
							<el-form-item label="来源"><el-input v-model="reg.source" /></el-form-item>
							<el-form-item label="类别数"><el-input-number v-model="reg.class_count" :min="1" controls-position="right" /></el-form-item>
							<el-form-item label="样本数"><el-input-number v-model="reg.sample_count" :min="0" controls-position="right" /></el-form-item>
							<el-form-item label="数据路径"><el-input v-model="reg.data_path" placeholder="testRestfulProject/data/datasets/xxx" /></el-form-item>
							<el-form-item label="描述"><el-input v-model="reg.description" type="textarea" :rows="2" /></el-form-item>
							<el-button type="primary" @click="doRegister">登记</el-button>
						</el-form>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>
	</el-tabs>
</template>

<script setup lang="ts" name="platformDataset">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { platformApi } from '/@/api/platform';

const route = useRoute();
const tab = ref<string>((route.query.tab as string) || 'inspect');
const datasets = ref<Record<string, any>>({});
const current = ref<string>('');
const dbDatasets = ref<any[]>([]);
const previewData = ref<any>(null);
const previewColumn = ref<string>('');
const fileInput = ref<HTMLInputElement>();
const uploading = ref(false);
const upload = reactive({ name: '' });
const reg = reactive<any>({ name: '', source: '', class_count: 10, sample_count: null, data_path: '', description: '' });

const datasetKeys = computed(() => Object.keys(datasets.value));
const tabularKeys = computed(() => datasetKeys.value.filter((k) => datasets.value[k]?.dataset_type === 'tabular'));
const currentData = computed(() => datasets.value[current.value] || {});
const currentFiles = computed(() => (currentData.value.files || []).filter((f: any) => f.on_disk));
const isTabular = computed(() => currentData.value.dataset_type === 'tabular');
const tabularFiles = (key: string) => (datasets.value[key]?.files || []).filter((f: any) => f.on_disk);

const kpis = computed(() => {
	const d: any = currentData.value;
	if (isTabular.value) {
		return [
			{ label: '类型', value: '表格', hint: 'Excel / CSV，一文件一类别' },
			{ label: '文件 / 类别', value: `${d.file_count ?? 0} / ${d.classes ?? 0}`, hint: 'on_disk 文件数' },
			{ label: '最短文件（行）', value: d.min_rows ?? '—', hint: '行数最少的文件' },
			{ label: '最长文件（行）', value: d.max_rows ?? '—', hint: '行数最多的文件' },
		];
	}
	return [
		{ label: '类型', value: 'MATLAB .mat', hint: '取 DE 通道' },
		{ label: '文件 / 类别', value: `${d.file_count ?? 0} / ${d.classes ?? 0}`, hint: '.mat 文件数' },
		{ label: '最短文件（点）', value: d.min_samples_in_file ?? '—', hint: 'IR014 只有 63788' },
		{ label: '最长文件（点）', value: d.max_samples_in_file ?? '—', hint: '采样点数' },
	];
});

const headRows = computed(() => {
	if (!previewData.value) return [];
	const { column_names, head } = previewData.value;
	return (head || []).map((row: any[]) => {
		const obj: any = {};
		column_names.forEach((c: string, i: number) => (obj[c] = row[i]));
		return obj;
	});
});

const loadDatasets = async () => {
	datasets.value = (await platformApi.datasets()) as any;
	if (!current.value || !datasets.value[current.value]) current.value = datasetKeys.value[0];
};
const loadDatasetDb = async () => { dbDatasets.value = ((await platformApi.datasetDb()) as any).datasets || []; };

const preview = async (datasetKey: string, filename?: string) => {
	if (!filename) return;
	const dir = datasets.value[datasetKey]?.dataset_dir;
	previewColumn.value = '';
	await reloadPreview(`${dir}\\${filename}`);
};
const reloadPreview = async (path?: string) => {
	const target = path || previewData.value?.path;
	if (!target) return;
	previewData.value = await platformApi.tablePreview(target, 8, previewColumn.value);
};

const doUpload = async () => {
	const files = fileInput.value?.files;
	if (!files || !files.length) { ElMessage.warning('先选择文件'); return; }
	const form = new FormData();
	form.append('name', upload.name || '');
	Array.from(files).forEach((f: any) => form.append('file', f, f.name));
	uploading.value = true;
	try {
		const res: any = await platformApi.upload(form);
		ElMessage.success(`已保存 ${res.saved.length} 个到 ${res.directory}`);
		if (res.skipped?.length) ElMessage.warning(`跳过 ${res.skipped.length} 个：${res.skipped.map((s: any) => s.filename).join(', ')}`);
		await loadDatasets();
		if (tabularKeys.value.length) await preview(tabularKeys.value[0], tabularFiles(tabularKeys.value[0])[0]?.filename);
	} finally {
		uploading.value = false;
	}
};

const doRegister = async () => {
	if (!reg.name) { ElMessage.warning('名称不能为空'); return; }
	const payload: any = { ...reg };
	Object.keys(payload).forEach((k) => payload[k] === '' && delete payload[k]);
	const res: any = await platformApi.registerDataset(payload);
	await ElMessageBox.alert(res.already_existed ? `已存在，沿用 DatasetID=${res.DatasetID}` : `登记成功，DatasetID=${res.DatasetID}`, '提示');
	await loadDatasetDb();
};

onMounted(async () => {
	await Promise.all([loadDatasets(), loadDatasetDb()]);
	if (tabularKeys.value.length) await preview(tabularKeys.value[0], tabularFiles(tabularKeys.value[0])[0]?.filename);
});
</script>

<style scoped lang="scss">
.mt { margin-top: 16px; }
.ml { margin-left: 8px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.kpi { font-size: 26px; font-weight: 600; margin: 4px 0; }
.empty { color: var(--el-text-color-secondary); text-align: center; padding: 24px 0; }
.tag-gap { margin: 0 6px 6px 0; cursor: pointer; }
.file-input { font-size: 12px; }
</style>
