<template>
	<!-- 必须包一层单根 div：本页除了 el-tabs 还有 3 个 el-dialog，
	     多根 fragment 会让框架的 KeepAlive/Transition 报
	     "Extraneous non-props attributes / non-element root node" 且 class 挂不上 -->
	<div class="platform-page">
	<el-tabs v-model="tab">
		<!-- ============ 模型清单 ============ -->
		<el-tab-pane label="模型清单" name="list">
			<el-card shadow="never">
				<template #header>
					<span>模型清单（登记信息 + 模型参数）</span>
					<span class="hint" style="margin-left: 8px">点任意一行，下方展示该模型的完整参数</span>
					<span style="float: right">
						<el-button type="primary" size="small" @click="openUpload">上传模型</el-button>
						<el-button size="small" @click="loadModels">刷新</el-button>
					</span>
				</template>
				<el-table ref="tableRef" :data="mergedRows" size="small" highlight-current-row empty-text="还没有登记/产物"
					@current-change="onRowClick" style="cursor: pointer">
					<!-- 四栏都用 min-width 且取值相同：el-table 会按 min-width 比例分配剩余宽度，
					     于是四栏最终等宽（原来是"头栏吃掉全部余量"，看着忽宽忽窄） -->
					<el-table-column label="模型 / 登记信息" min-width="160">
						<template #default="{ row }">
							<b>{{ row.name }}</b>
							<el-tag v-if="row.reg?.ModelType" size="small" class="ml">{{ typeLabel(row.reg.ModelType) }}</el-tag>
							<div class="hint">ID={{ row.reg?.ModelID ?? '—' }} · 接口 {{ row.reg?.ApiEndpoint || '—' }}</div>
							<div class="hint">状态 {{ row.reg?.Status || '—' }} · {{ row.reg?.IsActive ? '已启用' : '已停用' }}</div>
						</template>
					</el-table-column>
					<!-- 列表只回答「有没有产物、什么框架」；参数细节点行看下方详情卡，不重复搬运 -->
					<el-table-column label="产物" min-width="160" align="center">
						<template #default="{ row }">
							<template v-if="row.art">
								<el-tag size="small" type="success">{{ fwLabel(row.art.framework) }}</el-tag>
								<span class="ml">{{ (row.art.weights || '').split(/[\\/]/).pop() || '—' }}</span>
							</template>
							<span v-else class="hint">无产物</span>
						</template>
					</el-table-column>
					<el-table-column label="指标" min-width="160" align="center">
						<template #default="{ row }">
							<template v-if="row.art">
								<b v-if="rowMetric(row).value !== '—'">{{ rowMetric(row).value }}</b>
								<span v-else class="hint">—</span>
								<div class="hint">{{ rowMetric(row).label }}</div>
							</template>
							<span v-else class="hint">无产物</span>
						</template>
					</el-table-column>
					<el-table-column label="操作" min-width="160" align="center">
						<template #default="{ row }">
							<el-button link type="primary" @click.stop="openEdit(row)">编辑</el-button>
							<el-button link type="success" :disabled="!row.art" @click.stop="openExport(row)">发布</el-button>
							<el-button link type="danger" @click.stop="removeModel(row)">删除</el-button>
						</template>
					</el-table-column>
				</el-table>
			</el-card>

			<!-- ====== 列表下方：所选模型的完整参数 ====== -->
			<el-card shadow="never" class="mt">
				<template #header>
					<span>模型展示：{{ overview?.model || '未选择' }} 的模型参数</span>
					<span class="hint" style="margin-left: 8px">点上方列表任意一行查看</span>
					<!-- float:right 的规则是"先出现的更靠右"，所以 meta.json 写在前面 = 它在最右边。
					     两个都是实体按钮（去掉 link）：meta.json 白底描边，关闭是蓝色主按钮。 -->
					<el-button v-if="overview" size="small" style="float: right" @click="showMeta(overview.model)">meta.json 全文</el-button>
					<el-button v-if="overview" size="small" type="primary" style="float: right; margin-left: 8px" @click="closeOverview">关闭</el-button>
				</template>
				<div v-if="!overview" class="empty">尚未选择模型</div>
				<template v-else>
					<!-- overview.artifact 可能是 null（登记了但还没训练/上传过）：给一句话，其余字段照旧显示「—」 -->
					<el-alert v-if="!curArt" type="info" :closable="false" show-icon class="mb"
						title="该模型还没有产物（未训练，也没上传过文件夹），下面只有登记信息与超参。" />
					<el-descriptions :column="3" border size="small">
						<el-descriptions-item label="框架">{{ curArt.framework || '—' }}</el-descriptions-item>
						<el-descriptions-item label="输入长度">{{ curArt.input_len ?? '—' }}</el-descriptions-item>

						<!-- 分类/回归看"类别数"，异常检测没有类别，改看检测器与判定阈值 -->
						<el-descriptions-item v-if="!isAnomalyModel" label="类别数">
							{{ curArt.num_classes ?? '—' }}
						</el-descriptions-item>
						<template v-else>
							<el-descriptions-item label="检测器">
								{{ overview.params?.detector || '—' }}<span v-if="overview.params?.k != null" class="hint"> k={{ overview.params.k }}</span>
							</el-descriptions-item>
							<el-descriptions-item label="判定阈值">{{ fmtThreshold(overview.metrics?.threshold) }}</el-descriptions-item>
						</template>

						<el-descriptions-item label="权重文件">
							{{ (curArt.weights || '').split(/[\\/]/).pop() || '—' }}
						</el-descriptions-item>
						<el-descriptions-item label="参数来源">{{ overview.params?.source === 'uploaded' ? '文件夹上传' : '训练生成' }}</el-descriptions-item>
						<el-descriptions-item v-if="isAnomalyModel" label="基线文件">
							{{ overview.params?.baseline_file || '—' }}
						</el-descriptions-item>
						<el-descriptions-item v-if="isAnomalyModel" label="基线误报率">
							{{ overview.metrics?.baseline_false_positive_rate != null
								? (overview.metrics.baseline_false_positive_rate * 100).toFixed(2) + '%' : '—' }}
						</el-descriptions-item>
						<el-descriptions-item v-else label="类别标签">
							{{ (overview.labels || []).length ? `${overview.labels.length} 个` : '—' }}
						</el-descriptions-item>
					</el-descriptions>
					<div v-if="isAnomalyModel" class="hint mt">
						无监督判定：窗口 → 特征 → adtk 的 PCA 重构误差；阈值 = 正常窗口分数分布的
						{{ ((overview.params?.threshold_quantile ?? 0.995) * 100).toFixed(1) }}% 分位，
						推理时<strong>重构误差 &gt; 阈值即判「异常」</strong>，分数越大越异常。
					</div>
					<h4 class="mt">超参</h4>
					<el-descriptions :column="4" border size="small">
						<el-descriptions-item v-for="(v, k) in overview.params" :key="k" :label="String(k)">
							{{ Array.isArray(v) ? JSON.stringify(v) : (v === null || v === undefined ? '—' : v) }}
						</el-descriptions-item>
						<el-descriptions-item v-if="!Object.keys(overview.params || {}).length" label="超参">
							该模型没有超参记录（无监督模型，或从文件夹上传的产物）
						</el-descriptions-item>
					</el-descriptions>
				</template>
			</el-card>
		</el-tab-pane>

		<!-- ============ 训练 ============ -->
		<el-tab-pane label="训练" name="train">
			<el-alert type="warning" :closable="false" show-icon class="mb"
				title="训练是同步阻塞的：1DCNN 10 轮约 15 秒，cwt_cnn 50 轮约 25 秒，提交后请等待结果。" />
			<el-row :gutter="16">
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>训练参数</span></template>
						<el-form label-width="130px" size="small">
							<!-- 「数据源」select 已删除：它的值每次选目录都会被 syncSource() 用目录带出的
							     dataset_type 覆盖，而目录下拉的 label 里本来就有 [表格/mat]，留着只是个会骗人的状态。
							     ⚠️ train.dataset_type 这个键**照旧发送**（由目录带出），后端行为完全不变。 -->
							<el-form-item label="数据集目录">
								<el-select v-model="train.dataset_dir" style="width: 100%" @change="syncSource">
									<el-option v-for="d in datasetOptions" :key="d.value" :label="d.label" :value="d.value" />
								</el-select>
							</el-form-item>
							<!-- adtk 的专属入口：training.py 的 _train_adtk 就是拿 dataset_dir + baseline_file
							     去找那个「正常」样本文件，找不到会直接报错（不再静默退回自带的 cpu.csv） -->
							<el-form-item v-if="isAdtkTrain" label="基线文件">
								<el-input v-model="train.baseline_file" placeholder="normal_0_97.mat" />
								<div class="hint">必须存在于所选数据集目录中</div>
							</el-form-item>
							<el-form-item v-if="!isAdtkTrain" label="信号列">
								<el-input v-model="train.signal_column" placeholder="表格数据留空=自动识别（如 振动幅值）" />
							</el-form-item>
							<el-form-item label="模型">
								<el-select v-model="train.model" style="width: 100%" @change="applyDefaults">
									<el-option label="算法模型1 · 1dcnn（TensorFlow/Keras）" value="1dcnn" />
									<el-option label="算法模型2 · cwt_cnn（PyTorch）" value="cwt_cnn" />
									<el-option label="算法模型3 · adtk（无监督，已搁置）" value="adtk" />
								</el-select>
							</el-form-item>
							<!-- adtk 是无监督路线：不读 epochs / batch_size / signal_column，strict 也不生效
							     （它只吃 .mat 的 DE 通道切窗），所以这些控件在 adtk 下隐藏——改了不生效的控件
							     比没控件更误导。⚠️ 只是不显示：v-model 的值照旧随 payload 发出去，
							     后端收到的参数集与改动前逐字节一致 -->
							<el-row :gutter="8">
								<el-col v-if="!isAdtkTrain" :span="8"><el-form-item label="轮次" label-width="50px"><el-input-number v-model="train.epochs" :min="1" :max="200" controls-position="right" style="width: 100%" /></el-form-item></el-col>
								<el-col :span="8"><el-form-item label="长度" label-width="50px"><el-input-number v-model="train.length" :min="64" :step="64" controls-position="right" style="width: 100%" /></el-form-item></el-col>
								<!-- adtk 的 number 是「基线窗口数」，后端少于 20 个窗口直接报错，所以 min 跟着抬到 20 -->
								<el-col :span="isAdtkTrain ? 16 : 8">
									<el-form-item :label="isAdtkTrain ? '基线窗口数（≥20）' : '每类窗数'" :label-width="isAdtkTrain ? '140px' : '80px'">
										<el-input-number v-model="train.number" :min="isAdtkTrain ? 20 : 10" controls-position="right" style="width: 100%" />
									</el-form-item>
								</el-col>
							</el-row>
							<el-row :gutter="8">
								<el-col :span="isAdtkTrain ? 16 : 8">
									<el-form-item label="步长" label-width="50px">
										<el-input-number v-model="train.stride" :min="1" controls-position="right" style="width: 100%" />
										<div v-if="isAdtkTrain" class="hint">默认等于长度（不重叠）</div>
									</el-form-item>
								</el-col>
								<el-col v-if="!isAdtkTrain" :span="8"><el-form-item label="批大小" label-width="60px"><el-input-number v-model="train.batch_size" :min="1" controls-position="right" style="width: 100%" /></el-form-item></el-col>
								<el-col :span="8"><el-form-item label="种子" label-width="50px"><el-input-number v-model="train.seed" :min="0" controls-position="right" style="width: 100%" /></el-form-item></el-col>
							</el-row>
							<el-form-item label="数据集登记名">
								<el-input v-model="train.dataset" placeholder="写入 Datasets 表的名称" />
							</el-form-item>
							<el-form-item v-if="!isAdtkTrain" label="越界窗口">
								<el-switch v-model="train.strict" active-text="跳过（推荐，不补 NaN）" inactive-text="复刻旧脚本（补 NaN）" />
							</el-form-item>
							<el-button type="primary" :loading="training" @click="doTrain">
								{{ training ? `训练中… ${elapsed}s` : '开始训练' }}
							</el-button>
						</el-form>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="12">
					<el-card shadow="never">
						<template #header><span>训练结果</span></template>
						<div v-if="!trainResult" class="empty">还没有训练结果</div>
						<template v-else>
							<!-- 结果卡按任务类型分两套：分类（有监督）看准确率/loss/混淆矩阵；
							     异常检测（adtk 无监督）根本没有准确率这一说，硬套分类那 7 行只会
							     一排「—」+ 空白，看着像训练失败。分叉判据见 isAnomalyResult() -->
							<el-descriptions :column="1" border size="small">
								<el-descriptions-item label="状态">
									<el-tag :type="trainResult.status === '成功' ? 'success' : 'danger'" size="small">{{ trainResult.status }}</el-tag>
									耗时 {{ trainResult.duration_sec }} 秒
								</el-descriptions-item>
								<el-descriptions-item label="产物">{{ trainResult.artifact?.weights || '—' }}</el-descriptions-item>

								<!-- ===== 按任务类型分两套模板 =====
								     分类（有监督）：测试/验证准确率 + loss + 训练/验证/测试切分（保持原来的 7 行）；
								     异常检测（adtk 无监督）：根本没有准确率这一说，硬套上面那套会渲染出一排「—」，
								     看着像训练失败，所以改显示基线窗口数/检测器/阈值/基线误报率与后端给的 note。
								     判据见 isAnomalyResult() -->
								<template v-if="!isAnomalyResult()">
									<el-descriptions-item label="测试准确率">
										{{ fmt(trainResult.metrics?.test_accuracy) }} / loss {{ fmt(trainResult.metrics?.test_loss) }}
									</el-descriptions-item>
									<el-descriptions-item label="验证准确率">{{ fmt(trainResult.metrics?.val_accuracy) }}</el-descriptions-item>
									<el-descriptions-item label="训练/验证/测试">
										{{ trainResult.dataset_stats?.train_total ?? '—' }} / {{ trainResult.dataset_stats?.valid_total ?? '—' }} / {{ trainResult.dataset_stats?.test_total ?? '—' }}
									</el-descriptions-item>
									<el-descriptions-item label="跳过越界 / NaN">
										{{ trainResult.dataset_stats?.skipped_out_of_range_total ?? '—' }} / {{ trainResult.dataset_stats?.nan_windows_total ?? '—' }}
									</el-descriptions-item>
								</template>
								<template v-else>
									<el-descriptions-item label="基线窗口数">{{ trainResult.dataset_stats?.windows ?? '—' }}</el-descriptions-item>
									<el-descriptions-item label="基线点数">{{ trainResult.dataset_stats?.baseline_points ?? '—' }}</el-descriptions-item>
									<el-descriptions-item label="检测器">{{ trainResult.dataset_stats?.detector || '—' }}</el-descriptions-item>
									<el-descriptions-item label="主成分数 k">{{ trainResult.dataset_stats?.k ?? '—' }}</el-descriptions-item>
									<el-descriptions-item label="特征模式">{{ trainResult.dataset_stats?.feature_mode || '—' }}</el-descriptions-item>
									<el-descriptions-item label="判定阈值">
										{{ fmtThreshold(trainResult.metrics?.threshold ?? trainResult.dataset_stats?.threshold) }}
									</el-descriptions-item>
									<el-descriptions-item label="基线误报率">
										{{ fmtPct(trainResult.metrics?.baseline_false_positive_rate ?? trainResult.dataset_stats?.baseline_false_positive_rate) }}
									</el-descriptions-item>
									<el-descriptions-item label="说明">{{ trainResult.metrics?.note || '—' }}</el-descriptions-item>
								</template>

								<el-descriptions-item label="写库">
									<Tag :text="trainResult.db" />
								</el-descriptions-item>
							</el-descriptions>
							<!-- 图区：没图时给一句话说明，而不是留一个空 div（adtk 本来就不出训练曲线/混淆矩阵） -->
							<div v-if="(trainResult.figures || []).length" class="figs mt">
								<el-image v-for="f in trainResult.figures" :key="f.url" :src="fileUrl(f.url)"
									:preview-src-list="[fileUrl(f.url)]" fit="contain" class="fig" />
							</div>
							<div v-else class="hint mt">该模型不产出训练曲线/混淆矩阵</div>
							<!-- 无监督模型没有 classification_report（后端恒给 null），留着只会显示一个「—」 -->
							<el-collapse v-if="!isAnomalyResult()" class="mt">
								<el-collapse-item title="classification_report">
									<pre class="pre">{{ trainResult.metrics?.classification_report || '—' }}</pre>
								</el-collapse-item>
							</el-collapse>
						</template>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>

		<!-- ============ 推理 ============ -->
		<el-tab-pane label="推理" name="predict">
			<el-row :gutter="16">
				<el-col :xs="24" :md="10">
					<el-card shadow="never">
						<template #header><span>推理参数</span></template>
						<el-form label-width="120px" size="small">
							<el-form-item label="模型">
								<el-select v-model="pred.model" style="width: 100%">
									<el-option label="算法模型1 · 1dcnn" value="1dcnn" />
									<el-option label="算法模型2 · cwt_cnn" value="cwt_cnn" />
									<el-option label="算法模型3 · adtk" value="adtk" />
								</el-select>
							</el-form-item>
							<el-form-item label="输入文件">
								<el-select v-model="pred.path" filterable style="width: 100%">
									<el-option v-for="f in fileOptions" :key="f.value" :label="f.label" :value="f.value" />
								</el-select>
							</el-form-item>
							<el-form-item label="信号列">
								<el-input v-model="pred.column" placeholder="表格文件留空=自动识别" />
							</el-form-item>
							<el-row :gutter="8">
								<el-col :span="8"><el-form-item label="起始窗" label-width="60px"><el-input-number v-model="pred.index" :min="0" controls-position="right" style="width: 100%" /></el-form-item></el-col>
								<el-col :span="8"><el-form-item label="窗口数" label-width="60px"><el-input-number v-model="pred.limit" :min="1" :max="500" controls-position="right" style="width: 100%" /></el-form-item></el-col>
								<el-col :span="8"><el-form-item label="top_k" label-width="60px"><el-input-number v-model="pred.top_k" :min="1" :max="10" controls-position="right" style="width: 100%" /></el-form-item></el-col>
							</el-row>
							<el-button type="primary" :loading="predicting" @click="doPredict">开始推理</el-button>
						</el-form>
					</el-card>
				</el-col>
				<el-col :xs="24" :md="14">
					<el-card shadow="never">
						<template #header><span>推理结果</span></template>
						<div v-if="!predResult" class="empty">还没有推理结果</div>
						<template v-else>
							<el-descriptions :column="1" border size="small">
								<el-descriptions-item label="模型">{{ predResult.model }} · {{ predResult.framework }}</el-descriptions-item>
								<el-descriptions-item label="样本数">{{ predResult.count }}（窗口长度 {{ predResult.input_len }}）</el-descriptions-item>
								<el-descriptions-item label="摘要">{{ JSON.stringify(predResult.summary) }}</el-descriptions-item>
								<el-descriptions-item label="写库"><Tag :text="predResult.db" /></el-descriptions-item>
							</el-descriptions>
							<el-table :data="predResult.predictions" size="small" class="mt">
								<el-table-column prop="index" label="窗口" width="70" />
								<el-table-column prop="predicted_label" label="预测" min-width="150" />
								<el-table-column label="置信度" width="110">
									<template #default="{ row }">{{ row.confidence != null ? Number(row.confidence).toFixed(4) : '—' }}</template>
								</el-table-column>
								<el-table-column label="异常分数" width="120">
									<template #default="{ row }">{{ fmtScore(row.anomaly_score) }}</template>
								</el-table-column>
								<el-table-column prop="actual_class" label="真实类别" width="100" />
								<el-table-column label="命中" width="90">
									<template #default="{ row }">
										<el-tag v-if="row.actual_class != null" :type="row.predicted_class === row.actual_class ? 'success' : 'danger'" size="small">
											{{ row.predicted_class === row.actual_class ? '命中' : '未命中' }}
										</el-tag>
										<span v-else>—</span>
									</template>
								</el-table-column>
							</el-table>
							<div class="figs mt">
								<el-image v-for="f in predResult.figures || []" :key="f.url" :src="fileUrl(f.url)"
									:preview-src-list="[fileUrl(f.url)]" fit="contain" class="fig" />
							</div>
						</template>
					</el-card>
				</el-col>
			</el-row>
		</el-tab-pane>

		<!-- ============ 训练记录 ============ -->
		<el-tab-pane label="训练记录" name="trainings">
			<el-card shadow="never">
				<template #header><span>最近训练（读库）</span><el-button link type="primary" style="float: right" @click="loadTrainings">刷新</el-button></template>
				<el-table :data="trainings" size="small" empty-text="还没有训练记录">
					<el-table-column prop="TrainingID" label="ID" width="70" />
					<el-table-column prop="ModelName" label="模型" width="110" />
					<el-table-column prop="DatasetName" label="数据集" width="160" />
					<el-table-column prop="TrainName" label="训练名" min-width="200" />
					<!-- 轮次/准确率/loss 合并成一列：准确率与 loss 是一对必须成对看的指标，挤在一列省两格宽度；
					     轮次不另开列，改在指标下方用小字（无监督模型没有"轮次"这个概念，显示「—」） -->
					<el-table-column label="测试指标" min-width="170">
						<template #default="{ row }">
							<span v-if="isAnomalyTraining(row)" class="hint">无监督·无准确率</span>
							<span v-else>{{ fmt(row.Accuracy) }} / {{ fmt(row.Loss) }}</span>
							<div class="hint">轮次 {{ isAnomalyTraining(row) ? '—' : (row.Epochs ?? '—') }}</div>
						</template>
					</el-table-column>
					<el-table-column label="状态" width="90">
						<template #default="{ row }"><el-tag :type="row.Status === '成功' ? 'success' : 'danger'" size="small">{{ row.Status }}</el-tag></template>
					</el-table-column>
					<el-table-column prop="StartedDate" label="开始时间" min-width="150" />
				</el-table>
			</el-card>
		</el-tab-pane>

		<!-- ============ 推理任务 ============ -->
		<el-tab-pane label="推理任务" name="tasks">
			<el-card shadow="never">
				<template #header><span>推理任务（读库）</span><el-button link type="primary" style="float: right" @click="loadTasks">刷新</el-button></template>
				<el-table :data="tasks" size="small" empty-text="还没有推理任务">
					<el-table-column prop="InferenceTaskID" label="ID" width="70" />
					<el-table-column prop="ModelName" label="模型" width="110" />
					<el-table-column prop="TaskType" label="类型" width="150" />
					<el-table-column prop="TrainingID" label="锚点训练" width="100" />
					<!-- 「目标数据集」只显示一个 ID，价值低；改成显示后端早就 SELECT 出来、前端一直没用的
					     ResultSummary（db.recent_inference_tasks 的列里有它），内容长所以溢出用 tooltip 看全 -->
					<el-table-column label="摘要" min-width="220" show-overflow-tooltip>
						<template #default="{ row }">{{ row.ResultSummary || '—' }}</template>
					</el-table-column>
					<el-table-column label="状态" width="90">
						<template #default="{ row }"><el-tag :type="row.Status === '成功' ? 'success' : 'danger'" size="small">{{ row.Status }}</el-tag></template>
					</el-table-column>
					<el-table-column prop="CompletedDate" label="完成时间" min-width="150" />
					<el-table-column label="操作" width="90" fixed="right">
						<template #default="{ row }"><el-button link type="primary" @click="showTask(row.InferenceTaskID)">明细</el-button></template>
					</el-table-column>
				</el-table>
			</el-card>
		</el-tab-pane>
	</el-tabs>

	<!-- meta / 任务明细 弹窗 -->
	<!-- 登记弹窗：只用来「编辑」（新增登记改成从「上传模型」走，上传时自动登记） -->
	<el-dialog v-model="dialog.formVisible" :title="`编辑模型 ${dialog.originName || form.ModelName}`" width="520px">
		<el-form label-width="110px" size="small">
			<el-form-item label="模型名 *">
				<el-input v-model="form.ModelName" placeholder="唯一键，如 1DCNN" />
				<div class="hint">
					改名会一并重命名产物目录 <code>data/models/&lt;名&gt;/</code>，并更新库里已存的路径
				</div>
			</el-form-item>
			<el-form-item label="类型">
				<el-select v-model="form.ModelType" style="width: 100%">
					<el-option label="分类（Classification）" value="Classification" />
					<el-option label="异常检测（AnomalyDetection）" value="AnomalyDetection" />
					<el-option label="回归（Regression）" value="Regression" />
				</el-select>
			</el-form-item>
			<el-form-item label="接口"><el-input v-model="form.ApiEndpoint" placeholder="/predict" /></el-form-item>
			<el-form-item label="状态">
				<el-select v-model="form.Status" style="width: 100%" allow-create filterable>
					<el-option label="可运行" value="可运行" />
					<el-option label="未训练" value="未训练" />
					<el-option label="已停用" value="已停用" />
				</el-select>
			</el-form-item>
			<el-form-item label="说明"><el-input v-model="form.Description" type="textarea" :rows="3" /></el-form-item>
		</el-form>
		<div class="hint">编辑只改登记信息；换权重请用工具栏的「上传模型」（同名会直接替换旧产物）。</div>
		<template #footer>
			<el-button @click="dialog.formVisible = false">取消</el-button>
			<el-button type="primary" @click="submitForm">保存</el-button>
		</template>
	</el-dialog>

	<!-- 上传弹窗：文件夹，或单个/多个模型文件 -->
	<el-dialog v-model="dialog.uploadVisible" title="上传模型（文件夹，或单个/多个文件）" width="560px">
		<el-form label-width="90px" size="small">
			<el-form-item label="模型名 *">
				<el-input v-model="uploadForm.name" placeholder="唯一键，如 1DCNN；同名会直接替换旧产物" />
			</el-form-item>
			<el-form-item label="说明"><el-input v-model="uploadForm.description" placeholder="可选" /></el-form-item>
		</el-form>
		<div class="hint">
			权重文件必须有：<code>.h5 .keras .pt .pth .pkl</code>；<code>scaler.npz</code>、<code>meta.json</code> 可选。
			服务端会先<strong>判断这是不是一个模型</strong>（看文件内容，不只看后缀），再自动读出输入长度与类别数。
			同一个模型名再次上传会<strong>直接替换</strong>旧产物（后端会在结果里提示"已替换旧产物"）。
		</div>
		<div class="mt" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
			<input ref="folderInput" type="file" webkitdirectory directory multiple style="display: none" @change="onPick" />
			<input ref="fileInput" type="file" multiple accept=".h5,.keras,.pt,.pth,.pkl,.pickle,.npz,.json" style="display: none" @change="onPick" />
			<el-button size="small" @click="pickFolder">选择整个文件夹</el-button>
			<el-button size="small" @click="pickFiles">选择模型文件（可多选）</el-button>
			<el-button v-if="picked.length" size="small" text @click="clearPicked">清空</el-button>
		</div>
		<el-table v-if="picked.length" :data="picked" size="small" max-height="150" class="mt">
			<el-table-column prop="name" label="文件" min-width="200" />
			<el-table-column prop="size_kb" label="KB" width="90" />
			<el-table-column label="识别为" width="100">
				<template #default="{ row }">
					<el-tag :type="row.kind === '权重' ? 'success' : row.kind === '其他' ? 'info' : 'warning'" size="small">{{ row.kind }}</el-tag>
				</template>
			</el-table-column>
		</el-table>
		<div v-if="uploadMsg" class="hint mt" style="white-space: pre-line">{{ uploadMsg }}</div>
		<template #footer>
			<el-button @click="dialog.uploadVisible = false">取消</el-button>
			<el-button type="primary" :loading="uploading" @click="doUploadModel">上传</el-button>
		</template>
	</el-dialog>

	<!-- 发布（导出下载）弹窗：打包 → 给下载地址 → 列历史 -->
	<el-dialog v-model="dialog.exportVisible" :title="`发布模型：${exportForm.model}`" width="720px">
		<div class="hint">
			发布 = 把训练产物连同<strong>它活下去所必需的一切</strong>打成 zip：权重 + <code>scaler.npz</code>
			+ 网络结构（PyTorch 需要）+ 自动生成的 <code>README.md</code> / <code>requirements.txt</code>
			/ <code>example_infer.py</code>。
			之所以不是"直接下载权重文件"：单独一个权重<strong>外人用不了</strong>（分类模型缺 scaler 会算错、
			PyTorch 缺结构加载不出来）。
		</div>
		<el-form label-width="110px" size="small" class="mt">
			<el-form-item label="版本号">
				<el-input v-model="exportForm.version" :placeholder="`留空自动递增（下一个 ${exportForm.nextVersion}）`" />
			</el-form-item>
			<el-form-item label="来源训练">
				<el-select v-model="exportForm.training_id" clearable placeholder="留空 = 该模型最近一次成功的训练" style="width: 100%">
					<el-option v-for="t in exportForm.trainings" :key="t.TrainingID"
						:label="`#${t.TrainingID} ${t.TrainName || ''} · ${t.Status}${t.Accuracy != null ? ' · acc=' + Number(t.Accuracy).toFixed(4) : ''}`"
						:value="t.TrainingID" />
				</el-select>
			</el-form-item>
			<el-form-item label="发布说明">
				<el-input v-model="exportForm.description" type="textarea" :rows="2" placeholder="可选，写进发布记录的备注" />
			</el-form-item>
		</el-form>

		<!-- 打包结果 -->
		<template v-if="exportResult">
			<el-alert type="success" :closable="false" show-icon
				:title="`发布成功：${exportResult.version} · ${exportResult.package}（${exportResult.size_kb} KB）`" />
			<div class="mt" style="display: flex; gap: 8px; align-items: center">
				<el-button type="primary" size="small" @click="downloadExport(exportResult.package)">下载这个包</el-button>
				<span class="hint">解压后先看 <code>README.md</code>；<code>example_infer.py</code> 可直接运行验证</span>
			</div>
			<el-table :data="exportResult.contents" size="small" class="mt" max-height="180">
				<el-table-column prop="filename" label="包内文件" min-width="180" />
				<el-table-column prop="size_kb" label="KB" width="90" align="right" />
			</el-table>
			<el-alert v-for="(w, i) in exportResult.warnings || []" :key="i" type="warning" :closable="false"
				show-icon class="mt" :title="w" />
		</template>

		<!-- 发布历史 -->
		<div class="mt">
			<div style="display: flex; align-items: center; gap: 8px">
				<b>发布历史</b>
				<el-button size="small" text @click="loadExports(exportForm.model)">刷新</el-button>
			</div>
			<el-table :data="exportList" size="small" class="mt" empty-text="还没有发布过" max-height="240">
				<el-table-column prop="Version" label="版本" width="70" />
				<el-table-column label="是否最新" width="90" align="center">
					<template #default="{ row }">
						<el-tag v-if="row.IsCurrent" type="success" size="small">最新版</el-tag>
						<span v-else class="hint">历史版</span>
					</template>
				</el-table-column>
				<el-table-column label="来源训练" min-width="150">
					<template #default="{ row }">
						<span v-if="row.TrainingID">#{{ row.TrainingID }} {{ row.TrainName || '' }}</span>
						<span v-else class="hint">—</span>
					</template>
				</el-table-column>
				<el-table-column prop="DeployStatus" label="状态" width="90" />
				<el-table-column prop="DeployedDate" label="发布时间" min-width="150" />
				<el-table-column label="操作" width="130" align="center">
					<template #default="{ row }">
						<el-button link type="primary" :disabled="row.DeployStatus !== '已导出'"
							@click="downloadExport(fileName(row.DeployedPath))">下载</el-button>
						<el-button link type="danger" :disabled="row.DeployStatus !== '已导出'"
							@click="removeExport(fileName(row.DeployedPath), row.DeploymentID)">删除</el-button>
					</template>
				</el-table-column>
			</el-table>
		</div>

		<template #footer>
			<el-button @click="dialog.exportVisible = false">关闭</el-button>
			<el-button type="primary" :loading="exporting" @click="doExport">打包发布</el-button>
		</template>
	</el-dialog>

	<!-- meta.json 全文：底部给一个固定的「关闭」按钮，JSON 区域自己内部滚动，
	     否则几百行的长文本会把按钮顶到屏幕外面去 -->
	<el-dialog v-model="dialog.meta" :title="`${dialog.model} 的 meta.json`" width="70%">
		<pre class="pre" style="max-height: 62vh; overflow: auto; margin: 0">{{ dialog.metaText }}</pre>
		<template #footer>
			<el-button type="primary" @click="dialog.meta = false">关闭</el-button>
		</template>
	</el-dialog>
	<el-dialog v-model="dialog.task" :title="`推理任务 #${dialog.taskId}`" width="80%">
		<el-descriptions v-if="dialog.taskData" :column="1" border size="small">
			<el-descriptions-item label="任务名">{{ dialog.taskData.TaskName }}</el-descriptions-item>
			<el-descriptions-item label="锚点 / 目标">TrainingID={{ dialog.taskData.TrainingID }}　DatasetID={{ dialog.taskData.TargetDatasetID }}</el-descriptions-item>
			<el-descriptions-item label="输入 / 输出">{{ dialog.taskData.InputPath }} → {{ dialog.taskData.OutputPath }}</el-descriptions-item>
			<el-descriptions-item label="结果摘要">{{ dialog.taskData.ResultSummary }}</el-descriptions-item>
		</el-descriptions>
		<el-table :data="dialog.taskData?.results || []" size="small" class="mt" max-height="380">
			<el-table-column prop="ResultID" label="结果ID" width="80" />
			<el-table-column prop="RowIdentifier" label="样本" min-width="200" />
			<el-table-column prop="SampleIndex" label="窗口" width="70" />
			<el-table-column prop="PredictedLabel" label="预测" min-width="140" />
			<el-table-column label="置信度" width="100"><template #default="{ row }">{{ fmt(row.Confidence) }}</template></el-table-column>
			<el-table-column prop="ActualClass" label="真实" width="80" />
		</el-table>
	</el-dialog>
	</div>
