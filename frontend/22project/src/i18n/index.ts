import { createI18n } from 'vue-i18n';
import pinia from '/@/stores/index';
import { storeToRefs } from 'pinia';
import { useThemeConfig } from '/@/stores/themeConfig';

// 定义语言国际化内容

/**
 * 说明：
 * 须在 pages 下新建文件夹（建议 `要国际化界面目录` 与 `i18n 目录` 相同，方便查找），
 * 注意国际化定义的字段，不要与原有的定义字段相同。
 * 1、/src/i18n/lang 下的 ts 为框架的国际化内容
 * 2、/src/i18n/pages 下的 ts 为各界面的国际化内容
 */

// element plus 自带国际化
import zhcnLocale from 'element-plus/es/locale/lang/zh-cn';

// 定义变量内容
const messages = {};
const element = { 'zh-cn': zhcnLocale };
// 每种语言都必须先初始化为**空数组**，否则下面的 push 会炸（见下方注释）。
// 注意 key 用中划线写法，与文件名一致：'en'、'zh-tw'、'zh-cn'。
const itemize: Record<string, any[]> = { 'zh-cn': [], en: [], 'zh-tw': [] };
const modules: Record<string, any> = import.meta.glob('./**/*.ts', { eager: true });

// 对自动引入的 modules 进行分类
// https://vitejs.cn/vite3-cn/guide/features.html#glob-import
//
// ⚠️ 这里的写法被修过，不要再改回 `else itemize[key] = modules[path]`：
//    原代码只在 itemize 里预置了 'zh-cn'，其它语言第一次进来会走 else 分支，
//    把**整个模块对象**（而不是数组）赋给 itemize[key]；等到该语言的第二个文件
//    （如 lang/en.ts + pages/login/en.ts）进来时就会执行 `模块对象.push(...)`，
//    直接抛 `TypeError: itemize[key[2]].push is not a function`，
//    因为 i18n/index.ts 是 main.ts 的第 4 个 import，整个 Vue 应用会白屏。
//    只有在仓库里只有 zh-cn 一种语言时这个 bug 才不会暴露。
for (const path in modules) {
	const key = path.match(/(\S+)\/(\S+).ts/);
	if (!key) continue;
	const lang = key[2];
	// 兜底：glob 到未在上面登记的语言文件时，先补一个空数组，避免再次白屏。
	if (!Array.isArray(itemize[lang])) itemize[lang] = [];
	itemize[lang].push(modules[path].default);
}

// 合并数组对象（非标准数组对象，数组中对象的每项 key、value 都不同）
function mergeArrObj<T>(list: T, key: string) {
	let obj = {};
	list[key].forEach((i: EmptyObjectType) => {
		obj = Object.assign({}, obj, i);
	});
	return obj;
}

// 处理最终格式
for (const key in itemize) {
	messages[key] = {
		name: key,
		// element-plus 自带语言包里只有 zh-cn 被引入；en / zh-tw 等其它语言
		// 没有对应条目，直接取 element[key].el 会抛 `Cannot read properties of undefined`。
		// 这里回退到 zh-cn（非中文界面的 element-plus 内置文案会是中文，但不会白屏）。
		el: (element[key] ?? element['zh-cn']).el,
		message: mergeArrObj(itemize, key),
	};
}

// 读取 pinia 默认语言
const stores = useThemeConfig(pinia);
const { themeConfig } = storeToRefs(stores);

// 导出语言国际化
// https://vue-i18n.intlify.dev/guide/essentials/fallback.html#explicit-fallback-with-one-locale
export const i18n = createI18n({
	legacy: false,
	silentTranslationWarn: true,
	missingWarn: false,
	silentFallbackWarn: true,
	fallbackWarn: false,
	locale: themeConfig.value.globalI18n,
	fallbackLocale: zhcnLocale.name,
	messages,
});
