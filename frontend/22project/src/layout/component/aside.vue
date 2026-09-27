<template>
	<div class="h100" v-show="!isTagsViewCurrenFull">
		<el-aside class="layout-aside" :class="setCollapseStyle">
			<Logo v-if="setShowLogo" />
			<el-scrollbar class="flex-auto" ref="layoutAsideScrollbarRef" @mouseenter="onAsideEnterLeave(true)" @mouseleave="onAsideEnterLeave(false)">
				<Vertical :menuList="state.menuList" />
			</el-scrollbar>
			<!-- 左下角：退出登录。
			     ⚠️ 放在滚动区**外面**：菜单再长它也不会被顶走，始终钉在侧边栏底部。 -->
			<div class="aside-logout" v-if="showAsideLogout">
				<el-tooltip content="退出登录" placement="right" :disabled="!isCollapse">
					<el-button text class="aside-logout-btn" :class="{ 'is-collapse': isCollapse }" @click="onLogout">
						<SvgIcon name="ele-SwitchButton" :size="16" />
						<span class="aside-logout-text" v-show="!isCollapse">退出登录</span>
					</el-button>
				</el-tooltip>
			</div>
		</el-aside>
	</div>
</template>

<script setup lang="ts" name="layoutAside">
import { defineAsyncComponent, reactive, computed, watch, onBeforeMount, ref } from 'vue';
import { storeToRefs } from 'pinia';
import pinia from '/@/stores/index';
import { useRoutesList } from '/@/stores/routesList';
import { useThemeConfig } from '/@/stores/themeConfig';
import { useTagsViewRoutes } from '/@/stores/tagsViewRoutes';
import mittBus from '/@/utils/mitt';
import { useRoute } from 'vue-router';
import { doLogout } from '/@/utils/logout';
const route = useRoute();
// 引入组件
const Logo = defineAsyncComponent(() => import('/@/layout/logo/index.vue'));
const Vertical = defineAsyncComponent(() => import('/@/layout/navMenu/vertical.vue'));

// 定义变量内容
const layoutAsideScrollbarRef = ref();
const routesIndex = ref(0);
const stores = useRoutesList();
const storesThemeConfig = useThemeConfig();
const storesTagsViewRoutes = useTagsViewRoutes();
const { routesList } = storeToRefs(stores);
const { themeConfig } = storeToRefs(storesThemeConfig);
const { isTagsViewCurrenFull } = storeToRefs(storesTagsViewRoutes);
const state = reactive<AsideState>({
	menuList: [],
	clientWidth: 0,
});