</template>

<script setup lang="ts" name="platformModel">
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { platformApi, fileUrl } from '/@/api/platform';

/** 写库回执的小标签 */
const Tag = defineComponent({
	props: { text: { type: Object, default: () => ({}) } },
	setup(props) {
		return () => {
			const d: any = props.text || {};
			return d.written
				? h('span', [`已写入（${d.dialect}）ID=${d.TrainingID ?? d.InferenceTaskID ?? '—'}`])
				: h('span', { style: 'color:#f56c6c' }, d.error || '未写入');
		};
	},
});

const route = useRoute();
const tab = ref<string>((route.query.tab as string) || 'list');
const fmt = (v: any) => (v === null || v === undefined ? '—' : Number(v).toFixed(4));
/** Models.ModelType 库里存英文，界面统一显示中文；不认识的值原样显示，别把信息吞掉 */
const TYPE_LABELS: Record<string, string> = { Classification: '分类', AnomalyDetection: '异常检测', Regression: '回归' };
const typeLabel = (v?: string) => {
	const raw = String(v || '');
	const hit = Object.keys(TYPE_LABELS).find((k) => k.toLowerCase() === raw.toLowerCase());
	return hit ? TYPE_LABELS[hit] : (raw || '—');
};

const artifacts = ref<any[]>([]);
const dbModels = ref<any[]>([]);
const trainings = ref<any[]>([]);
const tasks = ref<any[]>([]);
const datasets = ref<Record<string, any>>({});
const overview = ref<any>(null);
const form = reactive<any>({ ModelName: '', Description: '', ModelType: 'Classification', ApiEndpoint: '/predict', Status: '' });
const dialog = reactive<any>({ meta: false, model: '', metaText: '', task: false, taskId: 0, taskData: null,
	formVisible: false, originName: '', uploadVisible: false, exportVisible: false });
