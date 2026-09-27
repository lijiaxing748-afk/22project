/**
 * 前端页面静态编译校验（不依赖 esbuild / 不起子进程）
 *
 * 背景：本机的受限沙箱不允许 esbuild 起子进程（spawn EPERM），所以 `vite build` / `vite dev`
 * 在沙箱内无法运行。这里改用工程里已经装好的编译器在**进程内**逐个编译我新写的 SFC：
 *   - @vue/compiler-sfc：解析 SFC → 编译 <script setup> → 编译 <template>
 *   - sass：编译 <style lang="scss">
 *   - 校验 import 路径是否存在
 * 它能覆盖 vite build 会报的绝大多数错误（模板语法、script 语法、SCSS、引用路径）。
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const sfc = require(path.join(ROOT, 'node_modules/@vue/compiler-sfc'));
const sass = require(path.join(ROOT, 'node_modules/sass'));

/**
 * 平台页清单：**自动发现** `src/views/platform/**\/index.vue`。
 *
 * ⚠️ 这里以前是手写的 5 个页面，于是 lab 线新增的 publish / user / log 三个页面
 *    根本没被校验到（清单漂了也不会有人发现）。改成扫描目录，新增页面自动纳入。
 *    新增页面后如果 SFC 编译不过，本脚本会直接报出来。
 */
function platformPages() {
	const base = path.join(ROOT, 'src/views/platform');
	const out = [];
	const walk = (dir) => {
		for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, e.name);
			if (e.isDirectory()) walk(full);
			else if (e.name === 'index.vue') out.push(path.relative(ROOT, full).replace(/\\/g, '/'));
		}
	};
	if (fs.existsSync(base)) walk(base);
	return out.sort();
}
/**
 * 平台页之外的**登录 / 布局**文件。
 *
 * ⚠️ 为什么要把它们列进来：这几个文件不在 `src/views/platform/` 下，自动扫描扫不到，
 *    但它们是**登录链路**——改坏了整站都进不去，比某个业务页出问题严重得多。
 *    2026-09 加「注册」页签时就吃了这个亏：新写的 register.vue 与改过的 user.vue
 *    没有任何自动校验覆盖，只能临时手写脚本去编译。
 *    这里手写清单是**有意**的：文件少、且每个都值得单独确认存在。
 */
const AUTH_LAYOUT_FILES = [
	'src/views/system/login/index.vue',
	'src/views/system/login/component/account.vue',
	'src/views/system/login/component/changePwd.vue',
	'src/views/system/login/component/register.vue',
	'src/layout/navBars/breadcrumb/user.vue',
].filter((rel) => fs.existsSync(path.join(ROOT, rel)));

const FILES = [...platformPages(), ...AUTH_LAYOUT_FILES];
const ALSO = ['src/api/platform/index.ts', 'src/api/system/user.ts', 'src/views/system/login/api.ts'];

let errors = 0;
const ok = (m) => console.log('  ✅ ' + m);
const bad = (m) => { errors++; console.log('  ❌ ' + m); };

console.log('=== 1) SFC 编译校验 ===');
for (const rel of FILES) {
	const file = path.join(ROOT, rel);
	const source = fs.readFileSync(file, 'utf8');
	const { descriptor, errors: parseErrors } = sfc.parse(source, { filename: file });
	if (parseErrors.length) { bad(`${rel} 解析失败：${parseErrors.map((e) => e.message).join('; ')}`); continue; }

	let fileOk = true;
	// script setup
	try {
		const id = 'x' + Math.random().toString(36).slice(2, 10);
		const compiled = sfc.compileScript(descriptor, { id });
		const bindings = Object.keys(compiled.bindings || {});
		// template
		if (descriptor.template) {
			const t = sfc.compileTemplate({
				source: descriptor.template.content, filename: file, id,
				compilerOptions: { bindingMetadata: compiled.bindings },
			});
			if (t.errors && t.errors.length) { fileOk = false; bad(`${rel} 模板错误：${t.errors.map((e) => e.message || e).join('; ')}`); }
		}
		// style
		for (const style of descriptor.styles) {
			if (style.lang === 'scss') {
				try { sass.compileString(style.content, { syntax: 'scss' }); }
				catch (e) { fileOk = false; bad(`${rel} SCSS 错误：${e.message.split('\n')[0]}`); }
			}
		}
		if (fileOk) ok(`${rel}（模板 + script setup + SCSS 全部编译通过，绑定 ${bindings.length} 个）`);
	} catch (e) {
		bad(`${rel} script 编译失败：${e.message.split('\n')[0]}`);
	}
}

