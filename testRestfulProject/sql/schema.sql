/* ================================================================
   模型管理库 · 建表脚本  (Microsoft SQL Server / T-SQL)
   ----------------------------------------------------------------
   用途：登记并追踪「模型 → 训练 → 部署 → 推理」全生命周期
   表清单（按外键依赖顺序）：
     1. Datasets            数据集
     2. Models              模型
     3. EdgeDevices         边缘设备
     4. Trainings           训练记录
     5. ModelInvocations    模型调用日志
     6. ModelDeployments    模型发布记录
     7. InferenceTasks      推理任务
     8. InferenceResults    推理结果明细
   说明：
     - 所有表用 IF OBJECT_ID ... IS NULL 保护，可重复执行
     - 外键、唯一约束、索引集中在末尾追加（带存在性判断）
     - 列的可空性与原始设计保持一致；仅给时间/Bool 列补了默认值
   ================================================================ */

SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO


/* ================================================================
   1. Datasets —— 数据集
   ================================================================ */
IF OBJECT_ID(N'[dbo].[Datasets]', N'U') IS NULL
CREATE TABLE [dbo].[Datasets](
    [DatasetID]    [int]           IDENTITY(1,1) NOT NULL,
    [DatasetName]  [nvarchar](100) NOT NULL,
    [Source]       [nvarchar](200) NULL,
    [SampleCount]  [int]           NULL,
    [ClassCount]   [int]           NULL,
    [DataPath]     [nvarchar](500) NULL,
    [Description]  [nvarchar](500) NULL,
    [CreatedDate]  [datetime2](7)  NULL CONSTRAINT [DF_Datasets_CreatedDate] DEFAULT (SYSDATETIME()),
    CONSTRAINT [PK_Datasets] PRIMARY KEY CLUSTERED ([DatasetID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   2. Models —— 模型
   ================================================================ */
IF OBJECT_ID(N'[dbo].[Models]', N'U') IS NULL
CREATE TABLE [dbo].[Models](
    [ModelID]     [int]           IDENTITY(1,1) NOT NULL,
    [ModelName]   [nvarchar](100) NOT NULL,
    [Description] [nvarchar](500) NULL,
    [ApiEndpoint] [nvarchar](255) NULL,
    [ModelType]   [nvarchar](50)  NULL,
    [CreatedDate] [datetime2](7)  NULL CONSTRAINT [DF_Models_CreatedDate] DEFAULT (SYSDATETIME()),
    [IsActive]    [bit]           NULL CONSTRAINT [DF_Models_IsActive] DEFAULT ((1)),
    [Status]      [nvarchar](20)  NULL,
    CONSTRAINT [PK_Models] PRIMARY KEY CLUSTERED ([ModelID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   3. EdgeDevices —— 边缘设备
   ================================================================ */
IF OBJECT_ID(N'[dbo].[EdgeDevices]', N'U') IS NULL
CREATE TABLE [dbo].[EdgeDevices](
    [DeviceID]      [int]           IDENTITY(1,1) NOT NULL,
    [DeviceName]    [nvarchar](100) NOT NULL,
    [DeviceType]    [nvarchar](50)  NULL,
    [IPAddress]     [nvarchar](45)  NULL,
    [Location]      [nvarchar](255) NULL,
    [HardwareSpecs] [nvarchar](max) NULL,
    [EdgeStatus]    [nvarchar](20)  NULL,
    [LastHeartbeat] [datetime2](7)  NULL,
    [DeviceCode]    [nvarchar](100) NULL,
    [MacAddress]    [nvarchar](50)  NULL,
    [OsVersion]     [nvarchar](100) NULL,
    [Status]        [nvarchar](20)  NULL,
    [IsActive]      [bit]           NULL CONSTRAINT [DF_EdgeDevices_IsActive] DEFAULT ((1)),
    [Remark]        [nvarchar](500) NULL,
    [CreatedDate]   [datetime2](7)  NULL CONSTRAINT [DF_EdgeDevices_CreatedDate] DEFAULT (SYSDATETIME()),
    CONSTRAINT [PK_EdgeDevices] PRIMARY KEY CLUSTERED ([DeviceID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   4. Trainings —— 训练记录（被 3 张表引用，是这套结构的中枢）
   ================================================================ */
IF OBJECT_ID(N'[dbo].[Trainings]', N'U') IS NULL
CREATE TABLE [dbo].[Trainings](
    [TrainingID]    [int]           IDENTITY(1,1) NOT NULL,
    [ModelID]       [int]           NOT NULL,
    [DatasetID]     [int]           NULL,
    [TrainName]     [nvarchar](200) NULL,
    [Epochs]        [int]           NULL,
    [BatchSize]     [int]           NULL,
    [Accuracy]      [float]         NULL,
    [Loss]          [float]         NULL,
    [ModelPath]     [nvarchar](500) NULL,
    [Status]        [nvarchar](20)  NULL,
    [CreatedDate]   [datetime2](7)  NULL CONSTRAINT [DF_Trainings_CreatedDate] DEFAULT (SYSDATETIME()),
    [StartedDate]   [datetime2](7)  NULL,
    [CompletedDate] [datetime2](7)  NULL,
    [CreatedBy]     [nvarchar](100) NULL,
    [Remark]        [nvarchar](500) NULL,
    CONSTRAINT [PK_Trainings] PRIMARY KEY CLUSTERED ([TrainingID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   5. ModelInvocations —— 模型调用日志
   ================================================================ */
IF OBJECT_ID(N'[dbo].[ModelInvocations]', N'U') IS NULL
CREATE TABLE [dbo].[ModelInvocations](
    [InvocationID]   [int]           IDENTITY(1,1) NOT NULL,
    [ModelID]        [int]           NOT NULL,
    [TrainingID]     [int]           NULL,
    [ApiEndpoint]    [nvarchar](255) NULL,
    [RequestParams]  [nvarchar](max) NOT NULL,
    [ResponseResult] [nvarchar](max) NULL,
    [DurationMs]     [int]           NULL,
    [IsSuccess]      [bit]           NULL,
    [StatusCode]     [int]           NULL,
    [ErrorMessage]   [nvarchar](max) NULL,
    [ClientIP]       [nvarchar](50)  NULL,
    [Status]         [nvarchar](20)  NULL,
    [InvocationDate] [datetime2](7)  NULL CONSTRAINT [DF_ModelInvocations_InvocationDate] DEFAULT (SYSDATETIME()),
    CONSTRAINT [PK_ModelInvocations] PRIMARY KEY CLUSTERED ([InvocationID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   6. ModelDeployments —— 模型发布记录
   ================================================================ */
IF OBJECT_ID(N'[dbo].[ModelDeployments]', N'U') IS NULL
CREATE TABLE [dbo].[ModelDeployments](
    [DeploymentID]    [int]           IDENTITY(1,1) NOT NULL,
    [ModelID]         [int]           NOT NULL,
    [TrainingID]      [int]           NOT NULL,
    [DeviceID]        [int]           NOT NULL,
    [Version]         [nvarchar](50)  NULL,
    [VersionAlias]    [nvarchar](20)  NULL,
    [Environment]     [nvarchar](20)  NULL,
    [DeployUrl]       [nvarchar](255) NULL,
    [DeployedPath]    [nvarchar](500) NULL,
    [ServicePort]     [int]           NULL,
    [RuntimeParams]   [nvarchar](max) NULL,
    [IsActive]        [bit]           NULL CONSTRAINT [DF_ModelDeployments_IsActive] DEFAULT ((1)),
    [IsCurrent]       [bit]           NOT NULL CONSTRAINT [DF_ModelDeployments_IsCurrent] DEFAULT ((1)),
    [DeployStatus]    [nvarchar](20)  NULL,
    [LastStatusCheck] [datetime2](7)  NULL,
    [DeployedDate]    [datetime2](7)  NULL CONSTRAINT [DF_ModelDeployments_DeployedDate] DEFAULT (SYSDATETIME()),
    [DeployedBy]      [nvarchar](100) NULL,
    [ErrorMessage]    [nvarchar](max) NULL,
    [Remark]          [nvarchar](500) NULL,
    CONSTRAINT [PK_ModelDeployments] PRIMARY KEY CLUSTERED ([DeploymentID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   7. InferenceTasks —— 推理任务
   ================================================================ */
IF OBJECT_ID(N'[dbo].[InferenceTasks]', N'U') IS NULL
CREATE TABLE [dbo].[InferenceTasks](
    [InferenceTaskID]  [int]           IDENTITY(1,1) NOT NULL,
    [TrainingID]       [int]           NOT NULL,
    [TargetDatasetID]  [int]           NOT NULL,
    [TaskName]         [nvarchar](200) NOT NULL,
    [TaskType]         [nvarchar](20)  NOT NULL,
    [Status]           [nvarchar](20)  NULL,
    [InferenceParams]  [nvarchar](max) NULL,
    [ResultSummary]    [nvarchar](max) NULL,
    [ErrorMessage]     [nvarchar](max) NULL,
    [DeploymentID]     [int]           NULL,
    [ModelID]          [int]           NULL,
    [DeviceID]         [int]           NULL,
    [InputPath]        [nvarchar](500) NULL,
    [OutputPath]       [nvarchar](500) NULL,
    [Progress]         [int]           NULL,
    [CreatedDate]      [datetime2](7)  NULL CONSTRAINT [DF_InferenceTasks_CreatedDate] DEFAULT (SYSDATETIME()),
    [StartedDate]      [datetime2](7)  NULL,
    [CompletedDate]    [datetime2](7)  NULL,
    [CreatedBy]        [nvarchar](100) NULL,
    CONSTRAINT [PK_InferenceTasks] PRIMARY KEY CLUSTERED ([InferenceTaskID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   8. InferenceResults —— 推理结果明细（1 任务 : N 结果）
   ================================================================ */
IF OBJECT_ID(N'[dbo].[InferenceResults]', N'U') IS NULL
CREATE TABLE [dbo].[InferenceResults](
    [ResultID]          [bigint]        IDENTITY(1,1) NOT NULL,
    [InferenceTaskID]   [int]           NOT NULL,
    [RowIdentifier]     [nvarchar](100) NULL,
    [ResultTimestamp]   [datetime2](7)  NULL,
    [PredictedValue]    [float]         NULL,
    [AnomalyScore]      [float]         NULL,
    [IsAnomaly]         [bit]           NULL,
    [PredictedCategory] [nvarchar](50)  NULL,
    [Confidence]        [float]         NULL,
    [FeatureSnapshot]   [nvarchar](500) NULL,
    [ModelID]           [int]           NULL,
    [SampleIndex]       [int]           NULL,
    [PredictedClass]    [int]           NULL,
    [PredictedLabel]    [nvarchar](100) NULL,
    [Score]             [float]         NULL,
    [ActualClass]       [int]           NULL,
    [ResultDetail]      [nvarchar](max) NULL,
    [CreatedDate]       [datetime2](7)  NULL CONSTRAINT [DF_InferenceResults_CreatedDate] DEFAULT (SYSDATETIME()),
    CONSTRAINT [PK_InferenceResults] PRIMARY KEY CLUSTERED ([ResultID] ASC)
) ON [PRIMARY];
GO


/* ================================================================
   外键约束
   ================================================================ */

/* Trainings */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_Trainings_Models')
ALTER TABLE [dbo].[Trainings] ADD CONSTRAINT [FK_Trainings_Models]
    FOREIGN KEY([ModelID]) REFERENCES [dbo].[Models]([ModelID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_Trainings_Datasets')
ALTER TABLE [dbo].[Trainings] ADD CONSTRAINT [FK_Trainings_Datasets]
    FOREIGN KEY([DatasetID]) REFERENCES [dbo].[Datasets]([DatasetID]);
GO

/* ModelInvocations */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ModelInvocations_Models')
ALTER TABLE [dbo].[ModelInvocations] ADD CONSTRAINT [FK_ModelInvocations_Models]
    FOREIGN KEY([ModelID]) REFERENCES [dbo].[Models]([ModelID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ModelInvocations_Trainings')
ALTER TABLE [dbo].[ModelInvocations] ADD CONSTRAINT [FK_ModelInvocations_Trainings]
    FOREIGN KEY([TrainingID]) REFERENCES [dbo].[Trainings]([TrainingID]);
GO

/* ModelDeployments */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ModelDeployments_Models')
ALTER TABLE [dbo].[ModelDeployments] ADD CONSTRAINT [FK_ModelDeployments_Models]
    FOREIGN KEY([ModelID]) REFERENCES [dbo].[Models]([ModelID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ModelDeployments_Trainings')
ALTER TABLE [dbo].[ModelDeployments] ADD CONSTRAINT [FK_ModelDeployments_Trainings]
    FOREIGN KEY([TrainingID]) REFERENCES [dbo].[Trainings]([TrainingID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ModelDeployments_EdgeDevices')
ALTER TABLE [dbo].[ModelDeployments] ADD CONSTRAINT [FK_ModelDeployments_EdgeDevices]
    FOREIGN KEY([DeviceID]) REFERENCES [dbo].[EdgeDevices]([DeviceID]);
GO

/* InferenceTasks */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceTasks_Trainings')
ALTER TABLE [dbo].[InferenceTasks] ADD CONSTRAINT [FK_InferenceTasks_Trainings]
    FOREIGN KEY([TrainingID]) REFERENCES [dbo].[Trainings]([TrainingID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceTasks_Datasets')
ALTER TABLE [dbo].[InferenceTasks] ADD CONSTRAINT [FK_InferenceTasks_Datasets]
    FOREIGN KEY([TargetDatasetID]) REFERENCES [dbo].[Datasets]([DatasetID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceTasks_Models')
ALTER TABLE [dbo].[InferenceTasks] ADD CONSTRAINT [FK_InferenceTasks_Models]
    FOREIGN KEY([ModelID]) REFERENCES [dbo].[Models]([ModelID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceTasks_EdgeDevices')
ALTER TABLE [dbo].[InferenceTasks] ADD CONSTRAINT [FK_InferenceTasks_EdgeDevices]
    FOREIGN KEY([DeviceID]) REFERENCES [dbo].[EdgeDevices]([DeviceID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceTasks_Deployments')
ALTER TABLE [dbo].[InferenceTasks] ADD CONSTRAINT [FK_InferenceTasks_Deployments]
    FOREIGN KEY([DeploymentID]) REFERENCES [dbo].[ModelDeployments]([DeploymentID]);
GO

/* InferenceResults */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceResults_Tasks')
ALTER TABLE [dbo].[InferenceResults] ADD CONSTRAINT [FK_InferenceResults_Tasks]
    FOREIGN KEY([InferenceTaskID]) REFERENCES [dbo].[InferenceTasks]([InferenceTaskID]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_InferenceResults_Models')
ALTER TABLE [dbo].[InferenceResults] ADD CONSTRAINT [FK_InferenceResults_Models]
    FOREIGN KEY([ModelID]) REFERENCES [dbo].[Models]([ModelID]);
GO


/* ================================================================
   检查约束（可选，按需保留）
   ================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_InferenceTasks_Progress')
ALTER TABLE [dbo].[InferenceTasks] WITH NOCHECK ADD CONSTRAINT [CK_InferenceTasks_Progress]
    CHECK ([Progress] IS NULL OR [Progress] BETWEEN 0 AND 100);
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_ModelDeployments_ServicePort')
ALTER TABLE [dbo].[ModelDeployments] WITH NOCHECK ADD CONSTRAINT [CK_ModelDeployments_ServicePort]
    CHECK ([ServicePort] IS NULL OR [ServicePort] BETWEEN 1 AND 65535);
GO


/* ================================================================
   唯一约束（可选）
   ================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_Models_ModelName')
ALTER TABLE [dbo].[Models] ADD CONSTRAINT [UQ_Models_ModelName] UNIQUE ([ModelName]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_Datasets_DatasetName')
ALTER TABLE [dbo].[Datasets] ADD CONSTRAINT [UQ_Datasets_DatasetName] UNIQUE ([DatasetName]);
GO


/* ================================================================
   索引
   ================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Trainings_ModelID' AND object_id = OBJECT_ID(N'[dbo].[Trainings]'))
CREATE NONCLUSTERED INDEX [IX_Trainings_ModelID] ON [dbo].[Trainings]([ModelID] ASC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ModelInvocations_ModelID_Date' AND object_id = OBJECT_ID(N'[dbo].[ModelInvocations]'))
CREATE NONCLUSTERED INDEX [IX_ModelInvocations_ModelID_Date] ON [dbo].[ModelInvocations]([ModelID] ASC, [InvocationDate] DESC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ModelDeployments_ModelID_Current' AND object_id = OBJECT_ID(N'[dbo].[ModelDeployments]'))
CREATE NONCLUSTERED INDEX [IX_ModelDeployments_ModelID_Current] ON [dbo].[ModelDeployments]([ModelID] ASC, [IsCurrent] ASC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ModelDeployments_DeviceID' AND object_id = OBJECT_ID(N'[dbo].[ModelDeployments]'))
CREATE NONCLUSTERED INDEX [IX_ModelDeployments_DeviceID] ON [dbo].[ModelDeployments]([DeviceID] ASC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_InferenceTasks_Status' AND object_id = OBJECT_ID(N'[dbo].[InferenceTasks]'))
CREATE NONCLUSTERED INDEX [IX_InferenceTasks_Status] ON [dbo].[InferenceTasks]([Status] ASC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_InferenceTasks_TrainingID' AND object_id = OBJECT_ID(N'[dbo].[InferenceTasks]'))
CREATE NONCLUSTERED INDEX [IX_InferenceTasks_TrainingID] ON [dbo].[InferenceTasks]([TrainingID] ASC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_InferenceResults_TaskID' AND object_id = OBJECT_ID(N'[dbo].[InferenceResults]'))
CREATE NONCLUSTERED INDEX [IX_InferenceResults_TaskID] ON [dbo].[InferenceResults]([InferenceTaskID] ASC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_InferenceResults_Timestamp' AND object_id = OBJECT_ID(N'[dbo].[InferenceResults]'))
CREATE NONCLUSTERED INDEX [IX_InferenceResults_Timestamp] ON [dbo].[InferenceResults]([ResultTimestamp] ASC);
GO


/* ================================================================
   初始数据（可重复执行，按名称判重）
   ================================================================ */

/* 数据集：CWRU 轴承 */
IF NOT EXISTS (SELECT 1 FROM [dbo].[Datasets] WHERE [DatasetName] = N'CWRU-0HP')
INSERT INTO [dbo].[Datasets] ([DatasetName], [Source], [SampleCount], [ClassCount], [DataPath], [Description])
VALUES (N'CWRU-0HP', N'Case Western Reserve University 轴承数据集', NULL, 10,
        N'testRestfulProject\1DCNN\0HP', N'驱动端(DE)振动信号，10 类轴承状态');
GO

/* 模型：项目内的三个 */
IF NOT EXISTS (SELECT 1 FROM [dbo].[Models] WHERE [ModelName] = N'1DCNN')
INSERT INTO [dbo].[Models] ([ModelName], [Description], [ApiEndpoint], [ModelType], [Status])
VALUES (N'1DCNN', N'一维卷积神经网络，CWRU 轴承振动信号 10 类故障分类。', NULL, N'Classification', N'可运行');
GO
IF NOT EXISTS (SELECT 1 FROM [dbo].[Models] WHERE [ModelName] = N'cwt_cnn')
INSERT INTO [dbo].[Models] ([ModelName], [Description], [ApiEndpoint], [ModelType], [Status])
VALUES (N'cwt_cnn', N'与 1DCNN 同任务的 PyTorch 实现，输出混淆矩阵。', NULL, N'Classification', N'可运行');
GO
IF NOT EXISTS (SELECT 1 FROM [dbo].[Models] WHERE [ModelName] = N'adtk')
INSERT INTO [dbo].[Models] ([ModelName], [Description], [ApiEndpoint], [ModelType], [Status])
VALUES (N'adtk', N'时序异常检测库（无监督），项目经 main.py 调用 PcaAD。', N'/todos', N'AnomalyDetection', N'可运行');
GO


/* ================================================================
   备注：已知的冗余列（未自动删除，需人工决定去留）
   ----------------------------------------------------------------
   Models            : Status 与 IsActive 语义重叠
   ModelDeployments  : IsActive / IsCurrent / DeployStatus 三者需分工
   InferenceResults  : PredictedClass / PredictedLabel / PredictedCategory 近义
                       Score / AnomalyScore / PredictedValue 近义
   EdgeDevices       : EdgeStatus 与 Status 重名语义
   InferenceTasks    : TrainingID 与 DeploymentID 同时存在，需明确权威锚点
   ================================================================ */
