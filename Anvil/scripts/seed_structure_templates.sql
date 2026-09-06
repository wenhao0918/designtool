-- ============================================================
-- 已知结构知识库 — 种子数据（2 个模板）
-- 执行: mysql -u root -p anvil < seed_structure_templates.sql
-- 幂等: 先 DELETE 再 INSERT，重复执行无害
-- ============================================================

-- 清理旧数据（按外键逆序）
DELETE FROM structure_assembly_rule WHERE template_id IN (1, 2);
DELETE FROM structure_constraint WHERE template_id IN (1, 2);
DELETE FROM structure_param_def WHERE template_id IN (1, 2);
DELETE FROM structure_component WHERE template_id IN (1, 2);
DELETE FROM structure_template WHERE id IN (1, 2);

-- ============================================================
-- 模板 1: 立式圆筒储罐 (VERTICAL_CYLINDER_TANK)
-- ============================================================
INSERT INTO structure_template (id, code, name, aliases, category, subcategory, description, standard_ref, applicable_scope, status) VALUES
(1, 'VERTICAL_CYLINDER_TANK', '立式圆筒储罐',
 '["储油罐","立式罐","储罐","圆筒罐"]',
 '压力容器', '储罐',
 '立式圆筒形钢制焊接储罐，由筒体、封头、接管、人孔、支座等组成，适用于常压至低压液体存储',
 'GB 150-2011',
 '设计压力 0.1~35MPa，容积 1~5000m³，介质: 液体/气体（非剧毒/非易爆限定）',
 0);

-- 组件清单
INSERT INTO structure_component (template_id, parent_id, name, component_type, ref_part_category, quantity_expr, required, sort_order, principle_note) VALUES
(1, NULL, '筒体',        'geometry',       NULL,             '1', 1, 1,  '承压主体，圆筒形以均匀承受内压'),
(1, NULL, '上封头',      'sub_structure',  NULL,             '1', 1, 2,  '顶部封闭件，通常椭圆或碟形封头'),
(1, NULL, '下封头',      'sub_structure',  NULL,             '1', 1, 3,  '底部封闭件，与上封头对称或采用锥形'),
(1, NULL, '接管',        'standard_part',  'flanged_pipe',   '@nozzle_count', 1, 4, '工艺管道接口，需配法兰和补强圈'),
(1, NULL, '人孔',        'sub_structure',  NULL,             '1', 1, 5,  '检修通道，DN450 或 DN500'),
(1, NULL, '支座',        'sub_structure',  NULL,             '1', 1, 6,  '支撑设备重量，大型罐用裙座，小型用支腿'),
(1, NULL, '安全阀',      'standard_part',  'safety_valve',   '1', 1, 7,  '超压保护，泄放面积按GB 150计算'),
(1, NULL, '液位计',      'standard_part',  'level_gauge',    '1', 0, 8,  '液位监测，磁翻板或雷达式'),
(1, NULL, '温度计',      'standard_part',  'thermometer',    '1', 0, 9,  '温度监测，可选'),
(1, NULL, '梯子平台',    'custom_part',    NULL,             '1', 0, 10, '检修通道，非承压件');

