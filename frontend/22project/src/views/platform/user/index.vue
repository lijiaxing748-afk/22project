<template>
	<div class="platform-user">
		<!-- 顶部说明：把这个页面的能力边界讲清楚，避免误以为可以物理删除 -->
		<el-alert type="info" :closable="false" show-icon class="mb">
			<template #title>
				这里可以<b>新建账号、调整角色、启停用户、重置密码</b>，无需再手工操作数据库。
			</template>
			<template #default>
				<div class="alert-body">
					出于审计留痕考虑，本平台<b>不提供物理删除用户</b>——账号一旦创建，
					其操作记录就需要能被追溯。要"移除"某个账号，请用<b>停用</b>：
					停用后无法登录，但历史记录里的操作人依然查得到。
					<br />
					角色权限由代码统一定义（<code>model_service/auth.py</code>），
					这里只能选择角色，不能逐项勾选权限点。
				</div>
			</template>
		</el-alert>

		<!-- KPI 四连：一眼看出账号家底 -->
		<el-row :gutter="16" class="mb">
			<el-col :xs="12" :sm="6" v-for="k in kpis" :key="k.label">
				<el-card shadow="never" class="kpi-card">
					<div class="kpi-label">{{ k.label }}</div>
					<div class="kpi-value">{{ k.value }}</div>
					<div class="kpi-hint">{{ k.hint }}</div>
				</el-card>
			</el-col>
		</el-row>

		<el-card shadow="never">
			<template #header>
				<div class="card-head">
					<span>用户列表</span>
					<span class="hint">共 {{ rows.length }} 个账号</span>
					<div style="float: right">
						<el-input
							v-model="keyword"
							placeholder="搜索用户名 / 显示名"
							clearable
							style="width: 220px; margin-right: 8px"
							:prefix-icon="Search"
						/>
						<el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
						<el-button :loading="loading" @click="load">刷新</el-button>
					</div>
				</div>
			</template>

			<!-- 首次加载骨架屏；失败时给明确错误，而不是空表 -->
			<el-skeleton v-if="loading && !rows.length" :rows="4" animated />

			<el-alert v-else-if="error" type="error" :closable="false" show-icon
				:title="error"
				description="如果提示没有权限，请用 admin 账号登录后重试。" />

			<el-empty v-else-if="!filtered.length" :description="keyword ? '没有匹配的用户' : '暂无用户'" />

			<el-table v-else :data="filtered" size="default" stripe>
				<el-table-column prop="username" label="用户名" min-width="130">
					<template #default="{ row }">
						<span class="mono">{{ row.username }}</span>
						<!-- 当前登录的自己打个标记，避免误操作（编辑/停用自己会被后端拦） -->
						<el-tag v-if="row.username === me" type="primary" size="small" effect="dark"
							style="margin-left: 6px">当前</el-tag>
					</template>
				</el-table-column>

				<el-table-column prop="name" label="显示名" min-width="120">
					<template #default="{ row }">
						<span v-if="row.name && row.name !== row.username">{{ row.name }}</span>
						<span v-else class="hint">—</span>
					</template>
				</el-table-column>

				<el-table-column label="角色" min-width="130">
					<template #default="{ row }">
						<el-tag :type="roleTagType(row.role_info?.key)" size="small">
							{{ row.role_info?.name || row.role_info?.key || '—' }}
						</el-tag>
					</template>
				</el-table-column>

				<el-table-column label="状态" width="90" align="center">
					<template #default="{ row }">
						<el-tag :type="row.is_active ? 'success' : 'info'" size="small">
							{{ row.is_active ? '正常' : '已停用' }}
						</el-tag>
					</template>
				</el-table-column>

				<el-table-column label="最近登录" width="160">
					<template #default="{ row }">
						<span v-if="row.last_login">{{ fmtTime(row.last_login) }}</span>
						<span v-else class="hint">从未登录</span>
					</template>
				</el-table-column>

				<el-table-column prop="login_count" label="登录次数" width="100" align="center">
					<template #default="{ row }">{{ row.login_count ?? 0 }}</template>
				</el-table-column>

				<el-table-column label="操作" width="250" align="center" fixed="right">
					<template #default="{ row }">
						<el-button link type="primary" @click="openEdit(row)">编辑</el-button>
						<el-button link type="primary" @click="openReset(row)">重置密码</el-button>
						<el-button
							link
							:type="row.is_active ? 'warning' : 'success'"
							:disabled="row.username === me"
							@click="toggleActive(row)">
							{{ row.is_active ? '停用' : '启用' }}
						</el-button>
					</template>
				</el-table-column>
			</el-table>
		</el-card>

		<!-- ============ 新建用户 ============ -->
		<el-dialog v-model="create.visible" title="新建用户" width="520px" :close-on-click-modal="false">
			<el-form :model="create.form" label-width="90px" :rules="rules" ref="createRef">
				<el-form-item label="用户名" prop="username">
					<el-input v-model="create.form.username" placeholder="登录账号，建议英文，如 zhangsan" />
				</el-form-item>
				<el-form-item label="显示名" prop="name">
					<el-input v-model="create.form.name" placeholder="选填，如 张三" />
				</el-form-item>
				<el-form-item label="密码" prop="password">
					<el-input v-model="create.form.password" type="password" show-password
						placeholder="至少 6 位" />
				</el-form-item>
				<el-form-item label="确认密码" prop="password2">
					<el-input v-model="create.form.password2" type="password" show-password
						placeholder="再输一遍" />
				</el-form-item>
				<el-form-item label="角色" prop="role_key">
					<el-select v-model="create.form.role_key" placeholder="请选择角色" style="width: 100%">
						<el-option v-for="r in roles" :key="r.key" :label="r.name" :value="r.key">
							<span style="float: left">{{ r.name }}</span>
							<span class="hint" style="float: right; margin-left: 12px">{{ r.key }}</span>
						</el-option>
					</el-select>
					<div class="form-hint">{{ roleHint(create.form.role_key) }}</div>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="create.visible = false">取消</el-button>
				<el-button type="primary" :loading="create.saving" @click="submitCreate">确定</el-button>
			</template>
		</el-dialog>

		<!-- ============ 编辑用户 ============ -->
		<el-dialog v-model="edit.visible" title="编辑用户" width="520px" :close-on-click-modal="false">
			<el-form :model="edit.form" label-width="90px">
				<el-form-item label="用户名">
					<!-- 用户名是登录凭据，也是审计记录里的操作人，**不可改** -->
					<el-input :model-value="edit.form.username" disabled />
					<div class="form-hint">用户名是登录凭据与审计记录的操作人，创建后不可修改。</div>
				</el-form-item>
				<el-form-item label="显示名">
					<el-input v-model="edit.form.name" placeholder="选填，如 张三" />
				</el-form-item>
				<el-form-item label="角色">
					<el-select v-model="edit.form.role_key" style="width: 100%"
						:disabled="edit.form.username === me">
						<el-option v-for="r in roles" :key="r.key" :label="r.name" :value="r.key" />
					</el-select>
					<div v-if="edit.form.username === me" class="form-hint warn">
						不能修改自己的角色——避免把自己降权后无法恢复。要转移管理权限，请用另一个管理员账号操作。
					</div>
					<div v-else class="form-hint">{{ roleHint(edit.form.role_key) }}</div>
				</el-form-item>
				<el-form-item label="状态">
					<el-switch v-model="edit.form.is_active" :disabled="edit.form.username === me"
						active-text="正常" inactive-text="停用" />
					<div v-if="edit.form.username === me" class="form-hint warn">不能停用自己。</div>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="edit.visible = false">取消</el-button>
				<el-button type="primary" :loading="edit.saving" @click="submitEdit">保存</el-button>
			</template>
		</el-dialog>

		<!-- ============ 重置密码 ============ -->
		<el-dialog v-model="reset.visible" title="重置密码" width="480px" :close-on-click-modal="false">
			<el-alert type="warning" :closable="false" show-icon class="mb"
				title="重置后该用户的当前登录会立即失效，需要用新密码重新登录。" />
			<el-form :model="reset.form" label-width="90px">
				<el-form-item label="用户">
					<el-input :model-value="reset.form.username" disabled />
				</el-form-item>
				<el-form-item label="新密码">
					<el-input v-model="reset.form.password" type="password" show-password placeholder="至少 6 位" />
				</el-form-item>
				<el-form-item label="确认密码">
					<el-input v-model="reset.form.password2" type="password" show-password placeholder="再输一遍" />
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="reset.visible = false">取消</el-button>
				<el-button type="primary" :loading="reset.saving" @click="submitReset">确定重置</el-button>
			</template>
		</el-dialog>
	</div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus';
