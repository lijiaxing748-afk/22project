<template>
	<div class="platform-log">
		<!-- 说明这个页面存在的意义：给验收/排查提供"谁在什么时候干了什么"的证据链 -->
		<el-alert type="info" :closable="false" show-icon class="mb">
			<template #title>
				这里集中展示<b>谁在什么时候做了什么</b>，包括登录、用户管理、模型上传/删除、发布、数据集、训练等关键操作。
			</template>
			<template #default>
				<div class="alert-body">
					日志<b>只记录成功的操作</b>（训练例外：失败也会记，便于排查"为什么没训出来"）。
					高频的<b>推理不在本表留痕</b>——它由 <code>InferenceResults</code> 表兜底，
					避免日志表被推理请求刷爆。
					<br />
					日志是<b>审计记录，不可修改或删除</b>。显示的是最近 {{ limit }} 条。
				</div>
			</template>
		</el-alert>

		<!-- KPI：先给整体印象，再往下看明细 -->
		<el-row :gutter="16" class="mb">
			<el-col :xs="12" :sm="6" v-for="k in kpis" :key="k.label">
				<el-card shadow="never" class="kpi-card">
					<div class="kpi-label">{{ k.label }}</div>
					<div class="kpi-value" :class="k.tone">{{ k.value }}</div>
					<div class="kpi-hint">{{ k.hint }}</div>
				</el-card>
			</el-col>
		</el-row>

		<el-card shadow="never">
			<template #header>
				<div class="card-head">
					<span>操作日志</span>
					<!--
						计数要跟着筛选走：只显示总数会让用户以为筛选没生效
						（表格明显变短了，标签还是 365，会怀疑是页面卡了）。
					-->
					<span class="hint">
						<template v-if="hasFilter">筛选出 {{ filtered.length }} 条（共 {{ rows.length }} 条）</template>
						<template v-else>共 {{ rows.length }} 条</template>
					</span>
					<div style="float: right">
						<!--
							⚠️ 两个下拉都必须 clearable + 显式给「全部」选项。
							之前没给 clearable，一旦选了某个动作就**退不回全部**
							（要清空只能刷新整页），这是实测中发现的问题。
						-->
						<el-select v-model="filterAction" placeholder="全部动作" clearable
							style="width: 170px; margin-right: 8px">
							<el-option label="全部动作" value="" />
							<el-option v-for="a in actionOptions" :key="a.value" :label="a.label" :value="a.value" />
						</el-select>
						<el-select v-model="filterResult" placeholder="全部结果" clearable
							style="width: 130px; margin-right: 8px">
							<el-option label="全部结果" value="" />
							<el-option label="成功" value="成功" />
							<el-option label="失败" value="失败" />
						</el-select>
						<el-input
							v-model="keyword"
							placeholder="搜索用户名 / 对象 / 详情"
							clearable
							style="width: 220px; margin-right: 8px"
							:prefix-icon="Search"
						/>
						<!-- 一键还原：三个筛选条件分散，逐个清容易漏 -->
						<el-button v-if="hasFilter" link type="primary" style="margin-right: 8px" @click="clearFilters">
							重置筛选
						</el-button>
						<el-button :loading="loading" @click="load">刷新</el-button>
					</div>
				</div>
			</template>

			<!-- 首次加载骨架屏；失败给明确原因，而不是空表 -->
			<el-skeleton v-if="loading && !rows.length" :rows="5" animated />

			<el-alert v-else-if="error" type="error" :closable="false" show-icon
				:title="error"
				description="操作日志只对管理员开放。如果提示没有权限，请用 admin 账号登录后重试。" />

			<el-empty v-else-if="!filtered.length"
				:description="hasFilter ? '没有匹配的日志，可点「重置筛选」还原' : '暂无操作日志'" />

			<el-table v-else :data="filtered" size="default" stripe :row-class-name="rowClass">
				<el-table-column prop="CreatedDate" label="时间" width="165">
					<template #default="{ row }">
						<span class="mono">{{ fmtTime(row.CreatedDate) }}</span>
					</template>
				</el-table-column>

				<el-table-column label="操作人" width="120">
					<template #default="{ row }">
						<span v-if="row.Username" class="mono">{{ row.Username }}</span>
						<span v-else class="hint">—</span>
						<div v-if="row.RoleKey" class="cell-sub">{{ roleName(row.RoleKey) }}</div>
					</template>
				</el-table-column>

				<el-table-column label="操作" width="150">
					<template #default="{ row }">
						<el-tag :type="actionTagType(row.Action)" size="small" effect="light">
							{{ actionLabel(row.Action) }}
						</el-tag>
						<div class="cell-sub mono">{{ row.Action }}</div>
					</template>
				</el-table-column>

				<el-table-column label="操作对象" min-width="140">
					<template #default="{ row }">
						<span v-if="row.Target">{{ row.Target }}</span>
						<span v-else class="hint">—</span>
					</template>
				</el-table-column>

				<el-table-column label="结果" width="90" align="center">
					<template #default="{ row }">
						<el-tag :type="row.Result === '成功' ? 'success' : 'danger'" size="small">
							{{ row.Result || '—' }}
						</el-tag>
					</template>
				</el-table-column>

				<el-table-column label="详情" min-width="260">
					<template #default="{ row }">
						<!-- Detail 是后端存的 JSON 字符串，这里格式化成紧凑的 key=value 便于扫读 -->
						<span v-if="detailItems(row).length" class="detail">
							<span v-for="(d, i) in detailItems(row)" :key="i" class="detail-pair">
								<span class="detail-k">{{ d.k }}</span>
								<span class="detail-v">{{ d.v }}</span>
							</span>
						</span>
						<!-- 没有结构详情时退回 Message（失败原因常在这里） -->
						<span v-else-if="row.Message" class="hint">{{ row.Message }}</span>
						<span v-else class="hint">—</span>
					</template>
				</el-table-column>

				<el-table-column label="来源 IP" width="130">
					<template #default="{ row }">
						<span class="mono hint">{{ row.ClientIP || '—' }}</span>
					</template>
				</el-table-column>
			</el-table>
		</el-card>
	</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { ElMessage } from 'element-plus';
