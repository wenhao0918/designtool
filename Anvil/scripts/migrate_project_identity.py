"""一次性迁移：项目身份统一到 projects.id(bigint)，Q 账本入 DB。

执行前务必备份:  mysqldump -h<host> -P<port> -u<user> -p anvil > anvil_backup.sql

做的事(幂等,可重复跑):
  1. 建 dltq_ledger 表(每项目一行: project_id bigint PK / seq bigint / entries JSON blob)
  2. design_log_rows 加 q_snapshot 列(TEXT)
  3. history_rows / design_log_rows / shares 的 project_id: uuid hash / 中文目录名
     → 经 projects.path 末段反查映射成 projects.id(bigint);无法映射的孤儿行删除
  4. 三张表 project_id 列 ALTER 为 BIGINT
  5. 旧 .dltQ_ledger.json 导入 dltq_ledger

全程原生 SQL/text()——不用新版 ORM(其 project_id 已是 BigInteger,
直接读旧 varchar 里的 hash 会类型转换失败)。

用法(在 Anvil/ 目录,能连 MySQL 的环境):
  python3 scripts/migrate_project_identity.py
"""
import os
import sys
import json

from sqlalchemy import create_engine, text, inspect


def _db_url():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from anvil.db import DB_URL  # 仅取连接串;不调 init_db/create_all
    return DB_URL


def main():
    engine = create_engine(_db_url())
    insp = inspect(engine)

    def has_col(table, col):
        return col in [c["name"] for c in insp.get_columns(table)]

    with engine.begin() as conn:
        # 1. 建 dltq_ledger
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dltq_ledger (
                project_id BIGINT PRIMARY KEY,
                seq BIGINT NOT NULL DEFAULT 0,
                entries TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP
            )"""))
        print("[1] dltq_ledger 表就绪")

        # 2. design_log_rows 加 q_snapshot
        if not has_col("design_log_rows", "q_snapshot"):
            conn.execute(text("ALTER TABLE design_log_rows ADD COLUMN q_snapshot TEXT"))
            print("[2] design_log_rows.q_snapshot 已添加")
        else:
            print("[2] q_snapshot 已存在,跳过")

        # 3. hash/中文目录名 → projects.id 映射
        prows = conn.execute(text(
            "SELECT id, path FROM projects")).fetchall()
        hash2id, idset = {}, set()
        for pid, path in prows:
            idset.add(int(pid))
            if path:
                base = os.path.basename(path.rstrip("/"))
                hash2id[base] = int(pid)
        print("[3] projects 映射条数:", len(hash2id))

        def remap(table):
            rows = conn.execute(text(
                "SELECT id, project_id FROM %s" % table)).fetchall()
            mapped = already = orphan = 0
            for rid, pcol in rows:
                ps = str(pcol)
                if ps.lstrip("-").isdigit():
                    if int(ps) in idset:
                        already += 1
                    else:
                        conn.execute(text("DELETE FROM %s WHERE id=:i" % table),
                                     {"i": rid})
                        orphan += 1
                    continue
                newid = hash2id.get(ps)
                if newid is None:
                    conn.execute(text("DELETE FROM %s WHERE id=:i" % table),
                                 {"i": rid})
                    orphan += 1
                else:
                    conn.execute(text("UPDATE %s SET project_id=:n WHERE id=:i" % table),
                                 {"n": newid, "i": rid})
                    mapped += 1
            print("    %s: 映射 %d,已是id %d,孤儿删除 %d" % (table, mapped, already, orphan))

        remap("history_rows")
        remap("design_log_rows")
        remap("shares")

        # 4. 列类型 → BIGINT(此时值应全为数字)
        conn.execute(text("ALTER TABLE history_rows  MODIFY COLUMN project_id BIGINT NOT NULL"))
        conn.execute(text("ALTER TABLE design_log_rows MODIFY COLUMN project_id BIGINT NOT NULL"))
        conn.execute(text("ALTER TABLE shares        MODIFY COLUMN project_id BIGINT NOT NULL"))
        print("[4] project_id 列已统一为 BIGINT")

        # 5. 导入 .dltQ_ledger.json
        imported = 0
        for pid, path in prows:
            if not path:
                continue
            lp = os.path.join(path, ".dltQ_ledger.json")
            if os.path.exists(lp):
                try:
                    data = json.load(open(lp, encoding="utf-8"))
                except Exception:
                    continue
                entries = data.get("entries", [])
                seq = int(data.get("seq", 0) or 0)
                ej = json.dumps(entries, ensure_ascii=False)
                conn.execute(text("""
                    INSERT INTO dltq_ledger (project_id, seq, entries)
                    VALUES (:p,:s,:e)
                    ON DUPLICATE KEY UPDATE seq=:s, entries=:e
                """), {"p": int(pid), "s": seq, "e": ej})
                imported += 1
        print("[5] .dltQ_ledger.json 导入:", imported)

    print("迁移完成。")


if __name__ == "__main__":
    main()
