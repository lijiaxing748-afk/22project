<template>
	<div class="layout-navbars-breadcrumb-user pr15" :style="{ flex: layoutUserFlexNum }">
		<el-dropdown :show-timeout="70" :hide-timeout="50" trigger="click" @command="onComponentSizeChange">
			<div class="layout-navbars-breadcrumb-user-icon">
				<i class="iconfont icon-ziti" :title="$t('message.user.title0')"></i>
			</div>
			<template #dropdown>
				<el-dropdown-menu>
					<el-dropdown-item command="large" :disabled="state.disabledSize === 'large'">{{ $t('message.user.dropdownLarge') }}</el-dropdown-item>
					<el-dropdown-item command="default" :disabled="state.disabledSize === 'default'">{{ $t('message.user.dropdownDefault') }}</el-dropdown-item>
					<el-dropdown-item command="small" :disabled="state.disabledSize === 'small'">{{ $t('message.user.dropdownSmall') }}</el-dropdown-item>
				</el-dropdown-menu>
			</template>
		</el-dropdown>
		<el-dropdown :show-timeout="70" :hide-timeout="50" trigger="click" @command="onLanguageChange">
			<div class="layout-navbars-breadcrumb-user-icon">
				<i
					class="iconfont"
					:class="state.disabledI18n === 'en' ? 'icon-fuhao-yingwen' : 'icon-fuhao-zhongwen'"
					:title="$t('message.user.title1')"
				></i>
			</div>
			<template #dropdown>
				<el-dropdown-menu>
					<el-dropdown-item command="zh-cn" :disabled="state.disabledI18n === 'zh-cn'">简体中文</el-dropdown-item>
				</el-dropdown-menu>
			</template>
		</el-dropdown>
		<div class="layout-navbars-breadcrumb-user-icon" @click="onSearchClick">
			<el-icon :title="$t('message.user.title2')">
				<ele-Search />
			</el-icon>
		</div>
		<div class="layout-navbars-breadcrumb-user-icon" @click="onLayoutSetingClick">
			<i class="icon-skin iconfont" :title="$t('message.user.title3')"></i>
		</div>
		<!-- 消息铃铛与 SSE 已移除：消息中心页面没有了，且 /sse/ 是桩，连上就报错刷控制台 -->
		<div class="layout-navbars-breadcrumb-user-icon mr10" @click="onScreenfullClick">
			<i
				class="iconfont"
				:title="state.isScreenfull ? $t('message.user.title6') : $t('message.user.title5')"
				:class="!state.isScreenfull ? 'icon-fullscreen' : 'icon-tuichuquanping'"
			></i>
		</div>
		<div></div>
		<el-dropdown :show-timeout="70" :hide-timeout="50" @command="onHandleCommandClick">
			<span class="layout-navbars-breadcrumb-user-link">
				<el-badge is-dot class="item online-status">
					<img :src="userInfos.avatar || headerImage" class="layout-navbars-breadcrumb-user-link-photo mr5" />
				</el-badge>
				{{ userInfos.username === '' ? 'common' : userInfos.username }}
				<el-icon class="el-icon--right">
					<ele-ArrowDown />
				</el-icon>
			</span>
			<template #dropdown>
				<el-dropdown-menu>
					<el-dropdown-item command="/home">{{ $t('message.user.dropdown1') }}</el-dropdown-item>
					<!-- 「个人资料 / 修改密码」于 2026-09 恢复：
					     后端 update_user_info 与 change_password **本来就实现了**（真落库），
					     只是之前把入口删了，导致"改密码"只剩「初次登录强制改密」一条路，
					     登录之后想主动改密没有任何入口。 -->
					<el-dropdown-item divided command="profile">个人资料</el-dropdown-item>
					<el-dropdown-item command="changePwd">修改密码</el-dropdown-item>
					<el-dropdown-item command="/versionUpgradeLog">更新日志</el-dropdown-item>
					<el-dropdown-item divided command="logOut">{{ $t('message.user.dropdown5') }}</el-dropdown-item>
				</el-dropdown-menu>
			</template>
		</el-dropdown>
		<Search ref="searchRef" />

		<!-- 个人资料：只改显示名/邮箱/手机，改不了角色与密码 -->
		<el-dialog v-model="profile.visible" title="个人资料" width="420px" append-to-body>
			<el-form :model="profile.form" label-width="72px">
				<el-form-item label="账号">
					<el-input :model-value="userInfos.username" disabled />
				</el-form-item>
				<el-form-item label="姓名">
					<el-input v-model="profile.form.name" placeholder="显示名" clearable />
				</el-form-item>
				<el-form-item label="邮箱">
					<el-input v-model="profile.form.email" placeholder="可留空" clearable />
				</el-form-item>
				<el-form-item label="手机">
					<el-input v-model="profile.form.mobile" placeholder="可留空" clearable />
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="profile.visible = false">取消</el-button>
				<el-button type="primary" :loading="profile.loading" @click="submitProfile">保存</el-button>
			</template>
		</el-dialog>

		<!-- 修改密码 -->
		<el-dialog v-model="pwd.visible" title="修改密码" width="420px" append-to-body>
			<el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px"
				title="改完会让旧令牌立即失效（本页会自动换上后端下发的新令牌，不用重新登录）。" />
			<el-form :model="pwd.form" label-width="72px">
				<el-form-item label="原密码">
					<el-input v-model="pwd.form.old_password" type="password" show-password placeholder="当前密码" />
				</el-form-item>
				<el-form-item label="新密码">
					<el-input v-model="pwd.form.password" type="password" show-password placeholder="至少 6 位" />
				</el-form-item>
				<el-form-item label="确认">
					<el-input v-model="pwd.form.password_regain" type="password" show-password placeholder="再输一次新密码" />
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button @click="pwd.visible = false">取消</el-button>
				<el-button type="primary" :loading="pwd.loading" @click="submitPwd">确定</el-button>
			</template>
		</el-dialog>
	</div>