-- 参数定义
INSERT INTO structure_param_def (template_id, param_key, param_label, param_type, unit, required, default_value, enum_values, validation_rule, formula_expr, formula_refs, sort_order) VALUES
(1, 'volume',         '容积',       'float',  'm³',  1, NULL, NULL,  '0.1~5000', '', NULL, 1),
(1, 'design_pressure','设计压力',   'float',  'MPa', 1, NULL, NULL,  '0.1~35',   '', NULL, 2),
(1, 'contents',       '介质',       'string', '',    1, NULL, '["柴油","汽油","水","润滑油","空气"]', '', '', NULL, 3),
(1, 'material',       '材料',       'enum',   '',    1, 'Q345R', '["Q345R","Q235B","304","316L"]', '', '', NULL, 4),
(1, 'diameter',       '直径',       'float',  'mm',  1, NULL, NULL,  '300~6000', '', NULL, 5),
(1, 'height',         '筒体高度',   'float',  'mm',  1, NULL, NULL,  '500~20000', '', NULL, 6),
(1, 'wall_thickness',  '壁厚',       'formula','mm',  1, NULL, NULL,  '', 'P*D/(2*[sigma]t*phi-0.5*P)+C', '["design_pressure","diameter","material"]', 7),
(1, 'corrosion_allow', '腐蚀裕量',   'float',  'mm',  0, '2.0', NULL, '0~6', '', NULL, 8),
(1, 'weld_coefficient','焊缝系数',   'float',  '',    0, '1.0', NULL, '0.7~1.0', '', NULL, 9),
(1, 'nozzle_count',   '接管数量',   'int',    '',    0, '3',  NULL,  '0~20', '', NULL, 10);

-- 约束规则
INSERT INTO structure_constraint (template_id, constraint_layer, target_component, rule_type, description, standard_clause, formula_expr, rag_chunk_tags, severity, sort_order) VALUES
(1, 'P', '筒体',     'dimensional', '壁厚不得小于计算值+腐蚀裕量', 'GB 150-2011 §4.3.2', 't >= Pc*Dc/(2*[sigma]t*phi-0.5*Pc)+C', '["GB150","壁厚","筒体"]', 'hard', 1),
(1, 'P', '封头',     'dimensional', '封头壁厚不得小于筒体壁厚×0.8', 'GB 150-2011 §5.1', 'th >= 0.8*t', '["GB150","封头","壁厚"]', 'hard', 2),
(1, 'P', '接管-筒体', 'safety',     '接管开孔需补强，补强面积≥开孔截面积', 'GB 150-2011 §8.3', '', '["GB150","开孔补强","接管"]', 'hard', 3),
(1, 'P', '安全阀',   'safety',     '安全阀泄放面积需满足超压排放要求', 'GB 150-2011 附录B', '', '["GB150","安全阀","泄放"]', 'hard', 4),
(1, 'M', '筒体',     'manufacturing', '筒体纵焊缝需100%射线或超声检测', 'GB 150-2011 §10.3', '', '["GB150","检测","焊缝"]', 'hard', 5),
(1, 'M', '支座',     'manufacturing', '裙座与筒体连接焊缝需全焊透', 'GB 150-2011 §10.4', '', '["GB150","裙座","焊缝"]', 'soft', 6),
(1, 'V', '整体',     'material',   '材料选择需与介质相容，腐蚀性介质选不锈钢', '', '', '["材料","腐蚀","选材"]', 'soft', 7);

-- 装配规则
INSERT INTO structure_assembly_rule (template_id, from_component, to_component, connection_type, relation_expr, principle_note, constraint_note, sort_order) VALUES
(1, '上封头', '筒体', 'weld',     '同心对齐，环焊缝',       '上封头与筒体顶部环焊缝连接，需全焊透',           '100%射线检测，见约束 §10.3', 1),
(1, '下封头', '筒体', 'weld',     '同心对齐，环焊缝',       '下封头与筒体底部环焊缝连接，需全焊透',           '100%射线检测，见约束 §10.3', 2),
(1, '接管',   '筒体', 'insert',   '垂直筒壁插入，接管伸出长度≥150mm', '接管穿过筒壁焊接，需开孔补强圈',          '开孔补强，见约束 §8.3',     3),
(1, '人孔',   '筒体', 'insert',   '距顶封头焊缝≥300mm',     '人孔在筒体上部，便于检修进出',                  '开孔补强，见约束 §8.3',     4),
(1, '支座',   '下封头','bolt',    '均匀分布，地脚螺栓M24×N',  '裙座底环板通过地脚螺栓固定在基础上',             '需校核风载和地震载荷',       5),
(1, '安全阀', '接管', 'flange',   '法兰连接DN≥50',          '安全阀通过法兰安装在顶部接管上',                 '泄放面积计算见约束附录B',    6),
(1, '液位计', '接管', 'flange',   '法兰连接DN20~40',        '液位计通过法兰安装在侧壁接管上',                 '',                          7),
(1, '梯子平台','支座', 'relative_pos','距人孔≤500mm',       '检修梯子通向人孔，平台需覆盖人孔区域',           '',                          8);

