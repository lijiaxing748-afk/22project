/* ================================================================
   模型管理库 · SQLite 版（开发/离线兜底用，与 schema_mysql.sql 同构）
   ----------------------------------------------------------------
   用途：在没接真库（MySQL / SQL Server）时，让 model_service 能把
        「训练 → 推理」的结果真实落库，从而端到端验证外键顺序。
   说明：
     - 表名、列名、外键命名与 schema_mysql.sql 完全一致，方便日后切换
     - SQLite 无 DATETIME 类型，统一用 TEXT 存 ISO8601 字符串
     - SQLite 无 AUTO_INCREMENT 语义差异，用 INTEGER PRIMARY KEY AUTOINCREMENT
     - 外键约束需 db.py 里 PRAGMA foreign_keys=ON 才生效
   ================================================================ */

/* ---------------- 1. Datasets ---------------- */
CREATE TABLE IF NOT EXISTS `Datasets` (
    `DatasetID`    INTEGER PRIMARY KEY AUTOINCREMENT,
    `DatasetName`  TEXT NOT NULL UNIQUE,
    `Source`       TEXT,
    `SampleCount`  INTEGER,
    `ClassCount`   INTEGER,
    `DataPath`     TEXT,
    `Description`  TEXT,
    `CreatedDate`  TEXT DEFAULT (datetime('now','localtime'))
);

/* ---------------- 2. Models ---------------- */
CREATE TABLE IF NOT EXISTS `Models` (
    `ModelID`     INTEGER PRIMARY KEY AUTOINCREMENT,
    `ModelName`   TEXT NOT NULL UNIQUE,
    `Description` TEXT,
    `ApiEndpoint` TEXT,
    `ModelType`   TEXT,
    `CreatedDate` TEXT DEFAULT (datetime('now','localtime')),
    `IsActive`    INTEGER DEFAULT 1,
    `Status`      TEXT
);

/* ---------------- 3. EdgeDevices ---------------- */
CREATE TABLE IF NOT EXISTS `EdgeDevices` (
    `DeviceID`      INTEGER PRIMARY KEY AUTOINCREMENT,
    `DeviceName`    TEXT NOT NULL,
    `DeviceType`    TEXT,
    `IPAddress`     TEXT,
    `Location`      TEXT,
    `HardwareSpecs` TEXT,
    `EdgeStatus`    TEXT,
    `LastHeartbeat` TEXT,
    `DeviceCode`    TEXT,
    `MacAddress`    TEXT,
    `OsVersion`     TEXT,
    `Status`        TEXT,
    `IsActive`      INTEGER DEFAULT 1,
    `Remark`        TEXT,
    `CreatedDate`   TEXT DEFAULT (datetime('now','localtime'))
);

/* ---------------- 4. Trainings ---------------- */
CREATE TABLE IF NOT EXISTS `Trainings` (
    `TrainingID`    INTEGER PRIMARY KEY AUTOINCREMENT,
    `ModelID`       INTEGER NOT NULL REFERENCES `Models`(`ModelID`),
    `DatasetID`     INTEGER REFERENCES `Datasets`(`DatasetID`),
    `TrainName`     TEXT,
    `Epochs`        INTEGER,
    `BatchSize`     INTEGER,
    `Accuracy`      REAL,
    `Loss`          REAL,
    `ModelPath`     TEXT,
    `Status`        TEXT,
    `CreatedDate`   TEXT DEFAULT (datetime('now','localtime')),
    `StartedDate`   TEXT,
    `CompletedDate` TEXT,
    `CreatedBy`     TEXT,
    `Remark`        TEXT
);

/* ---------------- 5. ModelInvocations ---------------- */
CREATE TABLE IF NOT EXISTS `ModelInvocations` (
    `InvocationID`   INTEGER PRIMARY KEY AUTOINCREMENT,
    `ModelID`        INTEGER NOT NULL REFERENCES `Models`(`ModelID`),
    `TrainingID`     INTEGER REFERENCES `Trainings`(`TrainingID`),
    `ApiEndpoint`    TEXT,
    `RequestParams`  TEXT NOT NULL,
    `ResponseResult` TEXT,
    `DurationMs`     INTEGER,
    `IsSuccess`      INTEGER,
    `StatusCode`     INTEGER,
    `ErrorMessage`   TEXT,
    `ClientIP`       TEXT,
    `Status`         TEXT,
    `InvocationDate` TEXT DEFAULT (datetime('now','localtime'))
);

/* ---------------- 6. ModelDeployments ---------------- */
CREATE TABLE IF NOT EXISTS `ModelDeployments` (
    `DeploymentID`    INTEGER PRIMARY KEY AUTOINCREMENT,
    `ModelID`         INTEGER NOT NULL REFERENCES `Models`(`ModelID`),
    `TrainingID`      INTEGER NOT NULL REFERENCES `Trainings`(`TrainingID`),
    `DeviceID`        INTEGER NOT NULL REFERENCES `EdgeDevices`(`DeviceID`),
    `Version`         TEXT,
    `VersionAlias`    TEXT,
    `Environment`     TEXT,
    `DeployUrl`       TEXT,
    `DeployedPath`    TEXT,
    `ServicePort`     INTEGER CHECK (`ServicePort` IS NULL OR (`ServicePort` BETWEEN 1 AND 65535)),
    `RuntimeParams`   TEXT,
    `IsActive`        INTEGER DEFAULT 1,
    `IsCurrent`       INTEGER NOT NULL DEFAULT 1,
    `DeployStatus`    TEXT,
    `LastStatusCheck` TEXT,
    `DeployedDate`    TEXT DEFAULT (datetime('now','localtime')),
    `DeployedBy`      TEXT,
    `ErrorMessage`    TEXT,
    `Remark`          TEXT
);

