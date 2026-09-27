<template>
	<el-tabs v-model="tab" class="platform-page">
		<!-- ============ 信号浏览 ============ -->
		<el-tab-pane label="信号浏览" name="signal">
			<el-card shadow="never">
				<template #header>
					<span>原始振动信号（降采样显示）</span>
					<el-button link type="primary" style="float: right" @click="loadSignal">重新采样</el-button>
				</template>
				<el-form inline size="small">
					<el-form-item label="数据集">
						<el-select v-model="dataset" style="width: 260px" @change="onDatasetChange">
							<el-option v-for="k in datasetKeys" :key="k" :label="k" :value="k" />
						</el-select>
					</el-form-item>
					<el-form-item label="文件">
						<el-select v-model="file" style="width: 320px" @change="loadSignal">
							<el-option v-for="f in files" :key="f.filename" :label="`${f.filename}（${f.label}）`" :value="f.filename" />
						</el-select>
					</el-form-item>
					<el-form-item label="信号列">
						<el-input v-model="column" placeholder="表格数据留空=自动" style="width: 160px" @change="loadSignal" />
					</el-form-item>
					<el-form-item label="起始点">
						<el-input-number v-model="start" :min="0" :step="1000" controls-position="right" style="width: 140px" @change="loadSignal" />
					</el-form-item>
					<el-form-item label="显示点数">
						<el-select v-model="points" style="width: 120px" @change="loadSignal">
							<el-option v-for="p in [600, 1500, 3000, 4000]" :key="p" :label="String(p)" :value="p" />
						</el-select>
					</el-form-item>
				</el-form>
				<canvas ref="canvas" width="1200" height="300" class="wave"></canvas>
				<el-row :gutter="16" class="mt">
					<el-col :xs="12" :md="6" v-for="s in stats" :key="s.label">
						<el-card shadow="never">
							<div class="hint">{{ s.label }}</div>
							<div class="stat">{{ s.value }}</div>
							<div class="hint">{{ s.hint }}</div>
						</el-card>
					</el-col>
				</el-row>
			</el-card>
		</el-tab-pane>

		<!-- ============ 图库 ============ -->
		<el-tab-pane label="图库" name="gallery">
			<el-card shadow="never">
				<template #header>
					<span>已生成的图（data/figures/）</span>
					<el-button link type="primary" style="float: right" @click="loadFigures">刷新</el-button>
				</template>
				<el-input v-model="filter" placeholder="按路径过滤，例如 1dcnn/v1；留空显示全部" style="width: 340px" class="mb" />
				<div class="gallery">
					<div v-for="f in filtered" :key="f.url" class="cell">
						<el-image :src="fileUrl(f.url)" :preview-src-list="[fileUrl(f.url)]" fit="contain" class="img" />
						<div class="cap" :title="f.file">
							<span class="cap-name">{{ f.file }}</span>
							<el-button link type="danger" size="small" class="cap-del" @click="removeFigure(f)">删除</el-button>
						</div>
						<div class="hint">{{ f.size_kb }} KB · {{ f.modified }}</div>
					</div>
					<div v-if="!filtered.length" class="empty">没有匹配的图，去训练或推理一次</div>
				</div>
			</el-card>
		</el-tab-pane>
	</el-tabs>
</template>

<script setup lang="ts" name="platformVisual">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { platformApi, fileUrl } from '/@/api/platform';

const route = useRoute();
const tab = ref<string>((route.query.tab as string) || 'signal');
const datasets = ref<Record<string, any>>({});
const dataset = ref<string>('');
const file = ref<string>('');
const column = ref<string>('');
const start = ref(0);
const points = ref(1500);
const figures = ref<any[]>([]);
const filter = ref('');
const canvas = ref<HTMLCanvasElement>();
const signalInfo = ref<any>(null);

const datasetKeys = computed(() => Object.keys(datasets.value));
const files = computed(() => (datasets.value[dataset.value]?.files || []).filter((f: any) => f.on_disk));
const filtered = computed(() =>
	figures.value.filter((f) => !filter.value || f.file.toLowerCase().includes(filter.value.toLowerCase()))
);
const stats = computed(() => {
	const d: any = signalInfo.value;
	if (!d) return [];
	return [
		{ label: '文件', value: d.file, hint: `${d.dataset_type === 'tabular' ? '表格' : 'MAT'}${d.column ? ' · 列 ' + d.column : ''}` },
		{ label: '类别 / 标签', value: d.label, hint: d.class_id != null ? `class_id=${d.class_id}` : '文件名即标签' },
		{ label: '文件总点数', value: d.samples_in_file, hint: `起始采样点 ${d.start}` },
		{ label: '显示 / stride', value: `${d.points} / ${d.stride}`, hint: `min ${d.min} · max ${d.max} · mean ${d.mean} · std ${d.std}` },
	];
});