-- ============================================================
-- 模板 2: 轴承座 (BEARING_HOUSING)
-- ============================================================
INSERT INTO structure_template (id, code, name, aliases, category, subcategory, description, standard_ref, applicable_scope, status) VALUES
(2, 'BEARING_HOUSING', '轴承座',
 '["轴承支座","轴承箱","bearing housing","支座"]',
 '机械传动', '支座',
 '支承滚动轴承的座体结构，由底板、圆筒体、安装孔、加强筋组成，适用于各类旋转机械支承',
 'GB/T 272',
 '轴承内径 10~500mm，载荷等级: 轻型/中型/重型',
 0);

-- 组件清单
INSERT INTO structure_component (template_id, parent_id, name, component_type, ref_part_category, quantity_expr, required, sort_order, principle_note) VALUES
(2, NULL, '底板',     'geometry',       NULL,          '1', 1, 1, '安装基准面，需铣平面'),
(2, NULL, '圆筒体',   'geometry',       NULL,          '1', 1, 2, '支承轴承外圈，内孔配合H7'),
(2, NULL, '安装孔',   'standard_part',  'bolt_hole',   '4', 1, 3, '底板四角地脚螺栓孔，均布'),
(2, NULL, '加强筋',   'custom_part',    NULL,          '2', 0, 4, '增强圆筒与底板连接刚度，两侧对称'),
(2, NULL, '油孔',     'standard_part',  'oil_port',    '1', 0, 5, '润滑脂注入口，M10×1螺纹'),
(2, NULL, '端盖',     'custom_part',    NULL,          '1', 0, 6, '密封端盖，防尘密封');

-- 参数定义
INSERT INTO structure_param_def (template_id, param_key, param_label, param_type, unit, required, default_value, enum_values, validation_rule, formula_expr, formula_refs, sort_order) VALUES
(2, 'bearing_inner_d', '轴承内径', 'float', 'mm', 1, NULL, NULL, '10~500', '', NULL, 1),
(2, 'bearing_outer_d','轴承外径', 'float', 'mm', 1, NULL, NULL, '20~600', '', NULL, 2),
(2, 'bearing_width',  '轴承宽度', 'float', 'mm', 1, NULL, NULL, '5~200',  '', NULL, 3),
(2, 'load_rating',    '载荷等级', 'enum',  '',   1, '中型', '["轻型","中型","重型"]', '', '', NULL, 4),
(2, 'plate_L',        '底板长',   'float', 'mm', 1, NULL, NULL, '50~500', 'bearing_outer_d + 2*30', '["bearing_outer_d"]', 5),
(2, 'plate_W',        '底板宽',   'float', 'mm', 1, NULL, NULL, '50~300', 'bearing_outer_d + 2*20', '["bearing_outer_d"]', 6),
(2, 'plate_t',        '底板厚',   'float', 'mm', 1, NULL, NULL, '5~50',   '', NULL, 7),
(2, 'cylinder_OD',    '圆筒外径', 'float', 'mm', 1, NULL, NULL, '30~700', 'bearing_outer_d + 2*wall', '["bearing_outer_d"]', 8),
(2, 'cylinder_ID',    '圆筒内径', 'float', 'mm', 1, NULL, NULL, '20~600', '', NULL, 9),
(2, 'cylinder_H',     '圆筒高度', 'float', 'mm', 1, NULL, NULL, '10~250', 'bearing_width + 10', '["bearing_width"]', 10),
(2, 'bolt_d',         '安装孔径', 'float', 'mm', 1, '9',   NULL, '6~36',   '', NULL, 11),
(2, 'material',       '材料',     'enum',  '',   1, 'HT200','["HT200","ZG230-450","Q235"]', '', '', NULL, 12);

