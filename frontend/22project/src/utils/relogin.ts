/**
 * 登录态已失效时的**统一收尾**：弹一句中文 → 清令牌 → 回登录页。
 *
 * 为什么要有这个文件：令牌失效的收尾原先散在两个 axios 实例里，而且**行为相反** ——
 *   · `platformRequest` 在 401 时**静默**清令牌跳转：用户莫名其妙被弹回登录页，一句提示都没有；
 *   · `service.ts` 在 `code=4000` 时弹了框，却把跳转那段注释掉了：人卡在失效页面里出不去。
 * 同一件事、两种表现，用户根本不知道该干什么。现在两边都调这里，只有一份实现
 * （与 `logout.ts` 里"退出只有一个实现"同样的理由）。
 *
 * ⚠️ 为什么不放进 `logout.ts`：那个文件 import 了 `service.ts` 的 `request`（为了发退出请求），
 *    而 `service.ts` 又要调用本函数 —— 放一起就成了**循环依赖**。
 *    本文件只依赖 storage 与 element-plus，谁都能安全引入。
 *
 * ⚠️ 去重是**必需**的：各页 onMounted 都是并发打多个请求
 *    （见 home/system/model/dataset/visual 的 Promise.all），令牌一过期会同时回来好几个 401/4000；
 *    不去重就会连弹好几个对话框、还互相抢跳转。
 */
import { ElMessageBox } from 'element-plus';
import { Session } from '/@/utils/storage';

/** 本次页面生命周期内是否已经提示过（避免并发请求弹一串框）。 */
let reloginShown = false;

/**
 * 收尾登录失效的会话。
 *
 * @param msg 给用户看的原因；优先用后端文案，取不到就用默认那句
 */
export function forceRelogin(msg = '登录已失效，请重新登录'): void {
	if (reloginShown) return;
	reloginShown = true;
	// 先清令牌：这样即便用户不点确认、对话框被浏览器拦掉，本地也不会留着一个已知无效的令牌
	// （路由守卫只判"令牌存不存在"，留着它就会一直被放行到各页面，然后每个请求再失败一次）
	Session.clear();
	let jumped = false;
	const go = () => {
		if (jumped) return;                 // callback 与 then/catch 可能都触发，只跳一次
		jumped = true;
		window.location.href = '/';
	};
	try {
		ElMessageBox.alert(msg, '提示', {
			confirmButtonText: '重新登录',
			// 这里没有"留在原页"这个选项：点遮罩、按 Esc 也一律回登录页
			closeOnClickModal: false,
			closeOnPressEscape: false,
			callback: go,
		}).catch(go);                       // 用户关掉对话框时 MessageBox 会 reject，必须接住
	} catch {
		// 极端情况（DOM 还没准备好、组件库初始化失败）：直接跳，绝不把人卡在失效页面
		go();
	}
}