import { Search } from '@element-plus/icons-vue';
import { platformApi } from '/@/api/platform';

/**
 * 操作日志页（管理员专属）
 *
 * ⚠️ 与用户管理页同一套**信封协议**：`{code, data, msg}`，**失败也回 HTTP 200**。
 *    所以判断成败必须看 `code === 2000`，不能靠 try/catch 或 HTTP 状态码。
 *
 * ⚠️ 后端只提供 `?limit=`，**没有分页与筛选参数**（见 dvadmin.py 的
 *    operation_log_list）。所以筛选与搜索都在前端做——日志量在工厂内网规模下
 *    完全够用（后端上限 500 条）。真要做服务端分页，得先改后端接口。
 */

/** 后端 limit 上限就是 500，取满一次，前端再做筛选 */
const limit = 500;

const rows = ref<any[]>([]);
const loading = ref(false);
const error = ref('');
const keyword = ref('');
const filterAction = ref('');
const filterResult = ref('');

/**
 * 动作中文名。**key 必须与后端 log_operation() 的 action 完全一致**，
 * 后端用的是 snake_case（与埋点时定的规范一致）。这里有遗漏也不会出错，
 * 只是会退回显示原始英文 key（见 actionLabel），所以新增埋点时不必强制同步这里。
 */
const ACTION_LABEL: Record<string, string> = {
	// —— 鉴权 / 用户 ——
	login: '登录',
	logout: '登出',
	change_password: '修改密码',
	create_user: '新建用户',
	update_user: '修改用户',
	reset_password: '重置密码',
	// —— 模型 ——
	upload_model: '上传模型',
	update_model: '修改模型',
	delete_model: '删除模型产物',
	delete_model_record: '删除模型记录',
	publish_model: '发布模型',
	unpublish_model: '取消发布',
	// —— 数据集 ——
	upload_dataset: '上传数据集',
	register_dataset: '登记数据集',
	// —— 训练 ——
	run_training: '训练',
};

/** 按动作分组着色：鉴权蓝、模型紫、数据集绿、训练橙，扫一眼能分辨类别 */
const ACTION_TONE: Record<string, string> = {
	login: 'info', logout: 'info', change_password: 'info',
	create_user: 'info', update_user: 'info', reset_password: 'info',
	upload_model: 'primary', update_model: 'primary', delete_model: 'primary',
	delete_model_record: 'primary', publish_model: 'primary', unpublish_model: 'primary',
	upload_dataset: 'success', register_dataset: 'success',
	run_training: 'warning',
};

const ROLE_NAME: Record<string, string> = {
	admin: '管理员',
	engineer: '工程师',
	operator: '操作员',
};

const actionLabel = (a: string) => ACTION_LABEL[a] || a || '—';
const actionTagType = (a: string) => (ACTION_TONE[a] as any) || 'info';
const roleName = (k: string) => ROLE_NAME[k] || k;

/** 下拉框的动作选项：只列出**当前数据里真实出现过**的动作，避免一堆永远选不到的项 */
const actionOptions = computed(() => {
	const seen = Array.from(new Set(rows.value.map((r) => r.Action).filter(Boolean)));
	return seen.map((v) => ({ value: v as string, label: actionLabel(v as string) })).sort((a, b) => a.label.localeCompare(b.label));
});

/**
 * 把 Detail 的 JSON 字符串变成 [{k, v}] 列表。
 *
 * ⚠️ 必须 try/catch：Detail 是 LONGTEXT 里的**原始字符串**，后端刻意不做解析
 *    （一段坏 JSON 不该让整个日志列表 500）。所以坏数据是会流到前端的，
 *    这里解析失败就返回空数组，退回显示 Message，不能让页面崩掉。
 */
