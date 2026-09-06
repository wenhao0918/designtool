"""Anvil routers — 按组件类别组织的路由和画法映射。

routers 职责：
- 端点定义（sketch_router, scene_router）
- 组件画法映射（mechanical, planar, spatial）
- 共享工具（_vec_len 等）

sketch.py 保留 vision 识别 + 跨类别调度逻辑。
"""

from . import sketch_router, scene_router
from . import mechanical, planar, spatial

# 所有类别路由器，按优先级排列
CATEGORY_ROUTERS = [spatial, planar, mechanical]

# 合并所有类别的类型→组件映射
_ALL_REGISTRIES = {}
for cr in CATEGORY_ROUTERS:
    _ALL_REGISTRIES.update(cr.REGISTRY)


def component_to_part(component: dict, idx: int) -> dict | None:
    """调度到对应类别路由器，将组件 JSON 转为 generate_model 的 part 参数。"""
    ctype = component.get("type", "")
    router = None
    for cr in CATEGORY_ROUTERS:
        if ctype in cr.REGISTRY:
            router = cr
            break
    if router is None:
        return None
    return router.component_to_part(component, idx)


def list_routers() -> list:
    """列出所有路由器及其覆盖的组件类型。"""
    result = []
    for cr in CATEGORY_ROUTERS:
        result.append({
            "name": cr.NAME,
            "description": cr.DESCRIPTION,
            "types": list(cr.REGISTRY.keys()),
        })
    return result