-- 约束规则
INSERT INTO structure_constraint (template_id, constraint_layer, target_component, rule_type, description, standard_clause, formula_expr, rag_chunk_tags, severity, sort_order) VALUES
(2, 'P', '圆筒体',  'dimensional', '内孔配合精度H7，圆柱度≤0.01mm', 'GB/T 1800', '', '["配合","H7","圆柱度"]', 'hard', 1),
(2, 'P', '底板',    'dimensional', '底板安装面平面度≤0.05mm/m',     'GB/T 1184', '', '["平面度","安装面"]', 'hard', 2),
(2, 'P', '安装孔',  'dimensional', '安装孔节距偏差≤0.5mm，对称度≤0.3mm', 'GB/T 1804', '', '["安装孔","节距","对称度"]', 'hard', 3),
(2, 'P', '圆筒-底板','safety',    '圆筒与底板连接焊缝/铸造圆角需满足剪切强度', '', 'tau >= F/(pi*d*t)', '["焊缝","剪切强度","圆角"]', 'hard', 4),
(2, 'M', '圆筒体',  'manufacturing', '铸铁件需时效处理消除内应力', 'GB/T 9439', '', '["铸铁","时效"]', 'soft', 5),
(2, 'M', '安装孔',  'manufacturing', '安装孔精装配系列，孔径按GB标准', 'GB/T 5277', '', '["安装孔","精装配","GB"]', 'hard', 6),
(2, 'V', '整体',    'material',   '重载工况选铸钢或锻钢，轻载可选铸铁', '', '', '["材料","载荷","选材"]', 'soft', 7);

-- 装配规则
INSERT INTO structure_assembly_rule (template_id, from_component, to_component, connection_type, relation_expr, principle_note, constraint_note, sort_order) VALUES
(2, '圆筒体',  '底板',    'weld',       '圆筒居中于底板，铸造圆角R5~R10', '圆筒体与底板通过焊接或铸造一体连接',  '焊缝剪切强度，见约束', 1),
(2, '安装孔',  '底板',    'bolt',       '四角均布，距边缘≥1.5×d',          '地脚螺栓固定底板到基础',               '孔径按精装配系列GB/T 5277', 2),
(2, '加强筋',  '圆筒体',  'weld',       '两侧对称布置，高度=圆筒高度×0.6', '增强圆筒与底板连接刚度，减少变形',     '', 3),
(2, '油孔',    '圆筒体',  'insert',     '距顶部法兰面≥10mm',               '润滑脂注入口，垂直于圆筒壁',           '', 4),
(2, '端盖',    '圆筒体',  'relative_pos','同心对齐，螺栓压紧',              '密封端盖防尘密封',                    '', 5);

-- 验证: 查询确认
SELECT '=== 模板 ===' AS '';
SELECT id, code, name, category FROM structure_template;
SELECT '=== 组件(模板1) ===' AS '';
SELECT name, component_type, quantity_expr FROM structure_component WHERE template_id=1 ORDER BY sort_order;
SELECT '=== 组件(模板2) ===' AS '';
SELECT name, component_type, quantity_expr FROM structure_component WHERE template_id=2 ORDER BY sort_order;
SELECT '=== 参数(模板1) ===' AS '';
SELECT param_key, param_label, param_type, unit FROM structure_param_def WHERE template_id=1 ORDER BY sort_order;
SELECT '=== 约束(模板1) ===' AS '';
SELECT constraint_layer, target_component, LEFT(description,40) AS description FROM structure_constraint WHERE template_id=1 ORDER BY sort_order;
SELECT '=== 装配(模板1) ===' AS '';
SELECT from_component, to_component, connection_type FROM structure_assembly_rule WHERE template_id=1 ORDER BY sort_order;
