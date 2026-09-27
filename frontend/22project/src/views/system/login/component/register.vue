<template>
	<el-form ref="formRef" size="large" class="login-content-form" :model="state.ruleForm" :rules="rules" @keyup.enter="registerClick">
		<el-form-item class="login-animation1" prop="username">
			<el-input type="text" placeholder="账号（3~50 个字符，不能含空格或斜杠）" v-model="ruleForm.username" clearable autocomplete="off">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-User /></el-icon>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation2" prop="name">
			<el-input type="text" placeholder="姓名 / 显示名（可留空，默认同账号）" v-model="ruleForm.name" clearable autocomplete="off">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-Postcard /></el-icon>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation2" prop="password">
			<el-input :type="isShowPassword ? 'text' : 'password'" placeholder="密码（至少 6 位）" v-model="ruleForm.password">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-Unlock /></el-icon>
				</template>
				<template #suffix>
					<i class="iconfont el-input__icon login-content-password"
						:class="isShowPassword ? 'icon-yincangmima' : 'icon-xianshimima'"
						@click="isShowPassword = !isShowPassword">
					</i>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation3" prop="password_regain">
			<el-input :type="isShowPassword ? 'text' : 'password'" placeholder="再输一次密码" v-model="ruleForm.password_regain">
				<template #prefix>
					<el-icon class="el-input__icon"><ele-Unlock /></el-icon>
				</template>
			</el-input>
		</el-form-item>
		<el-form-item class="login-animation3" v-if="isShowCaptcha" prop="captcha">
			<el-col :span="15">
				<el-input type="text" maxlength="4" placeholder="验证码" v-model="ruleForm.captcha" clearable autocomplete="off">
					<template #prefix>
						<el-icon class="el-input__icon"><ele-Position /></el-icon>
					</template>
				</el-input>
			</el-col>
			<el-col :span="1"></el-col>
			<el-col :span="8">
				<el-button class="login-content-captcha">
					<el-image :src="ruleForm.captchaImgBase" @click="refreshCaptcha" />
				</el-button>
			</el-col>
		</el-form-item>
		<el-form-item class="login-animation4">
			<el-button type="primary" class="login-content-submit" round @click="registerClick" :loading="state.loading.signIn">
				<span>注册并登录</span>
			</el-button>
		</el-form-item>
	</el-form>
	<div class="register-hint">
		注册出来的账号是<b>普通用户</b>（可训练、推理、发布、上传模型与数据集，也可以删除模型产物）。
		只有<b>用户管理</b>和<b>查看操作日志</b>需要管理员，需要请联系管理员在「用户管理」里把你设为管理员。
	</div>
</template>

<script lang="ts">
import { toRefs, reactive, defineComponent, computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, FormInstance, FormRules } from 'element-plus';
import Cookies from 'js-cookie';
import { Session } from '/@/utils/storage';
import * as loginApi from '/@/views/system/login/api';
import { useUserInfo } from '/@/stores/userInfo';
import { SystemConfigStore } from '/@/stores/systemConfig';
import { errorMessage } from '/@/utils/message';