</template>

<script setup lang="ts" name="layoutBreadcrumbUser">
import { defineAsyncComponent, ref, computed, reactive, onMounted, unref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessageBox, ElMessage } from 'element-plus';
import screenfull from 'screenfull';
import { useI18n } from 'vue-i18n';
import { storeToRefs } from 'pinia';
import { useUserInfo } from '/@/stores/userInfo';
import { useThemeConfig } from '/@/stores/themeConfig';
import other from '/@/utils/other';
import mittBus from '/@/utils/mitt';
import { Session, Local } from '/@/utils/storage';
import headerImage from '/@/assets/img/headerImage.png';
import { InfoFilled } from '@element-plus/icons-vue';
import { updateUserInfo, changePassword } from '/@/api/system/user';
// 引入组件
	// UserNews（消息铃铛组件）已随消息中心一起移除
const Search = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/search.vue'));

// 定义变量内容
const { locale, t } = useI18n();
const router = useRouter();
const stores = useUserInfo();
const storesThemeConfig = useThemeConfig();
const { userInfos } = storeToRefs(stores);
const { themeConfig } = storeToRefs(storesThemeConfig);
const searchRef = ref();
const state = reactive({
	isScreenfull: false,
	disabledI18n: 'zh-cn',
	disabledSize: 'large',
});

// 设置分割样式
const layoutUserFlexNum = computed(() => {
	let num: string | number = '';
	const { layout, isClassicSplitMenu } = themeConfig.value;
	const layoutArr: string[] = ['defaults', 'columns'];
	if (layoutArr.includes(layout) || (layout === 'classic' && !isClassicSplitMenu)) num = '1';
	else num = '';
	return num;
});

// 全屏点击时
const onScreenfullClick = () => {
	if (!screenfull.isEnabled) {
		ElMessage.warning('暂不不支持全屏');
		return false;
	}
	screenfull.toggle();
	screenfull.on('change', () => {
		if (screenfull.isFullscreen) state.isScreenfull = true;
		else state.isScreenfull = false;
	});
};
// 布局配置 icon 点击时
const onLayoutSetingClick = () => {
	mittBus.emit('openSetingsDrawer');
};
// 下拉菜单点击时
const onHandleCommandClick = (path: string) => {
	if (path === 'logOut') {		ElMessageBox({
			closeOnClickModal: false,
			closeOnPressEscape: false,
			title: t('message.user.logOutTitle'),
			message: t('message.user.logOutMessage'),
			showCancelButton: true,
			confirmButtonText: t('message.user.logOutConfirm'),
			cancelButtonText: t('message.user.logOutCancel'),
			buttonSize: 'default',
			beforeClose: (action, instance, done) => {
				if (action === 'confirm') {
					instance.confirmButtonLoading = true;
					instance.confirmButtonText = t('message.user.logOutExit');
					setTimeout(() => {
						done();
						setTimeout(() => {
							instance.confirmButtonLoading = false;
						}, 300);
					}, 700);
				} else {
					done();
				}
			},
		})
			.then(async () => {
				// 清除缓存/token等
				Session.clear();
				// 使用 reload 时，不需要调用 resetRoute() 重置路由
				window.location.reload();
			})
			.catch(() => {});
	} else if (path === 'wareHouse') {
		window.open('https://gitee.com/huge-dream/django-vue3-admin');
	} else if (path === 'profile') {
		openProfile();
	} else if (path === 'changePwd') {
		openChangePwd();
	} else {
		router.push(path);
	}
};

// ---------------- 个人资料 ----------------
const profile = reactive({
	visible: false,
	loading: false,
	form: { name: '', email: '', mobile: '' },
});
const openProfile = () => {
	// 用 store 里的现值预填，避免"打开是空的、保存却把原有资料清掉"
	profile.form.name = userInfos.value.name || '';
	profile.form.email = userInfos.value.email || '';
	profile.form.mobile = userInfos.value.mobile || '';
	profile.visible = true;
};
const submitProfile = async () => {
	profile.loading = true;
	try {
		const res: any = await updateUserInfo({ ...profile.form });
		// 后端回的就是 login_payload 的形状（id/username/name/email/...），
		// 交给 store 自己的方法写回 —— 它会同时同步 Session 里的 userInfo。
		stores.updateUserInfos(res.data);
		ElMessage.success('已保存');
		profile.visible = false;
	} catch (e) {
		// 失败原因由 utils/service.ts 的拦截器统一弹出（code=4000 → errorCreate），这里不重复提示
	} finally {
		profile.loading = false;
	}
};

