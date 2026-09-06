# DesignTool 确定性求解演示（demo/）

自包含单容器演示：网页输入设计需求 → **确定性求解全链路** → 3D 预览。

演示的是本仓库核心方法（[专利申请 2026113717477](../NOTICE)）的微型实现，零 LLM、零外部服务：

```
ΔQ 合法性校验(原子事务) → Q 落账(行号/权威/来源) → 约束装配(稀疏方程)
→ 求解 + 适定性诊断 → 形状演算 → 强约束二值判定 → 异源体积验算 → 意图漂移检测
```

两个预置示例：

- **实施例 1 · 空心球 + 底座**：贴合约束装配 → 唯一解（球心 z = 底板厚 + 外球半径）；壁厚二值判定；闭式 vs 辛普森数值积分**异源验算**（默认参数合计 610501.4 mm³，偏差 0.0000%）
- **实施例 2 · 轴承座**：「安装孔」术语块展开（孔径 ∈ 国标精装配系列前置校验）；勾选「筋板横跨全宽」追加增量后，安装孔 X 向保护方向的**零空间投影范数跌破阈值 → 意图丢失事件**（附确定性修复候选与置信度）

同一输入 → 位级一致输出；所有数值均可在 `solver.py`（约 200 行，纯 Python + NumPy）中复核。

## 本地运行

```bash
cd demo
pip install -r requirements.txt
uvicorn app:app --port 7860        # 打开 http://localhost:7860
```

## Docker

```bash
cd demo
docker build -t designtool-demo .
docker run -p 7860:7860 designtool-demo
```

## Hugging Face Spaces

新建 Space → Docker → 把本目录内容推上去即可（监听端口已按 Spaces 约定设为 7860；免费档 2 vCPU / 16 GB 足够）。
