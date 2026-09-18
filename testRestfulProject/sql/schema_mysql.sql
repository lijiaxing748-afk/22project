/* ================================================================
   模型管理库 · MySQL 版 建表脚本
   ----------------------------------------------------------------
   目标数据库: model_management
   字符集: utf8mb4 / utf8mb4_unicode_ci
   引擎: InnoDB
   表清单:
     1. Datasets            数据集
     2. Models              模型
     3. EdgeDevices         边缘设备
     4. Trainings           训练记录
     5. ModelInvocations    模型调用日志
     6. ModelDeployments    模型发布记录
     7. InferenceTasks      推理任务
     8. InferenceResults    推理结果明细
     9. Roles               角色
    10. Users               用户（登录凭据）
    11. OperationLogs       操作审计日志
   特点:
     - CREATE TABLE IF NOT EXISTS，可重复执行
     - 外键在建表时内联（依赖顺序已排好）
     - 种子数据用 INSERT IGNORE，依赖唯一键去重
   T-SQL → MySQL 映射:
     [int] IDENTITY(1,1)   -> INT AUTO_INCREMENT
     [nvarchar](n)         -> VARCHAR(n)
     [nvarchar](max)       -> LONGTEXT
     [datetime2](7)        -> DATETIME(6)
     [bit]                 -> TINYINT(1)
     [float]               -> DOUBLE
     SYSDATETIME()         -> CURRENT_TIMESTAMP(6)
   ================================================================ */

CREATE DATABASE IF NOT EXISTS `model_management`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `model_management`;


