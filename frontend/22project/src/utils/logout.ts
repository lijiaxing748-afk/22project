/**
 * 退出登录。
 *
 * 为什么单独一个文件：退出有**两个入口**（右上角头像下拉菜单、侧边栏左下角的按钮），
 * 逻辑要是各写一遍，早晚会出现"一处清了缓存、另一处忘了清"这种不一致，
 * 而且两边行为会慢慢漂移。这里放唯一一份实现，两处都调它。
 *
 * ⚠️ 三个步骤的**顺序**是有意的，别调换：
 *
 *   1. **先发** `POST /api/logout/`，再清本地令牌。
 *      反过来的话这个请求就成了匿名的，服务端那条 logout 操作日志会记不到"是谁退的"
 *      —— `dvadmin.logout()` 是**有有效令牌才写日志**的（令牌是无状态的，
 *      服务端本来没有会话要清，它能做的就只有留一条记录）。
 *      这一步用 catch 兜住：服务端连不上、令牌已失效，都**不该阻止本地退出**，
 *      否则用户会被卡在一个"退不出去"的登录态里，比丢一条日志严重得多。
 *
 *   2. 清 Session（token / userInfo / 菜单路由表都在里面）。
 *
 *   3. `window.location.href = '/'` **整页**回登录页，而不是 `router.push`：
 *      登录后是按角色 `addRoute` 动态加的路由，只 push 不重载会残留上一个人的路由表；
 *      整页重载能把 router、Pinia、keep-alive 缓存一次清干净。
 *      根路径下没有令牌时，路由守卫会把人送到 `/login`（见 `router/index.ts`）。
 */
import { ElMessageBox } from 'element-plus';
import { Session } from '/@/utils/storage';
import { request } from '/@/utils/service';

/**
 * 退出登录并回到登录页。
 *
 * @param opts.confirm 是否先弹确认框，默认 `true`。给 `false` 时不问直接退
 *                     （用于"令牌已失效、只想回登录页"这类场合）。
 */
export async function doLogout(opts: { confirm?: boolean } = {}): Promise<void> {
	const { confirm = true } = opts;

	if (confirm) {
		try {
			// ⚠️ 文案**写死中文**，不走 i18n：这里以前用的是 `i18n.global.t('message.user.logOut*')`，
			//    而 i18n 的语言是从本地存储恢复的 —— 浏览器里残留 `globalI18n: 'en'` 时，
			//    这个确认框会变成 "Are you sure you want to log out?" 之类。
			//    业务侧的自定义文案一律硬编码中文（与平台各页面一致）：
			//    文案来源越少，"界面突然变英文"这种问题就越不可能出现。
			await ElMessageBox.confirm('此操作将退出登录，是否继续？', '提示', {
				confirmButtonText: '确定',
				cancelButtonText: '取消',
				type: 'warning',
				// 点遮罩/按 Esc 直接关掉的话，用户会分不清"到底退没退"，所以都关掉
				closeOnClickModal: false,
				closeOnPressEscape: false,
			});
		} catch {
			// ⚠️ ElMessageBox 用 **reject** 表示"用户点了取消"，必须接住，
			//    否则控制台会留下一条未处理的 Promise 拒绝，看着像 bug。
			return;
		}
	}

	try {
		await request({ url: '/api/logout/', method: 'post' });
	} catch {
		// 见文件头第 1 条：失败也要继续把本地退干净
	}

	Session.clear();
	window.location.href = '/';
}
