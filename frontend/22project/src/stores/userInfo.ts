import { defineStore } from 'pinia';
import { UserInfosStates } from './interface';
import { Session } from '/@/utils/storage';
import { request } from '../utils/service';
import { getBaseURL } from '../utils/baseUrl';
import headerImage from '/@/assets/img/headerImage.png';

/**
 * 判断当前登录用户是否具备某个权限点。
 *
 * ⚠️ 这是个**独立导出**的函数（不是 store 的 getter），因为模板里要用它控制
 * 按钮显隐（`v-if="hasPerm('train:run')"`），而模板里拿 store 实例再去调
 * 方法比较啰嗦。直接读 Session 里的 userInfo 也避免了"store 还没 hydrate 完
 * 就已渲染"的时序问题——Session 是登录成功时就写好的。
 *
 * ⚠️ 再次强调：**这只决定按钮显不显示**。真正的权限检查在后端
 * （api.py 上的 @require_perm）。如果有人手动调接口，后端照样会拦。
 *
 * 未知权限 / 未登录 → false：默认拒绝，与后端 perms_of() 的失败方向一致。
 */
export function hasPerm(perm: string): boolean {
	if (!perm) return true;
	const info: any = Session.get('userInfo');
	if (!info) return false;
	const perms: string[] = info.permissions || [];
	return perms.includes(perm);
}

/**
 * 用户信息
 * @methods setUserInfos 设置用户信息
 */
export const useUserInfo = defineStore('userInfo', {
	state: (): UserInfosStates => ({
		userInfos: {
			id:'',
			avatar: '',
			username: '',
			name: '',
			email: '',
			mobile: '',
			gender: '',
			pwd_change_count:null,
			is_superuser: false,
			dept_info: {
				dept_id: 0,
				dept_name: '',
			},
			role_info: [
				{
					id: 0,
					name: '',
				},
			],
			// 鉴权改造新增：后端下发的**细粒度权限点列表**（auth.py 的 _ROLE_PERMS）。
			// 用它判断"这个按钮该不该显示"，比只看 is_superuser 精确得多——
			// engineer 不是超管，但他该能训练、该能发布。
			// ⚠️ 前端只管**显隐**，真正的拦截在后端。藏按钮只是避免用户点出一个
			//    403 的糟糕体验，它不是安全边界。
			permissions: [] as string[],
			role_key: '',
			role_name: '',
		},
	}),
	actions: {
		async setPwdChangeCount(count: number) {
			this.userInfos.pwd_change_count = count;
		},
		async updateUserInfos(userInfos:any) {
			this.userInfos.id = userInfos.id;
			this.userInfos.username = userInfos.name;
			this.userInfos.avatar = userInfos.avatar;
			this.userInfos.name = userInfos.name;
			this.userInfos.email = userInfos.email;
			this.userInfos.mobile = userInfos.mobile;
			this.userInfos.gender = userInfos.gender;
			this.userInfos.dept_info = userInfos.dept_info;
			this.userInfos.role_info = userInfos.role_info;
			this.userInfos.pwd_change_count = userInfos.pwd_change_count;
			this.userInfos.is_superuser = userInfos.is_superuser;
			this.userInfos.permissions = userInfos.permissions || [];
			this.userInfos.role_key = userInfos.role_key || '';
			this.userInfos.role_name = userInfos.role_name || '';
			Session.set('userInfo', this.userInfos);
		},
		async setUserInfos() {
			// 存储用户信息到浏览器缓存
			if (Session.get('userInfo')) {
				this.userInfos = Session.get('userInfo');
			} else {
				let userInfos: any = await this.getApiUserInfo();
				this.userInfos.id = userInfos.id;
				this.userInfos.username = userInfos.data.name;
				this.userInfos.avatar = userInfos.data.avatar;
				this.userInfos.name = userInfos.data.name;
				this.userInfos.email = userInfos.data.email;
				this.userInfos.mobile = userInfos.data.mobile;
				this.userInfos.gender = userInfos.data.gender;
				this.userInfos.dept_info = userInfos.data.dept_info;
				this.userInfos.role_info = userInfos.data.role_info;
				this.userInfos.pwd_change_count = userInfos.data.pwd_change_count;
				this.userInfos.is_superuser = userInfos.data.is_superuser;
				this.userInfos.permissions = userInfos.data.permissions || [];
				this.userInfos.role_key = userInfos.data.role_key || '';
				this.userInfos.role_name = userInfos.data.role_name || '';
				Session.set('userInfo', this.userInfos);
			}
		},
		async getApiUserInfo() {
			return request({
				url: '/api/system/user/user_info/',
				method: 'get',
			}).then((res:any)=>{
				this.userInfos.id = res.data.id;
				this.userInfos.username = res.data.name;
				this.userInfos.avatar = (res.data.avatar && getBaseURL(res.data.avatar)) || headerImage;
				this.userInfos.name = res.data.name;
				this.userInfos.email = res.data.email;
				this.userInfos.mobile = res.data.mobile;
				this.userInfos.gender = res.data.gender;
				this.userInfos.dept_info = res.data.dept_info;
				this.userInfos.role_info = res.data.role_info;
				this.userInfos.pwd_change_count = res.data.pwd_change_count;
				this.userInfos.is_superuser = res.data.is_superuser;
				this.userInfos.permissions = res.data.permissions || [];
				this.userInfos.role_key = res.data.role_key || '';
				this.userInfos.role_name = res.data.role_name || '';
				Session.set('userInfo', this.userInfos);
			})
		},
	},
});
