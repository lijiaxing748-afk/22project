/* ================================================================
   鉴权改造 · 增量迁移脚本（旧库 → 新库）
   ----------------------------------------------------------------
   什么时候需要跑这个？
     实验室那台机器上的 model_management 库是**鉴权改造之前**建的，
     只有 8 张表（Datasets / Models / EdgeDevices / Trainings /
     ModelInvocations / ModelDeployments / InferenceTasks /
     InferenceResults）。不同步这三张新表，更新代码后**登录会直接报错**
     （dvadmin.login() 一查 Users 表就 Table doesn't exist）。

   与 sql/schema_mysql.sql 的关系：
     那份是**全量**建库脚本（11 张表 + 所有种子数据），新装机用它；
     这份是**增量**脚本，只补鉴权相关的部分，给已经跑起来的旧库用。
     两者都写成 `IF NOT EXISTS` / `INSERT IGNORE`，重复执行安全。

   ⚠️ 顺序要求：本脚本只建表、只插角色，**不建任何账号**。
     账号由服务启动时的 bootstrap_users() 现算口令哈希创建
     （见 model_service/db.py），这样每台机器的密码各自独立，
     不会出现"全公司一个密码哈希"的情况。

   跑法（二选一）：
     · 命令行： mysql -u root -p < sql/auth-migration.sql
     · 或直接重启一次后端（ensure_schema() 会自动执行全量脚本，
       也是幂等的，效果与跑本脚本等价）
   ================================================================ */

USE `model_management`;


/* ---------------- 1. Roles ---------------- */
CREATE TABLE IF NOT EXISTS `Roles` (
    /* 角色：权限的唯一来源。RoleKey 是对外的稳定标识（前端按它判按钮显隐），
       RoleName 只是给人看的，改名字不影响逻辑。
       ⚠️ 权限是**写死在代码里**的（见 model_service/auth.py 的 _ROLE_PERMS），
       这张表只负责"有哪些角色、每个角色叫什么、是否启用"，不做通用的权限点配置。 */
    `RoleID`      INT           NOT NULL AUTO_INCREMENT,
    `RoleKey`     VARCHAR(50)   NOT NULL,     -- admin / engineer / operator
    `RoleName`    VARCHAR(100)  NOT NULL,     -- 超级管理员 / 算法工程师 / 现场操作员
    `Description` VARCHAR(500)  NULL,
    `IsActive`    TINYINT(1)    NULL DEFAULT 1,
    `CreatedDate` DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`RoleID`),
    UNIQUE KEY `UQ_Roles_RoleKey` (`RoleKey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 2. Users ---------------- */
CREATE TABLE IF NOT EXISTS `Users` (
    /* 用户：登录凭据 + 归属角色。
       密码只存哈希（werkzeug pbkdf2:sha256），**任何情况下都不落明文**。 */
    `UserID`       INT           NOT NULL AUTO_INCREMENT,
    `Username`     VARCHAR(50)   NOT NULL,
    `PasswordHash` VARCHAR(255)  NOT NULL,
    `DisplayName`  VARCHAR(100)  NULL,        -- 界面上显示的名字（"张工"），不参与登录
    `RoleKey`      VARCHAR(50)   NOT NULL,    -- 直接存角色键，不建中间表（一人一角色）
    `DeptName`     VARCHAR(100)  NULL,
    `Email`        VARCHAR(100)  NULL,
    `Mobile`       VARCHAR(30)   NULL,
    `IsActive`     TINYINT(1)    NULL DEFAULT 1,   -- 0 = 停用，登录时拒绝
    `Remark`       VARCHAR(500)  NULL,
    `LastLogin`    DATETIME(6)   NULL,
    `LoginCount`   INT           NULL DEFAULT 0,
    /* 令牌版本：改密码时 +1，让此前签发的所有令牌立即失效。
       ⚠️ 令牌是无状态自签的，服务端没有"会话列表"可清理，只能靠这个计数器
       实现"改密码即踢下线"。没它的话，改完密码旧令牌还能用满 12 小时。 */
    `TokenVersion` INT           NULL DEFAULT 0,
    `CreatedDate`  DATETIME(6)   NULL DEFAULT CURRENT_TIMESTAMP(6),
    `UpdatedDate`  DATETIME(6)   NULL,
    PRIMARY KEY (`UserID`),
    UNIQUE KEY `UQ_Users_Username` (`Username`),
    KEY `IX_Users_RoleKey` (`RoleKey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


/* ---------------- 3. OperationLogs ---------------- */
CREATE TABLE IF NOT EXISTS `OperationLogs` (
    /* 操作审计日志：记录"谁在什么时候干了什么"。
       工厂场景最关心**训练、发布、删除**这三类动作——模型换了版本、
       谁把记录删了，都必须能追溯。 */
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


/* ---------------- 初始角色数据 ---------------- */
/* ⚠️ 只插角色，不插用户。用户由 bootstrap_users() 在首次启动时创建，
   口令哈希现算 —— 这样每台机器口令各自独立，也不会把哈希写进版本库。 */
INSERT IGNORE INTO `Roles` (`RoleKey`, `RoleName`, `Description`, `IsActive`, `CreatedDate`)
VALUES
 ('admin',    '超级管理员', '全部权限，含用户管理与操作日志',                     1, CURRENT_TIMESTAMP(6)),
 ('engineer', '算法工程师', '训练、推理、发布、删除模型；不含用户管理/日志',        1, CURRENT_TIMESTAMP(6)),
 ('operator', '现场操作员', '只能浏览模型与产物、发起推理；不能训练/发布/删除',     1, CURRENT_TIMESTAMP(6));


/* ---------------- 自检 ---------------- */
/* 跑完可以执行这条确认三张表都在（应返回 3 行）： */
-- SELECT TABLE_NAME FROM information_schema.TABLES
--  WHERE TABLE_SCHEMA = 'model_management'
--    AND TABLE_NAME IN ('Users', 'Roles', 'OperationLogs');

/* ⚠️ 跑完本脚本**还不能登录** —— Users 表是空的，没有任何账号。
   启动一次后端服务，会看到：
       [鉴权] 已创建 3 个初始账号（admin / engineer / operator）
   默认口令是 Admin@2026 / Engineer@2026 / Operator@2026（公开的演示口令），
   交付现场前请至少改掉 admin 的。 */