console.log('\n=== 2) import 路径校验 ===');
const IMPORT_RE = /from\s+['"]([^'"]+)['"]/g;
const checkFile = (rel) => {
	const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
	const aliasRoot = path.join(ROOT, 'src');
	let m;
	while ((m = IMPORT_RE.exec(src))) {
		const spec = m[1];
		if (spec.startsWith('.')) continue;                       // 相对路径，编译器自己管
		if (spec.startsWith('/@/')) {
			const target = path.join(aliasRoot, spec.slice(3));
			const found = fs.existsSync(target) || fs.existsSync(target + '.ts') || fs.existsSync(target + '.vue')
				|| fs.existsSync(path.join(target, 'index.ts'));
			if (!found) bad(`${rel} 引用不存在的别名路径：${spec}`);
		} else if (spec.startsWith('/src/')) {
			if (!fs.existsSync(path.join(ROOT, spec))) bad(`${rel} 引用不存在：${spec}`);
		} else {
			const pkg = spec.startsWith('@') ? spec.split('/').slice(0, 2).join('/') : spec.split('/')[0];
			if (!fs.existsSync(path.join(ROOT, 'node_modules', pkg))) bad(`${rel} 依赖未安装：${pkg}`);
		}
	}
};
[...FILES, ...ALSO].forEach(checkFile);
if (!errors) ok('所有 import（/@/ 别名、外部依赖）都能解析');

console.log('\n=== 3) 前端接口清单同步校验（platform-api-paths.json）===');
// ⚠️ 本节原来的标题是「后端契约一致性（页面用到的接口是否都在 flask 侧存在）」，
//    但代码只是把 URL console.log 了一遍、**没有任何断言** —— 也就是它永远不会失败，
//    名不副实（README 却据此宣称"后端接口契约一致性"已校验）。
//    真要做"前端调用的路径在 Flask 里到底存不存在"，得读 Python 侧的 _ROUTES；
//    本脚本是 Node、沙箱里又不允许起子进程（spawn EPERM），所以那一层交给后端自测
//    （testRestfulProject/_selftest_*.py、tools/verify-*.py）。
//    这里改成做一件**能做到、也必须做**的断言：生成物与源码是否同步。
//    platform-api-paths.json 是要入库的生成物；改了 src/api/platform/index.ts 却忘了
//    重新生成 —— lab 线加完用户管理/操作日志接口后就是这么漏的。
const apiSrc = fs.readFileSync(path.join(ROOT, 'src/api/platform/index.ts'), 'utf8');
const urls = [...apiSrc.matchAll(/url:\s*(?:`([^`]+)`|'([^']+)')/g)].map((m) => (m[1] || m[2]));
const norm = [...new Set(urls.map((u) => '/' + u.replace(/^\//, '').split('?')[0].replace(/\$\{[^}]+\}/g, '<x>')))];
console.log('  前端调用的接口：');
norm.forEach((u) => console.log('    ' + u));

const manifest = path.join(ROOT, 'platform-api-paths.json');
let prev = null;
if (fs.existsSync(manifest)) {
	try { prev = JSON.parse(fs.readFileSync(manifest, 'utf8')); } catch { prev = null; }
}
if (Array.isArray(prev) && JSON.stringify(prev) === JSON.stringify(norm)) {
	ok(`platform-api-paths.json 与源码同步（${norm.length} 条）`);
} else {
	// 先把差异说清楚（读的是"改写前"的快照），再同步写回
	const added = prev ? norm.filter((u) => !prev.includes(u)) : norm;
	const removed = prev ? prev.filter((u) => !norm.includes(u)) : [];
	bad('platform-api-paths.json 与 src/api/platform/index.ts 不同步（生成物必须一起提交）');
	if (added.length) console.log('    源码有、清单缺：' + added.join(', '));
	if (removed.length) console.log('    清单有、源码无：' + removed.join(', '));
	console.log('    已自动同步；请把 platform-api-paths.json 一起提交后重跑本脚本');
}
fs.writeFileSync(manifest, JSON.stringify(norm, null, 1));

console.log(`\n结论：${errors ? errors + ' 处错误' : '全部通过 ✅'}`);
process.exit(errors ? 1 : 0);