/** 上传弹窗自己的字段，跟「新增/编辑」登记弹窗解耦，互不影响 */
const uploadForm = reactive<any>({ name: '', description: '' });

// ---------- 模型发布（导出下载）----------
// exporting / exportResult 是本弹窗的"当前操作状态"，exportList 是该模型的发布历史。
// nextVersion 只是为了在占位符里提示"下一个会是几"，真正的版本号由后端算（避免前端猜错）。
const exporting = ref(false);
const exportResult = ref<any>(null);
const exportList = ref<any[]>([]);
const exportForm = reactive<any>({ model: '', version: '', description: '', training_id: undefined,
	trainings: [], nextVersion: 'v1' });

/** 从路径里取文件名：后端返回的 DeployedPath 可能是 Windows 反斜杠或 POSIX 斜杠 */
const fileName = (p: string) => String(p || '').split(/[\\/]/).pop() || '';

const datasetOptions = computed(() =>
	Object.entries(datasets.value).map(([k, d]: any) => ({
		label: `${k}　[${d.dataset_type === 'tabular' ? '表格' : 'mat'}，${d.file_count ?? 0} 个文件]`,
		value: d.dataset_dir,
		kind: d.dataset_type,
	}))
);
const fileOptions = computed(() => {
	const out: any[] = [];
	Object.entries(datasets.value).forEach(([k, d]: any) => {
		(d.files || []).filter((f: any) => f.on_disk).forEach((f: any) => {
			out.push({ label: `${k} / ${f.filename}（${f.label}）`, value: `${d.dataset_dir}\\${f.filename}` });
		});
	});
	return out;
});

