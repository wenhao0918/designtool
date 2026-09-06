# AdminService — DesignTool 管理服务(独立子模块)

> 端口 **8097** · FastAPI · MySQL(anvil 库) · 与 Anvil 解耦

## 职责
- **认证**:登录 / 注册 / 修改密码 / me(JWT 签发,登录日志)
- **用户管理**:增删改查 / 角色分级(admin 管理员 / engineer 工程师 / viewer 访客)/ 启停
- **日志**:登录日志 / 系统日志(下载追溯 downloads.jsonl + 各用户项目设计日志)

## 与 Anvil 的关系
- **共享**:MySQL `anvil` 库(users / login_logs 表)、JWT secret(`ANVIL_JWT_SECRET`)、数据目录(`ANVIL_DATA_DIR`,读下载/设计日志)
- **解耦**:Anvil 只保留 token 校验(`get_current_user` 查 MySQL),不再承担认证与管理;管理 API 全在本服务
- 通信:前端通过 HTTP `/admin-api` → nginx → 127.0.0.1:8097(dev 走 vite proxy)

## 目录
```
AdminService/
├── main.py    # FastAPI 入口
├── auth.py    # /api/auth/login|register|change-password|me
├── admin.py   # /api/admin/users|login-logs|logs(仅 admin)
├── db.py      # MySQL 模型(User/LoginLog)+ 连接
├── start.sh   # 启动(8097)
└── README.md
```

## 启动
```bash
./start.sh          # 或: ANVIL_DATA_DIR=... python3 -m uvicorn main:app --port 8097
```

## 部署
- 服务:`setsid nohup bash start.sh > /tmp/admin8097.log 2>&1 &`
- nginx 反向代理(可选):`location /admin-api { proxy_pass http://127.0.0.1:8097; }`