import { Plus, Search } from '@element-plus/icons-vue';
import { platformApi } from '/@/api/platform';
import { Session } from '/@/utils/storage';

/**
 * 用户管理页
 *
 * ⚠️ 这一组接口走的是 dvadmin 的**信封协议** `{code, data, msg}`，而且**失败也回 HTTP 200**
 *    （见 dvadmin.py 里的 _ok）。所以判断成败必须看 `code === 2000`，
 *    不能靠 try/catch 或 HTTP 状态码——后端说"用户名已存在"时 HTTP 是 200，
 *    只有 code 不是 2000。这一点和平台其它接口（裸 JSON + HTTP 状态码）完全不同。
 */

const rows = ref<any[]>([]);
const roles = ref<any[]>([]);
const loading = ref(false);
const error = ref('');
const keyword = ref('');

/** 当前登录用户名：用于标记"自己"，并前置禁用会导致自锁的操作 */
const me = ref(Session.get('userInfo')?.username || '');

const createRef = ref<FormInstance>();

const create = reactive({ visible: false, saving: false, form: { username: '', name: '', password: '', password2: '', role_key: '' } });
const edit = reactive({ visible: false, saving: false, form: { id: 0, username: '', name: '', role_key: '', is_active: true } });
const reset = reactive({ visible: false, saving: false, form: { id: 0, username: '', password: '', password2: '' } });

