"""一次性迁移：Anvil 业务库表对齐 ruoyi-cloud-plus 规范(商用对接铺路)。

参考团队商用表结构(mn-qiaoyun-material.lianrao_open_terminal/material_file_regist,
ruoyi 代码生成标准):
  - 业务表 6 个公共字段: tenant_id varchar(20) '000000'、create_dept bigint、
    create_by bigint、create_time datetime、update_by bigint、update_time datetime
  - 追加日志表 4 个: tenant_id、create_dept、create_by、create_time(无 update 侧)
  - 软删: del_flag char(1), 0=存在 2=删除
  - 列/表带中文 COMMENT
执行前务必备份: mysqldump -h<host> -P<port> -u<user> -p anvil > anvil_backup.sql
幂等,可重复跑。用法(Anvil/ 目录): python3 scripts/migrate_ruoyi_conventions.py
"""
import os
import sys

from sqlalchemy import create_engine, text, inspect


def _db_url():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from anvil.db import DB_URL
    return DB_URL


def main():
    engine = create_engine(_db_url())
    insp = inspect(engine)

    def cols(table):
        return {c["name"]: c for c in insp.get_columns(table)}

    def add_col(conn, table, col, ddl, backfill=None):
        if col not in cols(table):
            conn.execute(text("ALTER TABLE `%s` ADD COLUMN %s" % (table, ddl)))
            print("  + %s.%s" % (table, col))
        if backfill:
            conn.execute(text("UPDATE `%s` SET %s" % (table, backfill)))

    with engine.begin() as conn:
        # ---- users: ruoyi 映射字段 ----
        print("[1] users")
        add_col(conn, "users", "sys_user_id",
                "`sys_user_id` BIGINT NULL COMMENT 'ruoyi sys_user.user_id'")
        add_col(conn, "users", "tenant_id",
                "`tenant_id` VARCHAR(20) NOT NULL DEFAULT '000000' COMMENT '租户编号'",
                backfill="`tenant_id`='000000' WHERE `tenant_id` IS NULL")

        # ---- projects: del_flag 1→2;parent_id→bigint;去冗余 created_at ----
        print("[2] projects")
        p = "projects"
        r = conn.execute(text("UPDATE projects SET del_flag='2' WHERE del_flag='1'"))
        if r.rowcount:
            print("  del_flag 1→2:", r.rowcount, "行")
        conn.execute(text(
            "ALTER TABLE projects MODIFY COLUMN parent_id BIGINT NULL COMMENT '父项目ID'"))
        conn.execute(text(
            "ALTER TABLE projects MODIFY COLUMN del_flag CHAR(1) DEFAULT '0' COMMENT '删除标志（0存在 2删除）'"))
        for c, ddl in [
            ("tenant_id", "`tenant_id` VARCHAR(20) DEFAULT '000000' COMMENT '租户编号'"),
            ("create_dept", "`create_dept` BIGINT NULL COMMENT '创建部门'"),
            ("create_by", "`create_by` BIGINT NULL COMMENT '创建者(ruoyi user_id)'"),
            ("update_by", "`update_by` BIGINT NULL COMMENT '更新者(ruoyi user_id)'"),
        ]:
            add_col(conn, p, c, ddl)
        if "created_at" in cols(p):
            conn.execute(text("ALTER TABLE projects DROP COLUMN `created_at`"))
            print("  - projects.created_at(冗余,统一 create_time)")
        conn.execute(text("ALTER TABLE projects COMMENT='设计项目表'"))

        # ---- shares: 补齐 6 公共字段 + del_flag;created_at→create_time;id→bigint ----
        print("[3] shares")
        s = "shares"
        conn.execute(text(
            "ALTER TABLE shares MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键'"))
        add_col(conn, s, "tenant_id",
                "`tenant_id` VARCHAR(20) NOT NULL DEFAULT '000000' COMMENT '租户编号'")
        add_col(conn, s, "create_dept", "`create_dept` BIGINT NULL COMMENT '创建部门'")
        add_col(conn, s, "create_by", "`create_by` BIGINT NULL COMMENT '创建者'")
        add_col(conn, s, "update_by", "`update_by` BIGINT NULL COMMENT '更新者'")
        add_col(conn, s, "del_flag",
                "`del_flag` CHAR(1) DEFAULT '0' COMMENT '删除标志（0存在 2删除）'")
        if "create_time" not in cols(s) and "created_at" in cols(s):
            conn.execute(text(
                "ALTER TABLE shares ADD COLUMN `create_time` DATETIME NULL COMMENT '创建时间'"))
            conn.execute(text("UPDATE shares SET create_time=created_at"))
        if "update_time" not in cols(s):
            conn.execute(text(
                "ALTER TABLE shares ADD COLUMN `update_time` DATETIME NULL COMMENT '更新时间'"))
        if "created_at" in cols(s):
            conn.execute(text("ALTER TABLE shares DROP COLUMN `created_at`"))
            print("  - shares.created_at → create_time")
        conn.execute(text(
            "ALTER TABLE shares MODIFY COLUMN permission VARCHAR(16) DEFAULT 'read' COMMENT '权限(read/comment/edit)'"))
        conn.execute(text("ALTER TABLE shares COMMENT='项目共享授权表'"))

        # ---- dltq_ledger: 补 6 公共字段;updated_at→update_time ----
        print("[4] dltq_ledger")
        d = "dltq_ledger"
        add_col(conn, d, "tenant_id",
                "`tenant_id` VARCHAR(20) NOT NULL DEFAULT '000000' COMMENT '租户编号'")
        add_col(conn, d, "create_dept", "`create_dept` BIGINT NULL COMMENT '创建部门'")
        add_col(conn, d, "create_by", "`create_by` BIGINT NULL COMMENT '创建者'")
        add_col(conn, d, "update_by", "`update_by` BIGINT NULL COMMENT '更新者'")
        if "update_time" not in cols(d):
            conn.execute(text(
                "ALTER TABLE dltq_ledger ADD COLUMN `update_time` DATETIME NULL COMMENT '更新时间'"))
        if "updated_at" in cols(d):
            conn.execute(text("UPDATE dltq_ledger SET update_time=updated_at WHERE update_time IS NULL"))
            conn.execute(text("ALTER TABLE dltq_ledger DROP COLUMN `updated_at`"))
            print("  - dltq_ledger.updated_at → update_time")
        if "create_time" not in cols(d):
            conn.execute(text(
                "ALTER TABLE dltq_ledger ADD COLUMN `create_time` DATETIME NULL COMMENT '创建时间'"))
        conn.execute(text("ALTER TABLE dltq_ledger COMMENT='dltQ需求账本表(每项目一行)'"))

        # ---- 追加日志表: 4 公共字段(tenant+create 侧) ----
        for t, cn in [("history_rows", "对话流水表"), ("design_log_rows", "设计日志表")]:
            print("[5]", t)
            add_col(conn, t, "tenant_id",
                    "`tenant_id` VARCHAR(20) NOT NULL DEFAULT '000000' COMMENT '租户编号'")
            add_col(conn, t, "create_dept", "`create_dept` BIGINT NULL COMMENT '创建部门'")
            add_col(conn, t, "create_by", "`create_by` BIGINT NULL COMMENT '创建者(ruoyi user_id)'")
            add_col(conn, t, "create_time",
                    "`create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'")
            conn.execute(text("ALTER TABLE `%s` COMMENT='%s'" % (t, cn)))

    print("迁移完成。")


if __name__ == "__main__":
    main()