// ---------------- 修改密码 ----------------
const pwd = reactive({
	visible: false,
	loading: false,
	form: { old_password: '', password: '', password_regain: '' },
});
const openChangePwd = () => {
	pwd.form.old_password = '';
	pwd.form.password = '';
	pwd.form.password_regain = '';
	pwd.visible = true;
};
const submitPwd = async () => {
	// 前端先拦一道明显的手滑；**服务端同样会校验**（客户端校验可绕过，见 dvadmin.change_password）
	if (!pwd.form.old_password) return ElMessage.warning('请填写原密码');
	if (!pwd.form.password) return ElMessage.warning('请填写新密码');
	if (pwd.form.password.length < 6) return ElMessage.warning('新密码至少 6 位');
	if (pwd.form.password !== pwd.form.password_regain) return ElMessage.warning('两次输入的新密码不一致');
	pwd.loading = true;
	try {
		const res: any = await changePassword({ ...pwd.form });
		// ⚠️ 必须把后端下发的新令牌写回 Session：改密会让 TokenVersion+1，**旧令牌立即失效**，
		//    不换的话下一次请求就是"登录已失效"、人被弹回登录页（见 dvadmin.change_password 的说明）。
		if (res?.data?.access) Session.set('token', res.data.access);
		ElMessage.success('密码已修改');
		pwd.visible = false;
	} catch (e) {
		// 同上，错误提示由拦截器负责
	} finally {
		pwd.loading = false;
	}
};
// 菜单搜索点击
const onSearchClick = () => {
	searchRef.value.openSearch();
};
// 组件大小改变
const onComponentSizeChange = (size: string) => {
	Local.remove('themeConfig');
	themeConfig.value.globalComponentSize = size;
	Local.set('themeConfig', themeConfig.value);
	initI18nOrSize('globalComponentSize', 'disabledSize');
	window.location.reload();
};
// 语言切换
const onLanguageChange = (lang: string) => {
	Local.remove('themeConfig');
	themeConfig.value.globalI18n = lang;
	Local.set('themeConfig', themeConfig.value);
	locale.value = lang;
	other.useTitle();
	initI18nOrSize('globalI18n', 'disabledI18n');
};
// 初始化组件大小/i18n
const initI18nOrSize = (value: string, attr: keyof typeof state) => {
	const themeConfig = Local.get('themeConfig') as { [key: string]: any } | null;
	const configValue = ((themeConfig && themeConfig[value]) as string) || '';
	state[attr] = configValue as unknown as never;
};
// 页面加载时
onMounted(() => {
	if (Local.get('themeConfig')) {
		initI18nOrSize('globalComponentSize', 'disabledSize');
		initI18nOrSize('globalI18n', 'disabledI18n');
	}
});

// 原本这里有一大段「消息中心未读数」的 SSE 逻辑（new EventSource(.../sse/?token=...)）：
// 后端 /sse/ 只是个一次性空流桩，连上即关闭 → 控制台每次都刷 "SSE 错误"。
// 消息中心页面已移除，这段一并删掉，控制台干净了。
</script>

<style scoped lang="scss">
.layout-navbars-breadcrumb-user {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	&-link {
		height: 100%;
		display: flex;
		align-items: center;
		white-space: nowrap;
		&-photo {
			width: 25px;
			height: 25px;
			border-radius: 100%;
		}
	}
	&-icon {
		padding: 0 10px;
		cursor: pointer;
		color: var(--next-bg-topBarColor);
		height: 50px;
		line-height: 50px;
		display: flex;
		align-items: center;
		&:hover {
			background: var(--next-color-user-hover);
			i {
				display: inline-block;
				animation: logoAnimation 0.3s ease-in-out;
			}
		}
	}
	:deep(.el-dropdown) {
		color: var(--next-bg-topBarColor);
	}
	:deep(.el-badge) {
		height: 40px;
		line-height: 40px;
		display: flex;
		align-items: center;
	}
	:deep(.el-badge__content.is-fixed) {
		top: 12px;
	}
	.online-status {
		cursor: pointer;
		:deep(.el-badge__content.is-fixed) {
			top: 30px;
			font-size: 14px;
			left: 5px;
			height: 12px;
			width: 12px;
			padding: 0;
			background-color: #18bc9c;
		}
	}
	.online-down {
		cursor: pointer;
		:deep(.el-badge__content.is-fixed) {
			top: 30px;
			font-size: 14px;
			left: 5px;
			height: 12px;
			width: 12px;
			padding: 0;
			background-color: #979b9c;
		}
	}
}
</style>
