-- ============================================================
-- 已知结构知识库 — 5 张表 DDL
-- 架构依据: Primordium/已知结构知识库架构_V0.md
-- 执行: mysql -u root -p anvil < structure_kb_tables.sql
-- ============================================================

-- 1. 结构模板：已知结构的顶层定义（= 高层术语具名块）
CREATE TABLE IF NOT EXISTS structure_template (
  id              INT          NOT NULL AUTO_INCREMENT,
  code            VARCHAR(64)  NOT NULL              COMMENT '模板编码: VERTICAL_CYLINDER_TANK',
  name            VARCHAR(128) NOT NULL               COMMENT '标准名: 立式圆筒储罐',
  aliases         TEXT                  DEFAULT NULL  COMMENT '别名JSON: ["储油罐","立式罐"]',
  category        VARCHAR(64)           DEFAULT NULL  COMMENT '类目: 压力容器/储运设备/传动装置',
  subcategory     VARCHAR(64)           DEFAULT NULL  COMMENT '子类: 储罐/反应釜/减速箱',
  description     TEXT                  DEFAULT NULL  COMMENT '结构简述',
  standard_ref    VARCHAR(128)          DEFAULT NULL  COMMENT '主标准: GB 150-2011',
  applicable_scope TEXT                 DEFAULT NULL  COMMENT '适用范围',
  rag_dataset_id  VARCHAR(64)           DEFAULT NULL  COMMENT 'RAGFlow 数据集 ID',
  expand_template TEXT                  DEFAULT NULL  COMMENT '术语块展开模板JSON(运算模板列表)',
  status          TINYINT       NOT NULL DEFAULT 0    COMMENT '0=启用 1=退役',
  create_by       BIGINT        DEFAULT NULL  COMMENT '创建者ruoyi用户ID',
  create_time     DATETIME      DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_by       BIGINT        DEFAULT NULL  COMMENT '更新者',
  update_time     DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  create_dept     BIGINT        DEFAULT NULL  COMMENT '创建部门ID',
  tenant_id       VARCHAR(20)   DEFAULT '000000' COMMENT '租户ID',
  PRIMARY KEY (id),
  UNIQUE KEY uk_code (code),
  KEY idx_category (category),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已知结构模板表(=高层术语具名块)';

-- 2. 结构组件：结构由哪些部件组成（支持嵌套递归）
CREATE TABLE IF NOT EXISTS structure_component (
  id                INT          NOT NULL AUTO_INCREMENT,
  template_id       INT          NOT NULL              COMMENT '所属模板ID',
  parent_id         INT                   DEFAULT NULL  COMMENT '父组件ID(null=顶层)',
  name              VARCHAR(128) NOT NULL               COMMENT '组件名: 筒体/封头/接管/人孔',
  component_type    VARCHAR(32)  NOT NULL               COMMENT 'sub_structure/standard_part/custom_part/geometry',
  ref_template_id   INT                   DEFAULT NULL  COMMENT 'component_type=sub_structure时引用的模板ID',
  ref_part_category VARCHAR(64)           DEFAULT NULL  COMMENT 'component_type=standard_part时零件类目',
  quantity_expr     VARCHAR(64)            DEFAULT '1'   COMMENT '数量(可参数化): "4" / "@nozzle_count"',
  required          TINYINT      NOT NULL DEFAULT 1    COMMENT '1=必需 0=可选',
  sort_order        INT          NOT NULL DEFAULT 0    COMMENT '展开顺序',
  principle_note    TEXT                  DEFAULT NULL  COMMENT '机械原理注解(为什么需要这个组件)',
  create_by        BIGINT       DEFAULT NULL,
  create_time      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  update_by        BIGINT       DEFAULT NULL,
  update_time      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  create_dept      BIGINT       DEFAULT NULL,
  tenant_id        VARCHAR(20)  DEFAULT '000000',
  PRIMARY KEY (id),
  KEY idx_template (template_id),
  KEY idx_parent (parent_id),
  KEY idx_sort (template_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='结构组件清单(可嵌套递归)';

-- 3. 结构参数定义：该结构类型的设计参数
CREATE TABLE IF NOT EXISTS structure_param_def (
  id              INT          NOT NULL AUTO_INCREMENT,
  template_id     INT          NOT NULL              COMMENT '所属模板ID',
  param_key       VARCHAR(64)  NOT NULL               COMMENT 'volume/design_pressure/contents/material',
  param_label     VARCHAR(64)           DEFAULT NULL  COMMENT '容积/设计压力/介质/材料',
  param_type      VARCHAR(32)           DEFAULT 'string' COMMENT 'float/int/string/enum/formula',
  unit            VARCHAR(32)           DEFAULT NULL  COMMENT 'm³/MPa/-/-',
  required        TINYINT      NOT NULL DEFAULT 1    COMMENT '1=必填 0=可选',
  default_value   VARCHAR(128)          DEFAULT NULL  COMMENT '默认值',
  enum_values     TEXT                  DEFAULT NULL  COMMENT '枚举可选值JSON: ["Q345R","Q235B"]',
  validation_rule TEXT                  DEFAULT NULL  COMMENT '校验规则: "0.1~10"',
  formula_expr    TEXT                  DEFAULT NULL  COMMENT '计算公式: P*D/(2*[σ]t*φ-0.5*P)+C',
  formula_refs    TEXT                  DEFAULT NULL  COMMENT '公式引用的其他param_key JSON',
  sort_order      INT          NOT NULL DEFAULT 0,
  create_by       BIGINT       DEFAULT NULL,
  create_time     DATETIME     DEFAULT CURRENT_TIMESTAMP,
  update_by       BIGINT       DEFAULT NULL,
  update_time     DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  create_dept     BIGINT       DEFAULT NULL,
  tenant_id       VARCHAR(20)  DEFAULT '000000',
  PRIMARY KEY (id),
  KEY idx_template (template_id),
  KEY idx_sort (template_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='结构参数定义(含计算公式)';

-- 4. 结构约束：该结构适用的约束规则（连接C约束场）
CREATE TABLE IF NOT EXISTS structure_constraint (
  id               INT          NOT NULL AUTO_INCREMENT,
  template_id      INT          NOT NULL              COMMENT '所属模板ID',
  constraint_layer VARCHAR(32)           DEFAULT 'P' COMMENT 'P硬律/M可行/V价值/C_c条件',
  target_component VARCHAR(128)          DEFAULT NULL COMMENT '约束对象: 筒体/封头/接管-法兰连接',
  rule_type        VARCHAR(32)           DEFAULT NULL COMMENT 'dimensional/material/safety/manufacturing',
  description      TEXT        NOT NULL               COMMENT '约束描述: 壁厚不得小于计算值+腐蚀裕量',
  standard_clause  VARCHAR(128)          DEFAULT NULL COMMENT '标准条款: GB 150-2011 §4.3.2',
  formula_expr     TEXT                  DEFAULT NULL COMMENT '约束公式: t >= Pc*Dc/(2*[σ]t*φ-0.5*Pc)+C',
  rag_chunk_tags   TEXT                  DEFAULT NULL COMMENT 'RAG检索标签JSON: ["GB150","壁厚"]',
  severity         VARCHAR(16) NOT NULL DEFAULT 'hard' COMMENT 'hard=违反不可行/soft=警告',
  sort_order       INT          NOT NULL DEFAULT 0    COMMENT '排序',
  create_by        BIGINT      DEFAULT NULL,
  create_time      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  update_by        BIGINT       DEFAULT NULL,
  update_time      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  create_dept      BIGINT       DEFAULT NULL,
  tenant_id        VARCHAR(20)  DEFAULT '000000',
  PRIMARY KEY (id),
  KEY idx_template (template_id),
  KEY idx_layer (template_id, constraint_layer)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='结构约束规则(连接C约束场)';

-- 5. 装配规则：组件之间的连接关系（机械原理的核心）
CREATE TABLE IF NOT EXISTS structure_assembly_rule (
  id               INT          NOT NULL AUTO_INCREMENT,
  template_id      INT          NOT NULL              COMMENT '所属模板ID',
  from_component   VARCHAR(128) NOT NULL              COMMENT '主动件: 接管',
  to_component     VARCHAR(128) NOT NULL              COMMENT '被动件: 筒体',
  connection_type  VARCHAR(32)           DEFAULT NULL COMMENT 'weld/flange/bolt/contact/insert/relative_pos',
  relation_expr    TEXT                  DEFAULT NULL COMMENT '位置/尺寸关系表达式',
  principle_note   TEXT                  DEFAULT NULL COMMENT '机械原理: 接管穿过筒体壁需开孔补强',
  constraint_note  TEXT                  DEFAULT NULL COMMENT '关联约束: 见structure_constraint: 开孔补强',
  sort_order       INT          NOT NULL DEFAULT 0,
  create_by        BIGINT       DEFAULT NULL,
  create_time      DATETIME      DEFAULT CURRENT_TIMESTAMP,
  update_by        BIGINT       DEFAULT NULL,
  update_time      DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  create_dept      BIGINT       DEFAULT NULL,
  tenant_id        VARCHAR(20)  DEFAULT '000000',
  PRIMARY KEY (id),
  KEY idx_template (template_id),
  KEY idx_sort (template_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='结构装配规则(组件间连接关系)';