const detailItems = (row: any): { k: string; v: string }[] => {
	if (!row?.Detail) return [];
	try {
		const obj = typeof row.Detail === 'string' ? JSON.parse(row.Detail) : row.Detail;
		if (!obj || typeof obj !== 'object') return [];
		return Object.entries(obj)
			// 空值不显示：详情里大量 null/false 会淹没关键信息
			.filter(([, v]) => v !== null && v !== undefined && v !== '')
			.map(([k, v]) => ({ k, v: Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v) }));
	} catch {
		return [];
	}
};

const hasFilter = computed(() => !!(keyword.value.trim() || filterAction.value || filterResult.value));

const clearFilters = () => {
	keyword.value = '';
	filterAction.value = '';
	filterResult.value = '';
};

/** 前端筛选：动作 + 结果 + 关键字（命中用户名/对象/详情/消息） */
const filtered = computed(() => {
	const k = keyword.value.trim().toLowerCase();
	return rows.value.filter((r) => {
		if (filterAction.value && r.Action !== filterAction.value) return false;
		if (filterResult.value && r.Result !== filterResult.value) return false;
		if (!k) return true;
		const hay = [r.Username, r.Target, r.Message, r.Detail, r.ClientIP, actionLabel(r.Action)]
			.filter(Boolean)
			.join(' ')
			.toLowerCase();
		return hay.includes(k);
	});
});

const kpis = computed(() => {
	const total = rows.value.length;
	const failed = rows.value.filter((r) => r.Result && r.Result !== '成功');
	// ⚠️ 失败里绝大多数是**登录失败**（口令输错、账号停用），属于日常噪音，
	//    不是"系统出了问题"。把它们和业务失败混在一个数字里会误导排查方向，
	//    所以拆成两个指标：业务失败才是真正"需要关注"的。
	const bizFailed = failed.filter((r) => r.Action !== 'login').length;
	const loginFailed = failed.length - bizFailed;
	const writers = new Set(rows.value.map((r) => r.Username).filter(Boolean)).size;
	return [
		{ label: '日志条数', value: total, hint: `最多显示 ${limit} 条`, tone: '' },
		{ label: '业务失败', value: bizFailed, hint: '训练/模型/数据集操作失败', tone: bizFailed > 0 ? 'warn' : '' },
		{ label: '登录失败', value: loginFailed, hint: '口令错误或账号停用', tone: '' },
		{ label: '操作人数', value: writers, hint: '去重后的账号数', tone: '' },
	];
});

/** MySQL DATETIME(6) 字符串，截到秒即可；微秒对人没意义 */
const fmtTime = (t: any) => (t ? String(t).replace('T', ' ').slice(0, 19) : '—');

/** 失败行淡红底：一屏之内肉眼就能定位问题操作 */
const rowClass = ({ row }: any) => (row.Result && row.Result !== '成功' ? 'row-failed' : '');

const load = async () => {
	loading.value = true;
	error.value = '';
	try {
		const res: any = await platformApi.operationLogs(limit);
		// ⚠️ 只看 code，不看 HTTP 状态码（后端失败也是 200）
		if (res && res.code === 2000) {
			rows.value = res.data?.results || [];
		} else {
			error.value = res?.msg || '加载操作日志失败';
		}
	} catch (e: any) {
		// 走到这里说明是网络/401 层的问题（权限不足是 code 4000，走不到这里）
		error.value = e?.message || String(e);
		ElMessage.error(error.value);
	} finally {
		loading.value = false;
	}
};

onMounted(load);
defineExpose({ load });
</script>

<style scoped lang="scss">
.mb { margin-bottom: 16px; }
.alert-body { font-size: 12px; line-height: 1.8; }
.alert-body code {
	background: var(--el-fill-color);
	padding: 1px 5px;
	border-radius: 3px;
}
.card-head {
	display: flex;
	align-items: center;
	gap: 10px;
}
.card-head .hint { color: var(--el-text-color-secondary); font-size: 12px; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
.mono { font-family: ui-monospace, Consolas, Monaco, monospace; }
.kpi-card { text-align: center; }
.kpi-label { color: var(--el-text-color-secondary); font-size: 13px; }
.kpi-value { font-size: 26px; font-weight: 600; line-height: 1.4; }
.kpi-value.warn { color: var(--el-color-danger); }
.kpi-hint { color: var(--el-text-color-placeholder); font-size: 12px; }

/* 表格里的次要小字（角色名、原始 action key） */
.cell-sub { color: var(--el-text-color-placeholder); font-size: 11px; line-height: 1.4; }

/* 详情列：key=value 用标签式排布，比一整行 JSON 好扫读 */
.detail { display: flex; flex-wrap: wrap; gap: 4px 8px; }
.detail-pair {
	display: inline-flex;
	align-items: baseline;
	gap: 3px;
	font-size: 12px;
	background: var(--el-fill-color-light);
	border-radius: 3px;
	padding: 1px 6px;
}
.detail-k { color: var(--el-text-color-secondary); }
.detail-v { color: var(--el-text-color-primary); font-weight: 500; }

/* 失败行淡红底，便于快速定位异常操作 */
:deep(.row-failed) { background: var(--el-color-danger-light-9); }
</style>