const train = reactive<any>({ model: '1dcnn', dataset_type: 'matlab', dataset_dir: '', signal_column: '',
	epochs: 10, length: 784, number: 600, stride: 150, batch_size: 128, seed: 42, dataset: 'CWRU-0HP', strict: true,
	// baseline_file 是 training.py 早就读的既有参数（_train_adtk 拿它 + dataset_dir 找正常样本文件），
	// 不是新契约；非 adtk 模型不会用到它，但键照旧随 payload 发出去，后端各分支只取自己认识的键
	baseline_file: 'normal_0_97.mat' });
const pred = reactive<any>({ model: '1dcnn', path: '', column: '', index: 0, limit: 4, top_k: 3 });
/** 训练表单是不是在配 adtk（无监督）：决定哪些控件该显示——adtk 不读 epochs/batch_size/signal_column/strict，
 *  改了也不生效的控件比没有控件更误导，所以这些项对 adtk 直接隐藏（隐藏不上删键，值照旧发送） */
const isAdtkTrain = computed(() => train.model === 'adtk');

const training = ref(false);
const predicting = ref(false);
const elapsed = ref(0);
const trainResult = ref<any>(null);
const predResult = ref<any>(null);

/** 模型清单 = Models 表登记信息 与 产物参数 合并成一行（1dcnn ↔ 1DCNN 用忽略大小写匹配） */
const mergedRows = computed(() => {
	const map = new Map<string, any>();
	(dbModels.value || []).forEach((r: any) => {
		map.set(String(r.ModelName).toLowerCase(), { name: r.ModelName, reg: r, art: null });
	});
	(artifacts.value || []).forEach((a: any) => {
		const key = String(a.model).toLowerCase();
		if (!map.has(key)) map.set(key, { name: a.model, reg: null, art: null });
		map.get(key).art = a;              // 一个模型只有一个产物，同名直接覆盖
	});
	return [...map.values()];
});
/** 当前产物（唯一那个）；模型还没有产物时是 null —— 详情卡照常渲染，字段显示「—」 */
const curArt = computed(() => overview.value?.artifact || null);
const isAnomalyModel = computed(() => {
	const reg = overview.value?.registration || {};
	return String(reg.ModelType || '').toLowerCase() === 'anomalydetection'
		|| curArt.value?.framework === 'adtk'
		|| (overview.value?.params || {}).detector != null;
});
/** 阈值/分数是 1e-3 量级的小数，用科学计数法更好读 */
const fmtThreshold = (v: any) => (v === null || v === undefined ? '—' : Number(v).toExponential(3));
/** 比率 → 百分比（0.0123 → "1.23%"）：基线误报率、异常占比这类 0~1 的字段用它 */
const fmtPct = (v: any) => (v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(2)}%`);
/** 异常分数：大数用定点、小数用科学计数法，别把 4.5e-5 显示成 0.0000 */
const fmtScore = (v: any) => {
	if (v === null || v === undefined) return '—';
	const n = Number(v);
	return Math.abs(n) >= 0.001 ? n.toFixed(4) : n.toExponential(3);
};
/** 框架名压缩版（列表格子窄，tensorflow-keras 太长撑不下） */
const FW_LABELS: Record<string, string> = { 'tensorflow-keras': 'Keras', pytorch: 'PyTorch', adtk: 'ADTK' };
const fwLabel = (v?: string) => FW_LABELS[String(v || '')] || (v || '—');
/** 列表行是不是异常检测（列表数据来自 /models，没有 overview，只能靠 registration + 产物判断） */
const isAnomalyRow = (row: any) => String(row?.reg?.ModelType || '').toLowerCase() === 'anomalydetection'
	|| row?.art?.framework === 'adtk'
	|| (row?.art?.params || {}).detector != null;
/** 列表「指标」列：分类/回归看测试准确率，异常检测看基线误报率（无监督没有准确率） */
const rowMetric = (row: any): { value: string; label: string } => {
	const metrics = row?.art?.metrics || {};
	if (isAnomalyRow(row)) {
		const rate = metrics.baseline_false_positive_rate;
		return { value: rate === null || rate === undefined ? '—' : `${(Number(rate) * 100).toFixed(2)}%`,
			label: '基线误报率' };
	}
	const accuracy = metrics.test_accuracy;
	return { value: accuracy === null || accuracy === undefined ? '—' : fmt(accuracy), label: '测试准确率' };
};
/** 训练结果是不是「异常检测（adtk 无监督）」那一套 —— 决定结果卡走哪个模板。
 *  后端 _train_adtk 的 metrics.classification_report 恒为 None，并带一条 note 说明"无监督模型没有准确率"，
 *  dataset_stats 里也只有基线/检测器这类字段；分类模型一定有 classification_report，故以它为主判据，
 *  note / 基线字段作兜底（训练在出指标前就失败时 metrics 可能只有 note）。 */
const isAnomalyResult = (): boolean => {
	const metrics = trainResult.value?.metrics || {};
	if (metrics.classification_report != null) return false;
	const stats = trainResult.value?.dataset_stats || {};
	return metrics.note != null || stats.detector != null || stats.baseline_source != null;
};
/** 训练记录行是不是异常检测（无监督）。
 *  ⚠️ 「Accuracy/Loss 为 NULL」这个判据必须再叠一层 Status==='成功'：**失败**的训练行指标同样是 NULL，
 *  那是"这次没跑出指标"，跟"这个模型压根没有准确率"是两回事，混在一起会把失败行也写成「无监督·无准确率」。
 *  模型名 adtk 单独判：无监督路线本身就没有准确率，与这一次成功与否无关。 */
const isAnomalyTraining = (row: any): boolean =>
	String(row?.ModelName || '').toLowerCase() === 'adtk'
	|| (row?.Status === '成功' && row?.Accuracy == null && row?.Loss == null);
const labelRows = computed(() =>
	((overview.value?.labels as string[]) || []).map((label, id) => ({ id, label }))
);

const loadModels = async () => {
	const res: any = await platformApi.models();
	artifacts.value = res.artifacts || [];
	dbModels.value = res.db_models || [];
};
const tableRef = ref<any>();
const onRowClick = (row: any) => { if (row?.name) loadOverview(row.name); };
/** 关掉下方的「模型展示」卡片：清空 overview，同时取消表格行高亮
 *  （只清 overview 的话会出现"行还高亮着、卡片却说尚未选择模型"的错位） */
const closeOverview = () => {
	overview.value = null;
	tableRef.value?.setCurrentRow?.();
};
const loadOverview = async (name: string) => {
	overview.value = (await platformApi.modelOverview(name)) as any;
};

/** 编辑登记信息（新增登记已取消：上传模型时后端会自动登记一行） */
const openEdit = (row: any) => {
	const r = row.reg || {};
	dialog.originName = row.name;                 // 改名要拿老名字当 URL，所以单独记一份
	Object.assign(form, { ModelName: row.name, Description: r.Description || '', ModelType: r.ModelType || 'Classification',
		ApiEndpoint: r.ApiEndpoint || '', Status: r.Status || '' });
	dialog.formVisible = true;
};
const submitForm = async () => {
	if (!form.ModelName) { ElMessage.warning('模型名不能为空'); return; }
	try {
		const payload: any = { Description: form.Description, ModelType: form.ModelType,
			ApiEndpoint: form.ApiEndpoint, Status: form.Status };
		if (form.ModelName !== dialog.originName) payload.NewModelName = form.ModelName;   // 改名：连产物目录一起搬
		const res: any = await platformApi.updateModel(dialog.originName, payload);
		const rn = res?.rename;
		ElMessage.success(rn
			? `已改名为 ${rn.to}` + (rn.artifact_dir_moved ? `（产物目录已搬到 ${rn.artifact_dir}）` : '（无产物目录，只改了登记）')
				+ (rn.note ? `；${rn.note}` : '')
			: `已更新模型 ${form.ModelName}`);
	} catch (e: any) {
		ElMessage.error('保存失败：' + (e?.response?.data?.error || e?.message || e));
		return;                                   // 失败就别关弹窗，让用户改完再提交
	}
	dialog.formVisible = false;
	await loadModels();
	if (overview.value) await loadOverview(overview.value.model);
};

/** 删除：先查引用，把"被哪些表引用多少行"放进确认框 */
const removeModel = async (row: any) => {
	let refs: any = {};
	try { refs = (await platformApi.modelReferences(row.name)) as any; } catch (e) { /* 未登记时忽略 */ }
	const detail = refs?.references ? JSON.stringify(refs.references) : '（无引用信息）';
	const hasRefs = (refs?.total || 0) > 0;
	try {
		await ElMessageBox.confirm(
			`将删除 Models 表里 ${row.name} 的登记行。\n引用情况：${detail}` +
			(hasRefs ? '\n⚠ 仍被引用：确认后将连带删除这些训练/推理记录（不可撤销）' : ''),
			hasRefs ? '危险操作（有引用）' : '确认删除', { type: 'warning' });
	} catch { return; }
	const res: any = await platformApi.deleteModelRecord(row.name, hasRefs);
	ElMessage.success(`已删除 ${res.deleted}${res.cascaded ? '（已连带清理引用记录）' : ''}`);
	if (overview.value?.model === row.name) overview.value = null;
	await loadModels();
};

/** 上传模型：文件夹或单个/多个文件都行；不再手填输入长度/类别数——服务端探测后自动识别 */
const folderInput = ref<HTMLInputElement>();
const fileInput = ref<HTMLInputElement>();
const picked = ref<{ name: string; size_kb: number; kind: string }[]>([]);
const uploading = ref(false);
const uploadMsg = ref('');
const pickKind = (n: string) =>
	/\.(h5|keras|pt|pth|pkl|pickle)$/i.test(n) ? '权重'
		: n === 'scaler.npz' ? 'scaler' : n === 'meta.json' ? 'meta' : '其他';
/** 两个隐藏的原生 input（浏览器没有"文件夹 + 文件"合一的入口），由两个按钮分别去点 */
const pickFolder = () => folderInput.value?.click();
const pickFiles = () => fileInput.value?.click();
/** 两个选择器里选中的文件合起来 */
const pickedFiles = (): File[] => [
	...Array.from(folderInput.value?.files || []),
	...Array.from(fileInput.value?.files || []),
];
const onPick = () => {
	picked.value = pickedFiles().map((f) => ({
		name: f.name, size_kb: Number((f.size / 1024).toFixed(1)), kind: pickKind(f.name),
	}));
	uploadMsg.value = picked.value.some((f) => f.kind === '权重')
		? '' : '⚠ 没识别到权重文件（.h5/.keras/.pt/.pth/.pkl），服务端会判定「不是一个模型」并拒绝';
};
const clearPicked = () => {
	if (folderInput.value) folderInput.value.value = '';
	if (fileInput.value) fileInput.value.value = '';
	picked.value = [];
	uploadMsg.value = '';
};
/** 工具栏「上传模型」：每次打开都是干净的空表单 */
const openUpload = () => {
	clearPicked();
	uploadForm.name = '';
	uploadForm.description = '';
	dialog.uploadVisible = true;
};
const doUploadModel = async () => {
	const files = pickedFiles();
	if (!files.length) { ElMessage.warning('先点「选择整个文件夹」或「选择模型文件」'); return; }
	if (!uploadForm.name) { ElMessage.warning('先填模型名'); return; }
	const fd = new FormData();
	fd.append('name', uploadForm.name);
	fd.append('description', uploadForm.description || '');
	files.forEach((f) => fd.append('file', f, f.name));
	uploading.value = true;
	uploadMsg.value = '';
	try {
		const res: any = await platformApi.uploadModel(fd);
		uploadMsg.value = [
			`已上传 → ${res.directory}`,
			`框架 ${res.framework}`,
			`权重 ${res.probe?.weights || res.weights}`,
			`input_len=${res.input_len ?? '未识别(推理按默认 784)'}`,
			`${res.num_classes ?? '?'} 类`,
			res.meta_generated ? '已自动生成 meta.json' : '使用文件夹里的 meta.json',
		].join(' · ') + (res.warnings?.length ? `\n⚠ ${res.warnings.join('；')}` : '');
		ElMessage.success('模型上传成功');
		clearPicked();
		await loadModels();
		await loadOverview(res.model);
		dialog.uploadVisible = false;
	} catch (e: any) {
		const data = e?.response?.data;
		const detail = (data?.detail || []).map((d: any) => `${d.filename}：${d.reason}`).join('\n');
		uploadMsg.value = '上传失败：' + (data?.error || e?.message || e) + (detail ? `\n${detail}` : '');
		ElMessage.error('上传失败：' + (data?.error || e?.message || e));
	} finally {
		uploading.value = false;
	}
};

// ---------- 模型发布（导出下载）----------
/** 点「发布」：打开弹窗并预载该模型的发布历史与可选训练列表。 */
const openExport = async (row: any) => {
	exportResult.value = null;
	exportList.value = [];
	exportForm.model = row.name;
	exportForm.version = '';
	exportForm.description = '';
	exportForm.training_id = undefined;
	exportForm.trainings = [];
	exportForm.nextVersion = 'v1';
	dialog.exportVisible = true;
	await Promise.all([loadExports(row.name), loadExportTrainings(row.name)]);
};

/** 取该模型的发布历史（磁盘包 + 库记录），并推算"下一个版本号"用于占位提示。 */
const loadExports = async (name: string) => {
	if (!name) return;
	try {
		const res: any = await platformApi.exports(name);
		exportList.value = res.deployments || [];
		// 版本号只按**已导出**的条数推，与后端 count_deployments 口径一致：
		// 失败/已删除的记录不占版本号，否则提示会和后端算出来的对不上
		const done = exportList.value.filter((d: any) => d.DeployStatus === '已导出').length;
		exportForm.nextVersion = `v${done + 1}`;
	} catch (e: any) {
		exportList.value = [];
		ElMessage.warning('发布历史读取失败：' + (e?.response?.data?.error || e?.message || e));
	}
};

/** 该模型的训练记录（供"来源训练"下拉选择）。 */
const loadExportTrainings = async (name: string) => {
	try {
		const res: any = await platformApi.trainings(100);
		const all = res.trainings || [];
		// 后端 latest_training 按**库表正式名**匹配，大小写敏感度交给它，这里宽松过滤即可
		exportForm.trainings = all.filter((t: any) => String(t.ModelName || '').toLowerCase() === String(name).toLowerCase());
	} catch {
		exportForm.trainings = [];
	}
};

/** 打包发布。 */
const doExport = async () => {
	exporting.value = true;
	try {
		const body: any = {};
		if (exportForm.version) body.version = exportForm.version;
		if (exportForm.description) body.description = exportForm.description;
		if (exportForm.training_id) body.training_id = exportForm.training_id;
		const res: any = await platformApi.exportModel(exportForm.model, body);
		exportResult.value = res;
		ElMessage.success(`已发布 ${res.version}：${res.package}`);
		await loadExports(exportForm.model);
		await loadModels();
	} catch (e: any) {
		const d = e?.response?.data;
		ElMessage.error('发布失败：' + (d?.error || e?.message || e) + (d?.hint ? `（${d.hint}）` : ''));
	} finally {
		exporting.value = false;
	}
};

/** 下载一个发布包：走 fileUrl() 拼绝对地址，用 <a download> 触发浏览器下载。 */
const downloadExport = (pkg: string) => {
	if (!pkg) return;
	// ⚠️ 路由参数要能原样被后端解析，所以按名字拼 URL；fileUrl() 会补上 VITE_API_URL 前缀
	const url = fileUrl(`/models/${encodeURIComponent(exportForm.model)}/exports/${encodeURIComponent(pkg)}`);
	const a = document.createElement('a');
	a.href = url;
	a.download = pkg;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
};

/** 删除一个发布包（只删磁盘文件，库记录标成「已删除」留痕）。 */
const removeExport = async (pkg: string, id: number) => {
	try {
		await ElMessageBox.confirm(`删除发布包 ${pkg}？磁盘文件会被删除，库里仍保留一条「已删除」记录。`,
			'确认删除', { type: 'warning' });
	} catch { return; }
	try {
		const res: any = await platformApi.deleteExport(exportForm.model, pkg);
		ElMessage.success(`已删除，释放 ${res.freed_kb} KB`);
		await loadExports(exportForm.model);
		await loadModels();
	} catch (e: any) {
		ElMessage.error('删除失败：' + (e?.response?.data?.error || e?.message || e));
	}
};

const loadTrainings = async () => { trainings.value = ((await platformApi.trainings(20)) as any).trainings || []; };
const loadTasks = async () => { tasks.value = ((await platformApi.tasks(20)) as any).tasks || []; };
const loadDatasets = async () => {
	datasets.value = (await platformApi.datasets()) as any;
	if (!train.dataset_dir) {
		const first = datasetOptions.value[0];
		if (first) { train.dataset_dir = first.value; train.dataset_type = (first as any).kind; }
	}
};

const syncSource = () => {
	const hit = datasetOptions.value.find((o) => o.value === train.dataset_dir);
	if (hit) train.dataset_type = (hit as any).kind;
};
const applyDefaults = () => {
	if (train.model === '1dcnn') { train.epochs = 10; train.number = 600; }
	else if (train.model === 'cwt_cnn') { train.epochs = 50; train.number = 300; }
	else { train.epochs = 1; }
};

const showMeta = async (name: string) => {
	const res: any = await platformApi.artifact(name);
	dialog.model = name;
	dialog.metaText = JSON.stringify(res, null, 2);
	dialog.meta = true;
};
const showTask = async (id: number) => {
	dialog.taskId = id;
	dialog.taskData = await platformApi.taskDetail(id);
	dialog.task = true;
};

const doTrain = async () => {
	training.value = true;
	elapsed.value = 0;
	const timer = setInterval(() => (elapsed.value += 1), 1000);
	try {
		const payload: any = { ...train };
		payload.strict = !!train.strict;
		if (!payload.signal_column) delete payload.signal_column;
		trainResult.value = await platformApi.train(payload);
		await Promise.all([loadModels(), loadTrainings()]);
	} finally {
		clearInterval(timer);
		training.value = false;
	}
};

const doPredict = async () => {
	predicting.value = true;
	try {
		const payload: any = { ...pred };
		if (!payload.column) delete payload.column;
		predResult.value = await platformApi.predict(payload);
		await loadTasks();
	} finally {
		predicting.value = false;
	}
};

onMounted(async () => {
	await Promise.all([loadModels(), loadTrainings(), loadTasks(), loadDatasets()]);
});
</script>

<style scoped lang="scss">
.mb { margin-bottom: 16px; }
.mt { margin-top: 16px; }
/* 本页原来漏了这条定义（其他 4 个 platform 页面各自的 scoped style 里都有一份），
   于是本页十几处 class="hint" 的说明文字一直按正文渲染、跟主内容抢注意力；照抄其余页面的写法补齐 */
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.empty { color: var(--el-text-color-secondary); text-align: center; padding: 24px 0; }
.pre { max-height: 320px; overflow: auto; background: #141413; color: #ede9e0; padding: 12px; border-radius: 6px; font-size: 12px; }
.figs { display: flex; flex-wrap: wrap; gap: 12px; }
.fig { width: 260px; height: 170px; border: 1px solid var(--el-border-color); border-radius: 6px; background: #fff; }
</style>