/* ---------------- 1. Datasets ---------------- */
CREATE TABLE IF NOT EXISTS `Datasets` (
    /* 数据集：DatasetName 唯一，db.ensure_dataset() 按它做"有就取、没有就建" */
    `DatasetID`    INT           NOT NULL AUTO_INCREMENT,
    `DatasetName`  VARCHAR(100)  NOT NULL,
    `Source`       VARCHAR(200)  NULL,        -- CWRU 官方数据集 / 用户上传 / ADHOC 临时登记
    `SampleCount`  INT           NULL,        -- 样本（窗口）数
    `ClassCount`   INT           NULL,        -- 类别数；无监督模型为 NULL
    `DataPath`     VARCHAR(500)  NULL,        -- 数据目录（接口返回时已脱敏）
    `Description`  VARCHAR(500)  NULL,
    `CreatedDate`  DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`DatasetID`),
    UNIQUE KEY `UQ_Datasets_DatasetName` (`DatasetName`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 2. Models ---------------- */
CREATE TABLE IF NOT EXISTS `Models` (
    /* 模型登记表：ModelName 唯一；训练/上传时按名字"有就取用、不重复插" */
    `ModelID`     INT           NOT NULL AUTO_INCREMENT,
    `ModelName`   VARCHAR(100)  NOT NULL,
    `Description` VARCHAR(500)  NULL,
    `ApiEndpoint` VARCHAR(255)  NULL,         -- 该模型的调用入口，一般为 /predict
    `ModelType`   VARCHAR(50)   NULL,         -- Classification / AnomalyDetection / Regression
    `CreatedDate` DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `IsActive`    TINYINT(1)    NULL DEFAULT 1,
    `Status`      VARCHAR(20)   NULL,         -- 可运行 / 未训练 …
    PRIMARY KEY (`ModelID`),
    UNIQUE KEY `UQ_Models_ModelName` (`ModelName`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 3. EdgeDevices ---------------- */
CREATE TABLE IF NOT EXISTS `EdgeDevices` (
    /* 边缘设备：当前 model_service 不写这张表（「边缘设备」支线未落地），保留结构供后续部署使用 */
    `DeviceID`      INT           NOT NULL AUTO_INCREMENT,
    `DeviceName`    VARCHAR(100)  NOT NULL,
    `DeviceType`    VARCHAR(50)   NULL,
    `IPAddress`     VARCHAR(45)   NULL,       -- IPv4/IPv6 文本
    `Location`      VARCHAR(255)  NULL,
    `HardwareSpecs` LONGTEXT      NULL,       -- 硬件规格（自由文本 / JSON）
    `EdgeStatus`    VARCHAR(20)   NULL,       -- 设备侧运行状态（与 Status 语义重叠，见 InferenceResults 的冗余列备注）
    `LastHeartbeat` DATETIME(6)   NULL,
    `DeviceCode`    VARCHAR(100)  NULL,
    `MacAddress`    VARCHAR(50)   NULL,
    `OsVersion`     VARCHAR(100)  NULL,
    `Status`        VARCHAR(20)   NULL,       -- 本平台的登记状态
    `IsActive`      TINYINT(1)    NULL DEFAULT 1,
    `Remark`        VARCHAR(500)  NULL,
    `CreatedDate`   DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`DeviceID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 4. Trainings ---------------- */
CREATE TABLE IF NOT EXISTS `Trainings` (
    /* 训练记录：被 ModelInvocations / ModelDeployments / InferenceTasks 三张表引用，
       是整套结构的中枢——InferenceTasks.TrainingID 就是这里的"权威锚点" */
    `TrainingID`    INT           NOT NULL AUTO_INCREMENT,
    `ModelID`       INT           NOT NULL,   -- 外键，模型必须已登记
    `DatasetID`     INT           NULL,       -- 可空：删除数据集时会置空
    `TrainName`     VARCHAR(200)  NULL,       -- 形如 1dcnn-20250912-193000
    `Epochs`        INT           NULL,
    `BatchSize`     INT           NULL,
    `Accuracy`      DOUBLE        NULL,       -- 测试集准确率；无监督模型为 NULL
    `Loss`          DOUBLE        NULL,
    `ModelPath`     VARCHAR(500)  NULL,       -- 权重文件路径，指向 data/models/<模型>/vN/…
    `Status`        VARCHAR(20)   NULL,       -- 成功 / 失败
    `CreatedDate`   DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `StartedDate`   DATETIME(6)   NULL,
    `CompletedDate` DATETIME(6)   NULL,
    `CreatedBy`     VARCHAR(100)  NULL,
    `Remark`        VARCHAR(500)  NULL,       -- 跳过越界窗口数、NaN 窗口数、日志/图目录等 JSON
    PRIMARY KEY (`TrainingID`),
    KEY `IX_Trainings_ModelID` (`ModelID`),
    CONSTRAINT `FK_Trainings_Models`   FOREIGN KEY (`ModelID`)   REFERENCES `Models` (`ModelID`),
    CONSTRAINT `FK_Trainings_Datasets` FOREIGN KEY (`DatasetID`) REFERENCES `Datasets` (`DatasetID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 5. ModelInvocations ---------------- */
CREATE TABLE IF NOT EXISTS `ModelInvocations` (
    /* 每次 /predict 留一条（失败也留）——最简单的调用审计日志 */
    `InvocationID`   INT           NOT NULL AUTO_INCREMENT,
    `ModelID`        INT           NOT NULL,
    `TrainingID`     INT           NULL,      -- 能定位到哪次训练时才有值
    `ApiEndpoint`    VARCHAR(255)  NULL,      -- 目前都是 /predict
    `RequestParams`  LONGTEXT      NOT NULL,  -- 请求参数 JSON（samples 体积太大，不记）
    `ResponseResult` LONGTEXT      NULL,      -- 成功摘要 / 失败错误 JSON
    `DurationMs`     INT           NULL,      -- 本次耗时（毫秒）
    `IsSuccess`      TINYINT(1)    NULL,      -- 1/0
    `StatusCode`     INT           NULL,      -- HTTP 状态码
    `ErrorMessage`   LONGTEXT      NULL,
    `ClientIP`       VARCHAR(50)   NULL,
    `Status`         VARCHAR(20)   NULL,      -- 成功 / 失败
    `InvocationDate` DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`InvocationID`),
    KEY `IX_ModelInvocations_ModelID_Date` (`ModelID`, `InvocationDate`),
    CONSTRAINT `FK_ModelInvocations_Models`    FOREIGN KEY (`ModelID`)    REFERENCES `Models` (`ModelID`),
    CONSTRAINT `FK_ModelInvocations_Trainings` FOREIGN KEY (`TrainingID`) REFERENCES `Trainings` (`TrainingID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 6. ModelDeployments ---------------- */
CREATE TABLE IF NOT EXISTS `ModelDeployments` (
    /* 模型发布记录（把某次训练产出的模型投放到某台边缘设备）。当前服务同样不写这张表 */
    `DeploymentID`    INT           NOT NULL AUTO_INCREMENT,
    `ModelID`         INT           NOT NULL,
    `TrainingID`      INT           NOT NULL,  -- 发布的是哪一次训练的产物
    `DeviceID`        INT           NOT NULL,
    `Version`         VARCHAR(50)   NULL,      -- 版本号，如 v2
    `VersionAlias`    VARCHAR(20)   NULL,      -- 别名，如 latest / stable
    `Environment`     VARCHAR(20)   NULL,      -- 环境：prod / test …
    `DeployUrl`       VARCHAR(255)  NULL,      -- 部署后的访问地址
    `DeployedPath`    VARCHAR(500)  NULL,      -- 设备上的产物路径
    `ServicePort`     INT           NULL,
    `RuntimeParams`   LONGTEXT      NULL,      -- 运行参数（JSON）
    `IsActive`        TINYINT(1)    NULL DEFAULT 1,
    `IsCurrent`       TINYINT(1)    NOT NULL DEFAULT 1,
    `DeployStatus`    VARCHAR(20)   NULL,
    `LastStatusCheck` DATETIME(6)   NULL,
    `DeployedDate`    DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `DeployedBy`      VARCHAR(100)  NULL,
    `ErrorMessage`    LONGTEXT      NULL,
    `Remark`          VARCHAR(500)  NULL,
    PRIMARY KEY (`DeploymentID`),
    KEY `IX_ModelDeployments_ModelID_Current` (`ModelID`, `IsCurrent`),
    KEY `IX_ModelDeployments_DeviceID` (`DeviceID`),
    CONSTRAINT `FK_ModelDeployments_Models`      FOREIGN KEY (`ModelID`)    REFERENCES `Models` (`ModelID`),
    CONSTRAINT `FK_ModelDeployments_Trainings`   FOREIGN KEY (`TrainingID`) REFERENCES `Trainings` (`TrainingID`),
    CONSTRAINT `FK_ModelDeployments_EdgeDevices` FOREIGN KEY (`DeviceID`)   REFERENCES `EdgeDevices` (`DeviceID`),
    CONSTRAINT `CK_ModelDeployments_ServicePort` CHECK (`ServicePort` IS NULL OR (`ServicePort` BETWEEN 1 AND 65535))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 7. InferenceTasks ---------------- */
CREATE TABLE IF NOT EXISTS `InferenceTasks` (
    /* 一次推理 = 一个任务，明细在 InferenceResults。
       TrainingID / TargetDatasetID 都是 NOT NULL 外键：推理前必须已有成功的训练记录 */
    `InferenceTaskID`  INT           NOT NULL AUTO_INCREMENT,
    `TrainingID`       INT           NOT NULL,  -- 权威锚点
    `TargetDatasetID`  INT           NOT NULL,  -- 内联样本会登记成 ADHOC-<模型> 数据集
    `TaskName`         VARCHAR(200)  NOT NULL,  -- 形如 predict-1dcnn-20250912-193000
    `TaskType`         VARCHAR(20)   NOT NULL,  -- classification / anomaly_detection
    `Status`           VARCHAR(20)   NULL,
    `InferenceParams`  LONGTEXT      NULL,      -- 请求参数 JSON
    `ResultSummary`    LONGTEXT      NULL,      -- 样本数、预测分布、模型版本…
    `ErrorMessage`     LONGTEXT      NULL,
    `DeploymentID`     INT           NULL,      -- 当前留空，等边缘设备支线落地后回填
    `ModelID`          INT           NULL,
    `DeviceID`         INT           NULL,      -- 同上，留空
    `InputPath`        VARCHAR(500)  NULL,      -- 输入来源文件路径
    `OutputPath`       VARCHAR(500)  NULL,      -- 出图目录
    `Progress`         INT           NULL,
    `CreatedDate`      DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `StartedDate`      DATETIME(6)   NULL,
    `CompletedDate`    DATETIME(6)   NULL,
    `CreatedBy`        VARCHAR(100)  NULL,
    PRIMARY KEY (`InferenceTaskID`),
    KEY `IX_InferenceTasks_Status` (`Status`),
    KEY `IX_InferenceTasks_TrainingID` (`TrainingID`),
    CONSTRAINT `FK_InferenceTasks_Trainings`   FOREIGN KEY (`TrainingID`)      REFERENCES `Trainings` (`TrainingID`),
    CONSTRAINT `FK_InferenceTasks_Datasets`    FOREIGN KEY (`TargetDatasetID`) REFERENCES `Datasets` (`DatasetID`),
    CONSTRAINT `FK_InferenceTasks_Models`      FOREIGN KEY (`ModelID`)         REFERENCES `Models` (`ModelID`),
    CONSTRAINT `FK_InferenceTasks_EdgeDevices` FOREIGN KEY (`DeviceID`)        REFERENCES `EdgeDevices` (`DeviceID`),
    CONSTRAINT `FK_InferenceTasks_Deployments` FOREIGN KEY (`DeploymentID`)    REFERENCES `ModelDeployments` (`DeploymentID`),
    CONSTRAINT `CK_InferenceTasks_Progress` CHECK (`Progress` IS NULL OR (`Progress` BETWEEN 0 AND 100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 8. InferenceResults ---------------- */
CREATE TABLE IF NOT EXISTS `InferenceResults` (
    /* 推理结果明细，一个任务 N 行（一个窗口一行）。
       分类任务用 PredictedClass/Label/Confidence，异常检测用 IsAnomaly/AnomalyScore，
       两类共享同一张表，所以近义列较多：PredictedValue 与 Confidence 同值、Score 又与
       Confidence 同值（三写一读，保留是为了兼容早期读取口径） */
    `ResultID`          BIGINT        NOT NULL AUTO_INCREMENT,
    `InferenceTaskID`   INT           NOT NULL,
    `RowIdentifier`     VARCHAR(100)  NULL,   -- 形如 内圈故障.csv#3，用来回溯这一行的来源
    `ResultTimestamp`   DATETIME(6)   NULL,   -- 该行结果的时间（取写入时刻）
    `PredictedValue`    DOUBLE        NULL,   -- 分类任务里的置信度（同类名字段）
    `AnomalyScore`      DOUBLE        NULL,   -- 异常检测：窗口重构误差 / 异常点占比
    `IsAnomaly`         TINYINT(1)    NULL,
    `PredictedCategory` VARCHAR(50)   NULL,   -- Classification / AnomalyDetection
    `Confidence`        DOUBLE        NULL,
    `FeatureSnapshot`   VARCHAR(500)  NULL,   -- top_k 的 JSON 快照（超 500 字符只记 truncated）
    `ModelID`           INT           NULL,
    `SampleIndex`       INT           NULL,   -- 窗口序号
    `PredictedClass`    INT           NULL,   -- 类别号
    `PredictedLabel`    VARCHAR(100)  NULL,   -- 类别中文名
    `Score`             DOUBLE        NULL,   -- 与 Confidence 同值
    `ActualClass`       INT           NULL,   -- 输入来自登记过的数据集文件时才有真值
    `ResultDetail`      LONGTEXT      NULL,   -- 判定细节 JSON（阈值、重构误差、相对倍数…）
    `CreatedDate`       DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`ResultID`),
    KEY `IX_InferenceResults_TaskID` (`InferenceTaskID`),
    KEY `IX_InferenceResults_Timestamp` (`ResultTimestamp`),
    CONSTRAINT `FK_InferenceResults_Tasks`  FOREIGN KEY (`InferenceTaskID`) REFERENCES `InferenceTasks` (`InferenceTaskID`),
    CONSTRAINT `FK_InferenceResults_Models` FOREIGN KEY (`ModelID`)          REFERENCES `Models` (`ModelID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 9. Roles ---------------- */
CREATE TABLE IF NOT EXISTS `Roles` (
    /* 角色：权限的唯一来源。RoleKey 是对外的稳定标识（前端按它判按钮显隐），
       RoleName 只是给人看的，改名字不影响逻辑。
       ⚠️ 权限是**写死在代码里**的（见 model_service/auth.py 的 _ROLE_PERMS），
       这张表只负责"有哪些角色、每个角色叫什么、是否启用"，不做通用的权限点配置。
       理由：本平台角色就三个、变动极少，做成通用 RBAC 权限表属于过度设计，
       而且会让"这个角色到底能干什么"变得只能查库才能回答。 */
    `RoleID`      INT           NOT NULL AUTO_INCREMENT,
    `RoleKey`     VARCHAR(50)   NOT NULL,     -- admin / engineer / operator
    `RoleName`    VARCHAR(100)  NOT NULL,     -- 超级管理员 / 算法工程师 / 现场操作员
    `Description` VARCHAR(500)  NULL,
    `IsActive`    TINYINT(1)    NULL DEFAULT 1,
    `CreatedDate` DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`RoleID`),
    UNIQUE KEY `UQ_Roles_RoleKey` (`RoleKey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 10. Users ---------------- */
CREATE TABLE IF NOT EXISTS `Users` (
    /* 用户：登录凭据 + 归属角色。
       密码只存哈希（werkzeug pbkdf2:sha256），**任何情况下都不落明文**，
       连"初始密码"都只在种子数据和重置接口里出现一次。
       ⚠️ PasswordHash 给 VARCHAR(255)：pbkdf2:sha256 的输出约 100 字符，
       未来若换 argon2 会更长，留足余量免得改列。 */
    `UserID`       INT           NOT NULL AUTO_INCREMENT,
    `Username`     VARCHAR(50)   NOT NULL,
    `PasswordHash` VARCHAR(255)  NOT NULL,
    `DisplayName`  VARCHAR(100)  NULL,        -- 界面上显示的名字（"张工"），不参与登录
    `RoleKey`      VARCHAR(50)   NOT NULL,    -- 直接存角色键，见下方"为什么不建 Users_Roles 中间表"
    `DeptName`     VARCHAR(100)  NULL,
    `Email`        VARCHAR(100)  NULL,
    `Mobile`       VARCHAR(30)   NULL,
    `IsActive`     TINYINT(1)    NULL DEFAULT 1,   -- 0 = 停用（离职/临时封禁），登录时拒绝
    `Remark`       VARCHAR(500)  NULL,
    `LastLogin`    DATETIME(6)   NULL,
    `LoginCount`   INT           NULL DEFAULT 0,
    /* 令牌版本：改密码时 +1，让此前签发的所有令牌立即失效。
       ⚠️ 令牌是无状态自签的，服务端没有"会话列表"可以清理，所以需要一个
       能被令牌携带、也能被服务端比对的计数器来实现"改密码即踢下线"。
       没这个字段的话，改完密码旧令牌照样能用满 12 小时。 */
    `TokenVersion` INT           NULL DEFAULT 0,
    `CreatedDate`  DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `UpdatedDate`  DATETIME(6)   NULL,
    PRIMARY KEY (`UserID`),
    UNIQUE KEY `UQ_Users_Username` (`Username`),
    KEY `IX_Users_RoleKey` (`RoleKey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/* ⚠️ 为什么**不**建 Users_Roles 中间表（多对多）：
   本项目一人只可能有一个角色——"算法工程师兼现场操作员"这种需求从没出现过，
   而多对多会立刻带来"取权限时要不要合并、冲突时听谁的"这类问题，
   收益为零、复杂度实打实。真需要一人多角色时再加中间表也不迟（本表 RoleKey 可留作主角色）。
   同理，RoleKey 没有加外键约束指向 Roles.RoleKey：种子数据里 Users 的插入顺序
   与 Roles 的先后关系会让外键成为负担，而角色键的合法性在代码里已经校验了。 */


/* ---------------- 11. OperationLogs ---------------- */
CREATE TABLE IF NOT EXISTS `OperationLogs` (
    /* 操作审计日志：记录"谁在什么时候干了什么"。
       工厂场景下最关心的是**训练、发布、删除**这三类动作——模型换了版本、
       谁把记录删了，都必须能追溯。
       ⚠️ 写入必须"尽力而为"：记日志失败**绝不能**让业务操作回滚。
       用户点了删除、文件真删了，却因为写日志失败而报错，那是本末倒置。
       所以 db.log_operation() 内部吞掉异常（见实现）。 */
    `LogID`         BIGINT        NOT NULL AUTO_INCREMENT,
    `Username`      VARCHAR(50)   NULL,       -- 操作人；未登录/匿名时为 NULL
    `RoleKey`       VARCHAR(50)   NULL,
    `Action`        VARCHAR(50)   NOT NULL,   -- login / train / predict / export / delete_model …
    `Target`        VARCHAR(200)  NULL,       -- 操作对象（模型名/包名/用户）
    `Detail`        LONGTEXT      NULL,       -- 请求摘要 JSON（已脱敏、已截断）
    `ClientIP`      VARCHAR(45)   NULL,
    `Result`        VARCHAR(20)   NULL,       -- 成功 / 失败
    `Message`       VARCHAR(500)  NULL,       -- 失败原因或补充说明
    `CreatedDate`   DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`LogID`),
    KEY `IX_OperationLogs_CreatedDate` (`CreatedDate`),
    KEY `IX_OperationLogs_Action` (`Action`),
    KEY `IX_OperationLogs_Username` (`Username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 初始数据 ---------------- */
INSERT IGNORE INTO `Datasets` (`DatasetName`, `Source`, `SampleCount`, `ClassCount`, `DataPath`, `Description`)
VALUES ('CWRU-0HP', 'Case Western Reserve University 轴承数据集', NULL, 10,
        'testRestfulProject/1DCNN/0HP', '驱动端(DE)振动信号，10 类轴承状态');

INSERT IGNORE INTO `Models` (`ModelName`, `Description`, `ApiEndpoint`, `ModelType`, `Status`)
VALUES
 ('1DCNN',   '一维卷积神经网络，CWRU 轴承振动信号 10 类故障分类。', NULL, 'Classification',   '可运行'),
 ('cwt_cnn', '与 1DCNN 同任务的 PyTorch 实现，输出混淆矩阵。',       NULL, 'Classification',   '可运行'),
 ('adtk',    '时序异常检测库（无监督），项目经 main.py 调用 PcaAD。', '/predict', 'AnomalyDetection', '可运行');
-- ⚠️ adtk 这行的 ApiEndpoint 原先是 '/todos'（flask_restful 官方示例路由，早已随示例一起删除）。
--    这个值会显示在「模型管理」页的「接口」一栏，留着等于给用户指一个 404 的地址；
--    三个模型实际都由 POST /predict 提供服务，所以改指 /predict。

/* 「模型发布/导出」用的占位设备。
   ⚠️ 为什么必须有这一行：ModelDeployments.DeviceID 是 **NOT NULL 外键 → EdgeDevices.DeviceID**，
   而本项目还没有真实边缘设备（代码里没有任何地方写 EdgeDevices），所以发布记录插不进去。
   备选方案是把 DeviceID 改成可空，但**行不通**：db.ensure_schema() 是幂等的，表已存在时
   一条语句都不执行，改了列定义对实验室已部署的库不会生效，得手工迁移。
   加一行种子数据没有这个问题，而且语义也成立——"导出到本地"本来就是一种投放目标。

   DeviceType='local' 是这里唯一的判别依据：界面/接口看到它就知道这不是真设备，
   而是"发布包落在了服务器磁盘上"。 */
INSERT IGNORE INTO `EdgeDevices` (`DeviceName`, `DeviceType`, `Location`, `EdgeStatus`, `Status`,
                                  `IsActive`, `Remark`, `CreatedDate`)
VALUES ('本地导出', 'local', '本机文件系统', '可用', '可用', 1,
        '不是真实边缘设备：仅为「模型发布」记录 ModelDeployments.DeviceID（该列是 NOT NULL 外键）。'
        '发布包落在 data/exports/<模型>/ 下供下载。',
        CURRENT_TIMESTAMP(6));