// 设置菜单展开/收起时的宽度
const setCollapseStyle = computed(() => {
	const { layout, isCollapse, menuBar } = themeConfig.value;
	const asideBrTheme = ['#FFFFFF', '#FFF', '#fff', '#ffffff'];
	const asideBrColor = asideBrTheme.includes(menuBar) ? 'layout-el-aside-br-color' : '';
	// 判断是否是手机端
	if (state.clientWidth <= 1000) {
		if (isCollapse) {
			document.body.setAttribute('class', 'el-popup-parent--hidden');
			const asideEle = document.querySelector('.layout-container') as HTMLElement;
			const modeDivs = document.createElement('div');
			modeDivs.setAttribute('class', 'layout-aside-mobile-mode');
			asideEle.appendChild(modeDivs);
			modeDivs.addEventListener('click', closeLayoutAsideMobileMode);
			return [asideBrColor, 'layout-aside-mobile', 'layout-aside-mobile-open'];
		} else {
			// 关闭弹窗
			closeLayoutAsideMobileMode();
			return [asideBrColor, 'layout-aside-mobile', 'layout-aside-mobile-close'];
		}
	} else {
		if (layout === 'columns') {
			// 分栏布局，菜单收起时宽度给 1px
			if (isCollapse) return [asideBrColor, 'layout-aside-pc-1'];
			else return [asideBrColor, 'layout-aside-pc-220'];
		} else {
			// 其它布局给 64px
			if (isCollapse) return [asideBrColor, 'layout-aside-pc-64'];
			else return [asideBrColor, 'layout-aside-pc-220'];
		}
	}
});
// 设置显示/隐藏 logo
const setShowLogo = computed(() => {
	let { layout, isShowLogo } = themeConfig.value;
	return (isShowLogo && layout === 'defaults') || (isShowLogo && layout === 'columns');
});
// 当前是否处于收起状态（收起时左下角按钮只留图标）
const isCollapse = computed(() => !!themeConfig.value.isCollapse);
// 是否渲染左下角的退出按钮。
// ⚠️ columns 布局收起时 el-aside 只有 **1px**（一级菜单在那条窄栏里，这个 aside 只放二级菜单），
//    此时按钮既看不见也点不到，干脆不渲染 —— 免得留一个能撑高布局、还可能引出滚动条的元素。
const showAsideLogout = computed(
	() => !(themeConfig.value.layout === 'columns' && themeConfig.value.isCollapse)
);
// 退出登录：确认框、通知服务端、清本地令牌、整页回登录页，都在 utils/logout.ts 里
const onLogout = () => doLogout();
// 关闭移动端蒙版
const closeLayoutAsideMobileMode = () => {
	const el = document.querySelector('.layout-aside-mobile-mode');
	el?.setAttribute('style', 'animation: error-img-two 0.3s');
	setTimeout(() => {
		el?.parentNode?.removeChild(el);
	}, 300);
	const clientWidth = document.body.clientWidth;
	if (clientWidth < 1000) themeConfig.value.isCollapse = false;
	document.body.setAttribute('class', '');
};
const findFirstLevelIndex = (data, path) => {
	for (let index = 0; index < data.length; index++) {
		const item = data[index];
    // 检查当前菜单项是否有子菜单，并查找是否在子菜单中找到路径
		if (item.children && item.children.length > 0) {
			// 检查子菜单中是否有匹配的路径
			const childIndex = item.children.findIndex((child) => child.path === path);
			if (childIndex !== -1) {
				return index; // 返回当前一级菜单的索引
			}
			// 递归查找子菜单
			const foundIndex = findFirstLevelIndex(item.children, path);
			if (foundIndex !== null) {
				return index; // 返回找到的索引
			}
		}
	}
	return null; // 找不到路径时返回 null
};
// 设置/过滤路由（非静态路由/是否显示在菜单中）
const setFilterRoutes = (path='') => {
	if (themeConfig.value.layout === 'columns') return false;
	let { layout, isClassicSplitMenu } = themeConfig.value;
	if (layout === 'classic' && isClassicSplitMenu) {
		// 获取当前地址的索引，不用从参数选取
    routesIndex.value = findFirstLevelIndex(routesList.value,path || route.path) || 0
		state.menuList = filterRoutesFun(routesList.value[routesIndex.value].children || [routesList.value[routesIndex.value]]);
	} else {
		state.menuList = filterRoutesFun(routesList.value);
	}
};
// 路由过滤递归函数
const filterRoutesFun = <T extends RouteItem>(arr: T[]): T[] => {
	return arr
		.filter((item: T) => !item.meta?.isHide)
		.map((item: T) => {
			item = Object.assign({}, item);
			if (item.children) item.children = filterRoutesFun(item.children);
			return item;
		});
};
// 设置菜单导航是否固定（移动端）
const initMenuFixed = (clientWidth: number) => {
	state.clientWidth = clientWidth;
};
// 鼠标移入、移出
const onAsideEnterLeave = (bool: Boolean) => {
	let { layout } = themeConfig.value;
	if (layout !== 'columns') return false;
	if (!bool) mittBus.emit('restoreDefault');
	stores.setColumnsMenuHover(bool);
};
// 页面加载前
onBeforeMount(() => {
	initMenuFixed(document.body.clientWidth);
	setFilterRoutes();
	// 此界面不需要取消监听(mittBus.off('setSendColumnsChildren))
	// 因为切换布局时有的监听需要使用，取消了监听，某些操作将不生效
	mittBus.on('setSendColumnsChildren', (res: MittMenu) => {
		state.menuList = res.children;
	});
	mittBus.on('setSendClassicChildren', (res: MittMenu) => {
		let { layout, isClassicSplitMenu } = themeConfig.value;
		if (layout === 'classic' && isClassicSplitMenu) {
			state.menuList = [];
			// state.menuList = res.children;
			setFilterRoutes(res.path);
		}
	});
	mittBus.on('getBreadcrumbIndexSetFilterRoutes', () => {
		setFilterRoutes();
	});
	mittBus.on('layoutMobileResize', (res: LayoutMobileResize) => {
		initMenuFixed(res.clientWidth);
		closeLayoutAsideMobileMode();
	});
});
// 监听 themeConfig 配置文件的变化，更新菜单 el-scrollbar 的高度
watch(themeConfig.value, (val) => {
	if (val.isShowLogoChange !== val.isShowLogo) {
		if (layoutAsideScrollbarRef.value) layoutAsideScrollbarRef.value.update();
	}
});
// 监听 pinia 值的变化，动态赋值给菜单中
watch(
	pinia.state,
	(val) => {
		let { layout, isClassicSplitMenu } = val.themeConfig.themeConfig;
		if (layout === 'classic' && isClassicSplitMenu) return false;
		setFilterRoutes();
	},
	{
		deep: true,
	}
);
</script>

<style scoped lang="scss">
/* 侧边栏左下角的退出登录。
   ⚠️ 颜色**全部走主题变量**（`--next-bg-menuBar*`），不要写死 Element Plus 的浅色变量：
      菜单栏的颜色可以在「布局设置」里被改成深色/渐变（见 stores/themeConfig 的 menuBar），
      写死浅色的话深色菜单下这个按钮会突兀地亮一块。
      `--next-bg-menuBarActiveColor` 是个半透明叠加色，正好当 hover 底色和分隔线用，
      在浅色和深色菜单栏上都成立。 */
.aside-logout {
	flex: 0 0 auto; // 不被上面的滚动区挤扁，钉在底部
	padding: 8px;
	border-top: 1px solid var(--next-bg-menuBarActiveColor);
	user-select: none;
}
.aside-logout-btn {
	width: 100%;
	height: 38px;
	justify-content: flex-start;
	gap: 10px;
	padding: 0 12px;
	color: var(--next-bg-menuBarColor);
	--el-button-text-color: var(--next-bg-menuBarColor);
	--el-button-hover-text-color: var(--next-bg-menuBarColor);
	--el-button-hover-bg-color: var(--next-bg-menuBarActiveColor);
	--el-button-active-bg-color: var(--next-bg-menuBarActiveColor);

	// 收起状态（64px）只显示图标：居中，别让图标贴着左边
	&.is-collapse {
		justify-content: center;
		padding: 0;
	}
}
// 收起时藏掉文字（v-show 已经控制渲染，这里再兜一层，避免宽度抖动时露出来）
.aside-logout-btn.is-collapse .aside-logout-text {
	display: none;
}
</style>
