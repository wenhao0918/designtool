-- 机械设计零件库表迁移到 anvil 库(2026-09-04)
-- 来源: standard_part/nonstandard_part/part_category 自 mn-qiaoyun-material;
--       enterprise_part/industry_part 自 mn-material(旧库);
-- 方式: 复制结构+数据,源表保留不动(mn-material 模块照常工作);
-- 幂等: 表存在则跳过建表,INSERT IGNORE 按主键去重;
-- 5 表原结构均无 tenant_id,统一补租户列(对齐 ruoyi TenantEntity,默认 '000000')

CREATE TABLE IF NOT EXISTS anvil.standard_part     LIKE `mn-qiaoyun-material`.standard_part;
CREATE TABLE IF NOT EXISTS anvil.nonstandard_part  LIKE `mn-qiaoyun-material`.nonstandard_part;
CREATE TABLE IF NOT EXISTS anvil.part_category     LIKE `mn-qiaoyun-material`.part_category;
CREATE TABLE IF NOT EXISTS anvil.enterprise_part   LIKE `mn-material`.enterprise_part;
CREATE TABLE IF NOT EXISTS anvil.industry_part     LIKE `mn-material`.industry_part;

INSERT IGNORE INTO anvil.standard_part    SELECT * FROM `mn-qiaoyun-material`.standard_part;
INSERT IGNORE INTO anvil.nonstandard_part SELECT * FROM `mn-qiaoyun-material`.nonstandard_part;
INSERT IGNORE INTO anvil.part_category    SELECT * FROM `mn-qiaoyun-material`.part_category;
INSERT IGNORE INTO anvil.enterprise_part  SELECT * FROM `mn-material`.enterprise_part;
INSERT IGNORE INTO anvil.industry_part    SELECT * FROM `mn-material`.industry_part;

-- 补租户列(已存在则报错忽略: 若列已存在需手工跳过本段)
ALTER TABLE anvil.standard_part    ADD COLUMN tenant_id VARCHAR(20) DEFAULT '000000' COMMENT '租户编号';
ALTER TABLE anvil.nonstandard_part ADD COLUMN tenant_id VARCHAR(20) DEFAULT '000000' COMMENT '租户编号';
ALTER TABLE anvil.part_category    ADD COLUMN tenant_id VARCHAR(20) DEFAULT '000000' COMMENT '租户编号';
ALTER TABLE anvil.enterprise_part  ADD COLUMN tenant_id VARCHAR(20) DEFAULT '000000' COMMENT '租户编号';
ALTER TABLE anvil.industry_part    ADD COLUMN tenant_id VARCHAR(20) DEFAULT '000000' COMMENT '租户编号';
