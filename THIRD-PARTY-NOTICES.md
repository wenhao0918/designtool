# Third-Party Notices

本项目再分发（vendored）了以下第三方组件，各自按其原始许可证发布：

## Online 3D Viewer Engine

- 位置：`frontend/public/vendor/o3dv/o3dv.min.js`
- 版权：Copyright (c) kovacsv
- 许可证：MIT — https://github.com/kovacsv/Online3DViewer
- 用途：浏览器内 3D 模型查看引擎

## three.js

- 位置：内嵌于 Online 3D Viewer Engine 构建产物（o3dv.min.js）
- 版权：Copyright 2010-2025 Three.js Authors
- 许可证：MIT — https://threejs.org
- 用途：WebGL 渲染（亦作为 npm 运行时依赖独立使用）

## occt-import-js

- 位置：`frontend/public/vendor/o3dv/occt/`（occt-import-js.js / occt-import-js-worker.js / occt-import-js.wasm）
- 版权：Copyright (c) kovacsv
- 许可证：MIT — https://github.com/kovacsv/occt-import-js
- 用途：在浏览器中读取 STEP/IGES/BREP 文件

## Open CASCADE Technology

- 位置：编译于 occt-import-js.wasm 内
- 版权：Copyright (c) Open CASCADE SAS
- 许可证：LGPL-2.1 with additional exception — https://dev.opencascade.org
- 用途：STEP/IGES 几何内核（WebAssembly 编译版）

---

## 外部服务与本地引擎（API 对接 / 独立进程调用，非再分发）

本仓库不包含下列组件的源码或二进制，仅通过自定义接口对接或以独立进程方式调用，不构成衍生作品的分发：

| 组件 | 对接方式 | 许可证 | 用途 |
|---|---|---|---|
| RAGFlow | 自定义 HTTP API 客户端（`Zhiyin/rag/`、`Anvil/anvil/rag/`） | Apache-2.0（infiniflow/ragflow） | 知识库检索 |
| FreeCAD / Open CASCADE | 独立进程，经 CADService / DraftEngine 调用 | LGPL-2.1+ | 几何建模与工程图纸 |
| RapidOCR（onnxruntime） | 本地引擎（OcrService） | Apache-2.0 | 图片文字识别 |
| openai-whisper | 本地引擎（VoiceService） | MIT | 语音转写 |

MIT 许可证全文见 https://opensource.org/licenses/MIT；LGPL-2.1（含例外条款）全文见 https://dev.opencascade.org/license/ ；Apache-2.0 全文见 https://www.apache.org/licenses/LICENSE-2.0 。

其余运行时依赖（vue、pinia、three、marked 等）经 `package.json` 声明、由包管理器安装，不在本仓库内再分发，各自适用其许可证。