const onDatasetChange = async () => {
	file.value = files.value[0]?.filename || '';
	await loadSignal();
};
const loadDatasets = async () => {
	datasets.value = (await platformApi.datasets()) as any;
	if (!dataset.value) dataset.value = datasetKeys.value[0];
	if (!file.value) file.value = files.value[0]?.filename || '';
};

const loadSignal = async () => {
	if (!file.value) return;
	try {
		const d: any = await platformApi.signal({
			dataset: dataset.value, file: file.value, column: column.value,
			points: points.value, start: start.value,
		});
		signalInfo.value = d;
		draw(d.values);
	} catch (e: any) {
		ElMessage.error('取信号失败：' + (e?.message || e));
	}
};

const draw = (values: number[]) => {
	const el = canvas.value;
	if (!el) return;
	const ctx = el.getContext('2d')!;
	const W = el.width, H = el.height, pad = 36;
	ctx.clearRect(0, 0, W, H);
	if (!values?.length) return;
	let min = Math.min(...values), max = Math.max(...values);
	if (min === max) { min -= 0.5; max += 0.5; }
	const x = (i: number) => pad + (i * (W - pad * 2)) / (values.length - 1);
	const y = (v: number) => H - pad - ((v - min) * (H - pad * 2)) / (max - min);
	ctx.strokeStyle = 'rgba(107,104,96,.22)';
	for (let g = 0; g <= 4; g++) {
		const gy = pad + (g * (H - pad * 2)) / 4;
		ctx.beginPath(); ctx.moveTo(pad, gy); ctx.lineTo(W - pad, gy); ctx.stroke();
	}
	ctx.strokeStyle = '#141413'; ctx.lineWidth = 1; ctx.beginPath();
	values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
	ctx.stroke();
	ctx.fillStyle = '#6b6860'; ctx.font = '11px monospace';
	ctx.fillText(max.toFixed(3), 4, pad + 4);
	ctx.fillText(min.toFixed(3), 4, H - pad + 4);
	ctx.fillText(String(values.length - 1), W - pad - 24, H - 8);
};

const loadFigures = async () => { figures.value = ((await platformApi.figures(300)) as any).figures || []; };

/**
 * 删除一张图。
 *
 * ⚠️ 取消确认要用 try/catch 单独接住：`ElMessageBox.confirm` 用 **reject** 表示"用户点了取消"，
 *    不接就会变成未处理的 Promise 拒绝（控制台一片红，看着像 bug）。
 *    所以确认框与真正的删除请求分开写，别把两者塞进同一个 try。
 * ⚠️ 删除失败（图已被人删掉 / 没登录 / 路径非法）由平台拦截器包成 Error(msg) 抛出，
 *    这里负责提示 —— platformRequest 不会自己弹消息（见其文件头说明）。
 */
const removeFigure = async (f: any) => {
	try {
		await ElMessageBox.confirm(`确认删除这张图？\n${f.file}`, '危险操作', { type: 'warning' });
	} catch {
		return;                                  // 用户取消
	}
	try {
		const res: any = await platformApi.deleteFigure(f.file);
		ElMessage.success(`已删除，释放 ${res?.freed_kb ?? '?'} KB`);
		await loadFigures();                     // 重新拉列表：目录可能被一并清掉了
	} catch (e: any) {
		ElMessage.error(e?.message || '删除失败');
	}
};

onMounted(async () => {
	// ⚠️ 以前是裸 Promise.all：任一接口 500/断网 → 未处理拒绝 + 整页空白且零提示。
	try {
		await loadDatasets();
		await Promise.all([loadSignal(), loadFigures()]);
	} catch (e: any) {
		ElMessage.error(e?.message || '数据展示页加载失败，请确认后端服务已启动后刷新重试');
	}
});
</script>

<style scoped lang="scss">
.mt { margin-top: 16px; }
.mb { margin-bottom: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.stat { font-size: 16px; font-weight: 600; margin: 4px 0; word-break: break-all; }
.wave { width: 100%; height: 300px; background: #fffdf8; border: 1px solid var(--el-border-color); border-radius: 6px; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.cell { border: 1px solid var(--el-border-color); border-radius: 6px; overflow: hidden; background: #fff; }
.img { width: 100%; height: 170px; background: #f5f5f5; display: block; }
// ⚠️ 文件名用 flex 布局：`.cap` 原来靠自身的 ellipsis 截断，现在里面多了一个删除按钮，
//    截断必须挪到 `.cap-name` 上，否则按钮会跟着文字一起被 ellipsis 裁掉（点不到）。
//    `min-width: 0` 是 flex 子项能收缩的前提，漏了它长文件名会把按钮挤出卡片。
.cap { font-size: 12px; padding: 6px 8px 0; display: flex; align-items: center; gap: 6px; }
.cap-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cap-del { flex: 0 0 auto; }
.cell .hint { padding: 0 8px 8px; }
.empty { color: var(--el-text-color-secondary); text-align: center; padding: 24px 0; grid-column: 1 / -1; }
</style>