/* ---------------- 7. InferenceTasks ---------------- */
CREATE TABLE IF NOT EXISTS `InferenceTasks` (
    `InferenceTaskID`  INTEGER PRIMARY KEY AUTOINCREMENT,
    `TrainingID`       INTEGER NOT NULL REFERENCES `Trainings`(`TrainingID`),
    `TargetDatasetID`  INTEGER NOT NULL REFERENCES `Datasets`(`DatasetID`),
    `TaskName`         TEXT NOT NULL,
    `TaskType`         TEXT NOT NULL,
    `Status`           TEXT,
    `InferenceParams`  TEXT,
    `ResultSummary`    TEXT,
    `ErrorMessage`     TEXT,
    `DeploymentID`     INTEGER REFERENCES `ModelDeployments`(`DeploymentID`),
    `ModelID`          INTEGER REFERENCES `Models`(`ModelID`),
    `DeviceID`         INTEGER REFERENCES `EdgeDevices`(`DeviceID`),
    `InputPath`        TEXT,
    `OutputPath`       TEXT,
    `Progress`         INTEGER CHECK (`Progress` IS NULL OR (`Progress` BETWEEN 0 AND 100)),
    `CreatedDate`      TEXT DEFAULT (datetime('now','localtime')),
    `StartedDate`      TEXT,
    `CompletedDate`    TEXT,
    `CreatedBy`        TEXT
);

/* ---------------- 8. InferenceResults ---------------- */
CREATE TABLE IF NOT EXISTS `InferenceResults` (
    `ResultID`          INTEGER PRIMARY KEY AUTOINCREMENT,
    `InferenceTaskID`   INTEGER NOT NULL REFERENCES `InferenceTasks`(`InferenceTaskID`),
    `RowIdentifier`     TEXT,
    `ResultTimestamp`   TEXT,
    `PredictedValue`    REAL,
    `AnomalyScore`      REAL,
    `IsAnomaly`         INTEGER,
    `PredictedCategory` TEXT,
    `Confidence`        REAL,
    `FeatureSnapshot`   TEXT,
    `ModelID`           INTEGER REFERENCES `Models`(`ModelID`),
    `SampleIndex`       INTEGER,
    `PredictedClass`    INTEGER,
    `PredictedLabel`    TEXT,
    `Score`             REAL,
    `ActualClass`       INTEGER,
    `ResultDetail`      TEXT,
    `CreatedDate`       TEXT DEFAULT (datetime('now','localtime'))
);

/* ---------------- 索引（与 MySQL 版同名） ---------------- */
CREATE INDEX IF NOT EXISTS `IX_Trainings_ModelID`                 ON `Trainings`(`ModelID`);
CREATE INDEX IF NOT EXISTS `IX_ModelInvocations_ModelID_Date`     ON `ModelInvocations`(`ModelID`, `InvocationDate`);
CREATE INDEX IF NOT EXISTS `IX_ModelDeployments_ModelID_Current`  ON `ModelDeployments`(`ModelID`, `IsCurrent`);
CREATE INDEX IF NOT EXISTS `IX_ModelDeployments_DeviceID`         ON `ModelDeployments`(`DeviceID`);
CREATE INDEX IF NOT EXISTS `IX_InferenceTasks_Status`             ON `InferenceTasks`(`Status`);
CREATE INDEX IF NOT EXISTS `IX_InferenceTasks_TrainingID`         ON `InferenceTasks`(`TrainingID`);
CREATE INDEX IF NOT EXISTS `IX_InferenceResults_TaskID`           ON `InferenceResults`(`InferenceTaskID`);
CREATE INDEX IF NOT EXISTS `IX_InferenceResults_Timestamp`        ON `InferenceResults`(`ResultTimestamp`);

/* ---------------- 初始数据（与 MySQL 版一致） ---------------- */
INSERT OR IGNORE INTO `Datasets` (`DatasetName`, `Source`, `SampleCount`, `ClassCount`, `DataPath`, `Description`)
VALUES ('CWRU-0HP', 'Case Western Reserve University 轴承数据集', NULL, 10,
        'testRestfulProject/1DCNN/0HP', '驱动端(DE)振动信号，10 类轴承状态');

INSERT OR IGNORE INTO `Models` (`ModelName`, `Description`, `ApiEndpoint`, `ModelType`, `Status`)
VALUES
 ('1DCNN',   '一维卷积神经网络，CWRU 轴承振动信号 10 类故障分类。', '/predict', 'Classification',     '可运行'),
 ('cwt_cnn', '与 1DCNN 同任务的 PyTorch 实现，输出混淆矩阵。',      '/predict', 'Classification',     '可运行'),
 ('adtk',    '时序异常检测库（无监督），项目经 main.py 调用 PcaAD。', '/predict', 'AnomalyDetection',   '可运行');