/** 表单校验：密码必须两次一致，且至少 6 位（与后端 user_create 的校验保持一致） */
const rules = {
	username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
	password: [
		{ required: true, message: '请输入密码', trigger: 'blur' },
		{ min: 6, message: '密码至少 6 位', trigger: 'blur' },
	],
	password2: [
		{
			validator: (_r: any, v: string, cb: any) =>
				v !== create.form.password ? cb(new Error('两次输入的密码不一致')) : cb(),
			trigger: 'blur',
		},
	],
	role_key: [{ required: true, message: '请选择角色', trigger: 'change' }],
};

const filtered = computed(() => {
	const k = keyword.value.trim().toLowerCase();
	if (!k) return rows.value;
	return rows.value.filter(
		(r) =>
			String(r.username || '').toLowerCase().includes(k) ||
			String(r.name || '').toLowerCase().includes(k)
	);
});

const kpis = computed(() => {
	const total = rows.value.length;
	const active = rows.value.filter((r) => r.is_active).length;
	const admins = rows.value.filter((r) => r.role_info?.key === 'admin').length;
	return [
		{ label: '账号总数', value: total, hint: 'Users 表全部记录' },
		{ label: '正常账号', value: active, hint: '可登录' },
		{ label: '已停用', value: total - active, hint: '不能登录，记录保留' },
		{ label: '管理员', value: admins, hint: '拥有全部权限' },
	];
});

const ROLE_DESC: Record<string, string> = {
	admin: '拥有全部权限，含用户管理与操作日志查看',
	engineer: '可训练、推理、发布/删除模型，上传数据集',
	operator: '只能查看模型与发起推理，不能训练或发布',
};

const roleHint = (key: string) => ROLE_DESC[key] || '';
const roleTagType = (key: string) => (key === 'admin' ? 'danger' : key === 'engineer' ? 'warning' : 'info');

/** 后端给的是 MySQL DATETIME 字符串（本地时间），截到分钟即可 */
const fmtTime = (t: any) => (t ? String(t).slice(0, 16) : '—');

/**
 * 解析信封响应。
 *
 * ⚠️ 判成败**只看 code**，不看 HTTP 状态码，也**不要用 `data` 是否有值来判断**：
 *    后端 `_fail()` 回的是 `{code:4000, data:null, msg:"..."}`，
 *    而 `_ok(None, "密码已重置…")` 回的是 `{code:2000, data:null, msg:"..."}`——
 *    两者 data 都是 null。若拿 data 判成败，"重置成功"会被误报成失败。
 *
 * @returns 成功时返回 data（可能是 null），失败时返回 FAILED 并把 msg 抛给调用方
 */
const FAILED = Symbol('failed');

const unwrap = (res: any, fallbackMsg = '操作失败'): any => {
	if (res && res.code === 2000) return res.data;
	ElMessage.error(res?.msg || fallbackMsg);
	return FAILED;
};

const rejected = (res: any) => !(res && res.code === 2000);

