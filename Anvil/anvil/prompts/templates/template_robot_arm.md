Description: 机器人臂设计（关节臂、DH参数、工作空间）
Triggers: 机器人,关节,臂,机械臂,六轴,四轴,SCARA,6轴,4轴,DH参数,运动学

## 机器人臂设计要点

### 运动学基础
- 使用 DH 参数法描述关节链：每关节 [a, alpha, d, theta_offset]
- 优先使用预设模型 robot_list_models（6dof_articulated / scara）
- 正解用 robot_dh_forward 验证末端位姿

### 结构设计
- 基座固定，关节依次串联
- 每个关节对应一个 link_arm（带两端法兰面）
- 关节范围要考虑机械限位和线缆管理

### 推荐步骤
1. robot_list_models → 选择合适的预设模型
2. robot_dh_forward → 验证零位和极限位姿
3. robot_workspace → 计算工作空间
4. 根据工作空间调整连杆长度
5. 用 shell_box / link_arm 原语建主体
