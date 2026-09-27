/* ================================================================
   鉴权改造 · 增量迁移脚本（旧库 → 新库）
   ----------------------------------------------------------------
   什么时候需要跑这个？
     实验室那台机器上的 model_management 库是**鉴权改造之前**建的，
     只有 8 张表（Datasets / Models / EdgeDevices / Trainings /
     ModelInvocations / ModelDeployments / InferenceTasks /
     InferenceResults）。不同步这三张新表，更新代码后**登录会直接报错**
     （dvadmin.login() 一查 Users 表就 Table doesn't exist）。

   ⚠️ 库名在本脚本里是**写死**的（见下面第 26 行 `USE model_management;`）。要用别的库名，
      请让安装脚本执行 —— Windows: docs/离线部署/部署脚本/02-init-database.ps1、
      Linux: docs/Linux部署/init-database.sh 都会按 db.env 的 MODEL_DB_NAME 自动替换；
      手工执行的话请自己改这一行。

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
    `RoleKey`     VARCHAR(50)   NOT NULL,     -- admin / user（只有两种身份；旧的 engineer/operator 见文末迁移段）
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
   口令哈希现算 —— 这样每台机器口令各自独立，也不会把哈希写进版本库。
   ⚠️ 本平台只有**两种身份**：admin（管理员）与 user（普通用户）。 */
INSERT IGNORE INTO `Roles` (`RoleKey`, `RoleName`, `Description`, `IsActive`, `CreatedDate`)
VALUES
 ('admin', '管理员',   '全部权限，含用户管理与操作日志；可把普通用户设为管理员或停用', 1, CURRENT_TIMESTAMP(6)),
 ('user',  '普通用户', '训练、推理、发布、上传模型与数据集；不含删除模型产物、用户管理、操作日志', 1, CURRENT_TIMESTAMP(6));


/* ---------------- 增量：三角色 → 两种身份（admin / user） ----------------
   背景：早期是 admin / engineer / operator 三种角色，后收敛成 admin / user。
   ⚠️ 为什么必须跑：auth.perms_of() 对**未知角色返回空集**（刻意的失败方向），
      所以库里的旧角色键不迁走，那些用户登进去会"什么权限都没有"——
      表现为"能登录、但每个按钮都提示没权限"，很难查。
   ⚠️ 后端启动时 db.migrate_legacy_roles() 会自动跑一次（幂等），
      正常情况下不需要手工执行本段；留着它是给"只想改库、不想重启服务"的场合。
   ⚠️ 删除旧角色行是安全的：Users.RoleKey 对 Roles.RoleKey **没有外键**
      （见 schema_mysql.sql 里"为什么不建中间表"的说明）。 */
UPDATE `Users` SET `RoleKey` = 'user' WHERE `RoleKey` IN ('engineer', 'operator');
DELETE FROM `Roles` WHERE `RoleKey` IN ('engineer', 'operator');
INSERT IGNORE INTO `Roles` (`RoleKey`, `RoleName`, `Description`, `IsActive`, `CreatedDate`)
VALUES ('user', '普通用户', '训练、推理、发布、上传模型与数据集；不含删除模型产物、用户管理、操作日志', 1, CURRENT_TIMESTAMP(6));


/* ---------------- 增量：Users.PwdChangeCount（初次登录强制改密） ----------------
   用途：0 = 还没改过初始口令 → 该用户登录后会被要求改成自己的口令；1 = 已改过/不要求。

   ⚠️ 为什么单列一条：建表脚本是 `CREATE TABLE IF NOT EXISTS`，**表已存在时一个字都不改**，
      所以给老库补列只能靠 ALTER。后端启动时 db._ensure_user_columns() 也会自动补一次
      （带 5 秒锁等待上限），**正常情况下不需要你手工跑这条**。

   ⚠️ 什么时候需要手工跑：如果启动日志/行为显示这列一直没补上，多半是有别的会话
      （另一个长跑的后端、或数据库客户端窗口）开着事务占着元数据锁，ALTER 拿不到锁就放弃了。
      此时先关掉那个会话，再跑本脚本即可。默认值 1 是关键：老账号一律"不要求改密"。
      新账号由程序显式写 0（db.create_user 的 pwd_change_count 参数）。 */
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'Users'
       AND COLUMN_NAME = 'PwdChangeCount');
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE `Users` ADD COLUMN `PwdChangeCount` INT NOT NULL DEFAULT 1',
    'SELECT ''Users.PwdChangeCount 已存在，跳过'' AS note');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


/* ---------------- 自检 ---------------- */
/* 跑完可以执行这条确认三张表都在（应返回 3 行）： */
-- SELECT TABLE_NAME FROM information_schema.TABLES
--  WHERE TABLE_SCHEMA = 'model_management'
--    AND TABLE_NAME IN ('Users', 'Roles', 'OperationLogs');

/* ⚠️ 跑完本脚本**还不能登录** —— Users 表是空的，没有任何账号。
   启动一次后端服务，会看到：
       [鉴权] 已创建 2 个初始账号（admin / user）
   默认口令是 Admin@2026 / User@2026（公开的演示口令），
   交付现场前请至少改掉 admin 的。 */