const load = async () => {
	loading.value = true;
	error.value = '';
	try {
		// 角色与用户都拉：角色给下拉框用（后端在库为空时会用代码定义兜底）
		const [uRes, rRes] = await Promise.all([platformApi.userList(), platformApi.roleList()]);
		if (rejected(uRes)) {
			error.value = uRes?.msg || '加载用户列表失败';
			return;
		}
		rows.value = uRes.data?.results || [];
		// 角色拉不到不阻塞页面：只影响下拉框，给个空数组即可
		if (!rejected(rRes)) roles.value = rRes.data?.results || [];
	} catch (e: any) {
		// 走到这里说明是网络/401 层的问题（权限不足是 code 4000，走不到这里）
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
};

const openCreate = () => {
	create.form = { username: '', name: '', password: '', password2: '', role_key: 'operator' };
	create.visible = true;
};

const submitCreate = async () => {
	if (!createRef.value) return;
	await createRef.value.validate(async (ok) => {
		if (!ok) return;
		create.saving = true;
		try {
			const data = unwrap(
				await platformApi.createUser({
					username: create.form.username.trim(),
					password: create.form.password,
					role_key: create.form.role_key,
					name: create.form.name.trim(),
				}),
				'新建失败'
			);
			if (data !== FAILED) {
				ElMessage.success('已新建用户');
				create.visible = false;
				await load();
			}
		} catch (e: any) {
			ElMessage.error(e?.message || String(e));
		} finally {
			create.saving = false;
		}
	});
};

const openEdit = (row: any) => {
	edit.form = {
		id: row.id,
		username: row.username,
		name: row.name === row.username ? '' : row.name || '',
		role_key: row.role_info?.key || '',
		is_active: !!row.is_active,
	};
	edit.visible = true;
};

const submitEdit = async () => {
	edit.saving = true;
	try {
		// 只提交**有变化**的字段：后端对"没有要修改的内容"会直接回 msg，
		// 全量提交会让"只改了显示名"这种操作也触发角色/状态分支。
		const payload: any = {};
		const orig = rows.value.find((r) => r.id === edit.form.id);
		const newName = edit.form.name.trim() || null;
		if (orig && (orig.name || '') !== (newName || '')) payload.name = edit.form.name.trim();
		if (orig && (orig.role_info?.key || '') !== edit.form.role_key) payload.role_key = edit.form.role_key;
		if (orig && !!orig.is_active !== edit.form.is_active) payload.is_active = edit.form.is_active;

		if (!Object.keys(payload).length) {
			ElMessage.info('没有要修改的内容');
			edit.visible = false;
			return;
		}
		const data = unwrap(await platformApi.updateUser(edit.form.id, payload), '保存失败');
		if (data !== FAILED) {
			ElMessage.success('已保存');
			edit.visible = false;
			await load();
		}
	} catch (e: any) {
		ElMessage.error(e?.message || String(e));
	} finally {
		edit.saving = false;
	}
};

const openReset = (row: any) => {
	reset.form = { id: row.id, username: row.username, password: '', password2: '' };
	reset.visible = true;
};

const submitReset = async () => {
	if (reset.form.password.length < 6) {
		ElMessage.warning('新密码至少 6 位');
		return;
	}
	if (reset.form.password !== reset.form.password2) {
		ElMessage.warning('两次输入的密码不一致');
		return;
	}
	reset.saving = true;
	try {
		const res: any = await platformApi.resetUserPassword(reset.form.id, reset.form.password);
		// ⚠️ 重置成功的 data 就是 null（后端 `_ok(None, "密码已重置…")`），
		//    所以**不能**用 `if (data)` 判断——那样成功也会被当成失败。
		//    必须看信封里的 code。
		if (res && res.code === 2000) {
			ElMessage.success('密码已重置，该用户的登录会立即失效');
			reset.visible = false;
		} else {
			ElMessage.error(res?.msg || '重置失败');
		}
	} catch (e: any) {
		ElMessage.error(e?.message || String(e));
	} finally {
		reset.saving = false;
	}
};

/** 启用 / 停用。停用是"移除账号"的推荐做法——保留审计痕迹 */
const toggleActive = async (row: any) => {
	const next = !row.is_active;
	try {
		await ElMessageBox.confirm(
			next
				? `确定要启用「${row.username}」吗？启用后该账号可以登录。`
				: `确定要停用「${row.username}」吗？停用后该账号将无法登录，但历史操作记录会保留。`,
			next ? '启用账号' : '停用账号',
			{ type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
		);
	} catch {
		return; // 用户取消
	}
	try {
		const data = unwrap(await platformApi.updateUser(row.id, { is_active: next }), '操作失败');
		if (data !== FAILED) {
			ElMessage.success(next ? '已启用' : '已停用');
			await load();
		}
	} catch (e: any) {
		ElMessage.error(e?.message || String(e));
	}
};

onMounted(load);

/** 供模板里 el-input 的 prefix-icon 用 */
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
.kpi-hint { color: var(--el-text-color-placeholder); font-size: 12px; }
.form-hint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.form-hint.warn { color: var(--el-color-warning); }
</style>

