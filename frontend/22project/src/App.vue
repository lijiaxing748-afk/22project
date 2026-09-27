<template>
	<el-config-provider :size="getGlobalComponentSize" :locale="getGlobalI18n">
		<!-- v-show="themeConfig.lockScreenTime > 1" -->
		<router-view v-show="themeConfig.lockScreenTime > 1" />
		<LockScreen v-if="themeConfig.isLockScreen" />
		<Setings ref="setingsRef" v-show="themeConfig.lockScreenTime > 1" />
		<CloseFull v-if="!themeConfig.isLockScreen" />
<!--		<Upgrade v-if="getVersion" />-->
	</el-config-provider>
</template>

<script setup lang="ts" name="app">
import { defineAsyncComponent, computed, ref, onBeforeMount, onMounted, onUnmounted, nextTick, watch, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { storeToRefs } from 'pinia';
import { useTagsViewRoutes } from '/@/stores/tagsViewRoutes';
import { useThemeConfig } from '/@/stores/themeConfig';
import other from '/@/utils/other';
import { Local, Session } from '/@/utils/storage';
import mittBus from '/@/utils/mitt';
import setIntroduction from '/@/utils/setIconfont';
import { DEFAULT_LOCALE } from '/@/i18n/index';

// 引入组件
const LockScreen = defineAsyncComponent(() => import('/@/layout/lockScreen/index.vue'));
const Setings = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/setings.vue'));
const CloseFull = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/closeFull.vue'));
import { ElMessageBox, ElNotification, NotificationHandle } from 'element-plus';
import { useCore } from '/@/utils/cores';
// 定义变量内容
const { messages, locale } = useI18n();
const setingsRef = ref();
const route = useRoute();
const stores = useTagsViewRoutes();
const storesThemeConfig = useThemeConfig();
const { themeConfig } = storeToRefs(storesThemeConfig);
const core = useCore();
const router = useRouter();
// 获取版本号
const getVersion = computed(() => {
	let isVersion = false;
	if (route.path !== '/login') {
		// @ts-ignore
		if ((Local.get('version') && Local.get('version') !== __VERSION__) || !Local.get('version')) isVersion = true;
	}
	return isVersion;
});
// 获取全局组件大小
const getGlobalComponentSize = computed(() => {
	return other.globalComponentSize();
});
// 获取全局 i18n
const getGlobalI18n = computed(() => {
	return messages.value[locale.value];
});
// 设置初始化，防止刷新时恢复默认
onBeforeMount(() => {
	// 设置批量第三方 icon 图标
	setIntroduction.cssCdn();
	// 设置批量第三方 js
	setIntroduction.jsCdn();
});
// 页面加载时
onMounted(() => {
	nextTick(() => {
		// 监听布局配'置弹窗点击打开
		mittBus.on('openSetingsDrawer', () => {
			setingsRef.value.openDrawer();
		});
    // 设置皮肤缓存版本，每次更新版本可以所有用户清空缓存
    const themeConfigVersion = '1.0.0'
		// 获取缓存中的布局配置
    if (Local.get('themeConfigVersion') !== themeConfigVersion) {
        Local.clear();
        Local.set('themeConfigVersion', themeConfigVersion);
	      window.location.reload();
        return
    }
		if (Local.get('themeConfig')) {
			const saved = Local.get('themeConfig') as any;
			// ⚠️ 两点写法上的讲究：
			//    ① 用**合并**而不是整体替换：本地存的是**旧版本**的 themeConfig 时，
			//       整体替换会把后来新增的键从 store 里抹掉，下游取到 undefined
			//       就会出现"语言/尺寸莫名回默认"这类问题。合并后：老键以本地为准，新增键保留默认值。
			//    ② `globalI18n` **强制归一到当前语言**（DEFAULT_LOCALE，见 i18n/index.ts）：
			//       早期版本切过语言的话，存储里会留 `globalI18n: 'en'`。它现在虽然已经**失效**
			//       （语言在 i18n 创建时写死、"从存储恢复语言"那行也删了），但留在 store 里是个假值 ——
			//       任何人读 `themeConfig.globalI18n` 都会得到"界面并没在用"的答案，早晚误导人。
			//       这里就地修好，并在值确实不对时回写一次存储，下次启动就是干净的。
			//       ⚠️ 特意**不**用"升版本号 → Local.clear() + 刷新"那套：那会把用户调好的
			//          配色/布局一起清掉，代价比收益大。
			const merged = { ...themeConfig.value, ...saved, globalI18n: DEFAULT_LOCALE };
			storesThemeConfig.setThemeConfig({ themeConfig: merged });
			if (saved.globalI18n !== DEFAULT_LOCALE) Local.set('themeConfig', merged);
			document.documentElement.style.cssText = Local.get('themeConfigStyle');
		}
		// 获取缓存中的全屏配置
		if (Session.get('isTagsViewCurrenFull')) {
			stores.setCurrenFullscreen(Session.get('isTagsViewCurrenFull'));
		}
	});
});
// 页面销毁时，关闭监听布局配置/i18n监听
onUnmounted(() => {
	mittBus.off('openSetingsDrawer', () => {});
});

</script>