export default defineComponent({
	name: 'loginRegister',
	setup() {
		const router = useRouter();
		const state = reactive({
			isShowPassword: false,
			ruleForm: {
				username: '',
				name: '',
				password: '',
				password_regain: '',
				captcha: '',
				captchaKey: '',
				captchaImgBase: '',
			},
			loading: {
				signIn: false,
			},
		});

		// ⚠️ 这里的校验规则与后端 dvadmin.register() **逐条对齐**（长度/空值/一致性）。
		//    前端校验只是提前拦住手滑，**不是安全边界** —— 客户端可以绕过，
		//    所以后端那份必须同样存在。改这里时别忘了同步改后端。
		const validateRegain = (rule: any, value: string, callback: any) => {
			if (!value) callback(new Error('请再次输入密码'));
			else if (value !== state.ruleForm.password) callback(new Error('两次输入的密码不一致'));
			else callback();
		};
		const rules = reactive<FormRules>({
			username: [
				{ required: true, message: '请填写账号', trigger: 'blur' },
				{ min: 3, max: 50, message: '账号长度需在 3~50 个字符之间', trigger: 'blur' },
				{ pattern: /^[^\s/\\]+$/, message: '账号不能包含空格或斜杠', trigger: 'blur' },
			],
			password: [
				{ required: true, message: '请填写密码', trigger: 'blur' },
				{ min: 6, message: '密码至少 6 位', trigger: 'blur' },
			],
			password_regain: [{ required: true, validator: validateRegain, trigger: 'blur' }],
			captcha: [{ required: true, message: '请填写验证码', trigger: 'blur' }],
		});
		const formRef = ref<FormInstance>();

		// 验证码开关与登录页共用同一个来源（后端 /api/init/settings/ 的 base.captcha_state）
		const isShowCaptcha = computed(() => SystemConfigStore().systemConfig['base.captcha_state']);

		const getCaptcha = async () => {
			loginApi.getCaptcha().then((ret: any) => {
				state.ruleForm.captchaImgBase = ret.data.image_base;
				state.ruleForm.captchaKey = ret.data.key;
			});
		};
		const refreshCaptcha = async () => {
			state.ruleForm.captcha = '';
			getCaptcha();
		};

		const registerClick = async () => {
			if (!formRef.value) return;
			await formRef.value.validate((valid: any) => {
				if (!valid) {
					errorMessage('请填写完整的注册信息');
					return;
				}
				// ⚠️ 密码**原样发**，不要做 MD5 —— 理由见 account.vue 的长注释：
				//    客户端哈希不解决传输安全（那是 HTTPS 的事），反而会让服务端的
				//    pbkdf2 加盐存储彻底失效，并且和后端校验必然对不上。
				state.loading.signIn = true;
				loginApi
					.register({ ...state.ruleForm })
					.then((res: any) => {
						if (res.code !== 2000) return;
						ElMessage.success('注册成功，正在登录…');
						// 注册完直接用同一份凭据走**正常的登录接口**。
						// 后端不在 register 里发令牌，就是为了让"登录之后要做什么"只有一条路径，
						// 不用把 account.vue 里那套初始化再抄一遍。
						return loginApi.login({ username: state.ruleForm.username, password: state.ruleForm.password });
					})
					.then((res2: any) => {
						if (!res2 || res2.code !== 2000) return;
						Cookies.set('username', res2.data.username);
						Session.set('token', res2.data.access);
						useUserInfo().setPwdChangeCount(res2.data.pwd_change_count);
						ElMessage.success('已登录');
						// ⚠️ 只 push 首页即可：路由守卫发现"有令牌但路由表为空"会自己初始化动态路由
						//    （见 router/index.ts 的 routesList.length === 0 分支），
						//    所以这里不需要重复 loginSuccess() 里那一整套初始化。
						router.push('/');
					})
					.catch(() => {
						// 业务失败的信息由 service.ts 的拦截器（case 4000）统一弹出，
						// 这里只负责刷新验证码 —— 一道题用过就作废，不刷新下次必然失败。
						refreshCaptcha();
					})
					.finally(() => {
						state.loading.signIn = false;
					});
			});
		};

		onMounted(() => {
			getCaptcha();
		});

		return {
			state,
			rules,
			formRef,
			isShowCaptcha,
			refreshCaptcha,
			registerClick,
			...toRefs(state),
		};
	},
});
</script>

<style scoped lang="scss">
.login-content-form {
	margin-top: 20px;

	@for $i from 1 through 4 {
		.login-animation#{$i} {
			opacity: 0;
			animation-name: error-num;
			animation-duration: 0.5s;
			animation-fill-mode: forwards;
			animation-delay: calc($i/10) + s;
		}
	}

	.login-content-password {
		display: inline-block;
		width: 20px;
		cursor: pointer;

		&:hover {
			color: #909399;
		}
	}

	.login-content-captcha {
		width: 100%;
		padding: 0;
		font-weight: bold;
		letter-spacing: 5px;
	}

	.login-content-submit {
		width: 100%;
		letter-spacing: 2px;
		font-weight: 800;
		margin-top: 15px;
	}
}
.register-hint {
	margin-top: 4px;
	font-size: 12px;
	line-height: 1.7;
	color: var(--el-text-color-secondary);
	text-align: center;
}
</style>
