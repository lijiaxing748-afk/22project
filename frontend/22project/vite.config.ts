import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';
import { writeFileSync } from 'fs';
import { defineConfig, loadEnv, ConfigEnv } from 'vite';
import vueSetupExtend from 'vite-plugin-vue-setup-extend';
import vueJsx from '@vitejs/plugin-vue-jsx'

/**
 * 生成 public/version-build（生产环境版本校验用）。
 *
 * 原来是 `import { generateVersionFile } from '/@/utils/upgrade'`，但那个模块里用了
 * `import.meta.env`；vite 把**配置文件本身打成 CJS** 时会报：
 *   "[WARNING] import.meta is not available with the cjs output format"
 * 这里就地实现同样的逻辑（只用 process.env.npm_package_version，行为不变），
 * 配置里不再引用带 import.meta 的模块，警告随之消失。
 *
 * ⚠️ 原注释在这里还写了"本工程的 package.json 没有 type: module"——**这句是错的**：
 *    package.json 第 4 行就是 `"type": "module"`。该警告的真实成因与配置文件的打包格式
 *    判定有关，跟那句话无关。结论（就地实现）依然成立，故只修正错误的前提描述。
 */
function generateVersionFile() {
	const packageVersion = process.env.npm_package_version ?? '0.0.0';
	writeFileSync('public/version-build', `${packageVersion}.${Date.now()}`);
}

const pathResolve = (dir: string) => {
	return resolve(__dirname, '.', dir);
};

const alias: Record<string, string> = {
	'/@': pathResolve('./src/'),
	'@great-dream': pathResolve('./node_modules/@great-dream/'),
	'@views': pathResolve('./src/views'),
	'vue-i18n': 'vue-i18n/dist/vue-i18n.cjs.js',
	'@dvaformflow':pathResolve('./src/viwes/plugins/dvaadmin_form_flow/src/')
};

const viteConfig = defineConfig((mode: ConfigEnv) => {
	const env = loadEnv(mode.mode, process.cwd());
	// 当Vite构建时，生成版本文件
	generateVersionFile()
	return {
		plugins: [vue(), vueJsx(), vueSetupExtend()],
		root: process.cwd(),
		resolve: { alias },
		base: mode.command === 'serve' ? './' : env.VITE_PUBLIC_PATH,
		optimizeDeps: {
			include: ['element-plus/es/locale/lang/zh-cn'],
		},
		server: {
			host: '0.0.0.0',
			port: env.VITE_PORT as unknown as number,
			open: false,
			hmr: true,
			proxy: {
				'/gitee': {
					target: 'https://gitee.com',
					ws: true,
					changeOrigin: true,
					rewrite: (path) => path.replace(/^\/gitee/, ''),
				},
			},
		},
		build: {
			outDir: env.VITE_DIST_PATH || 'dist',
			chunkSizeWarningLimit: 1500,
			rollupOptions: {
				output: {
					entryFileNames: `assets/[name].[hash].js`,
					chunkFileNames: `assets/[name].[hash].js`,
					assetFileNames: `assets/[name].[hash].[ext]`,
					compact: true,
					manualChunks: {
						vue: ['vue', 'vue-router', 'pinia'],
						echarts: ['echarts'],
					},
				},
			},
		},
		css: { preprocessorOptions: { css: { charset: false } } },
		define: {
			__VUE_I18N_LEGACY_API__: JSON.stringify(false),
			__VUE_I18N_FULL_INSTALL__: JSON.stringify(false),
			__INTLIFY_PROD_DEVTOOLS__: JSON.stringify(false),
			__VERSION__: JSON.stringify(process.env.npm_package_version),
		},
	};
});

export default viteConfig;
