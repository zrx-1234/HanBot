"""工具注册表（design §6，lessons 3.2）。

单一来源列表 + 按名排序序列化（顺序稳定对缓存关键）。
内部字段（execute 等）不暴露给模型可见 schema（lessons 3.1）。
"""

from app.tools import http_request
from app.tools.registry import Tool, ToolError, get_tool_definitions, register, run_tool

register(http_request.TOOL)

__all__ = ["Tool", "ToolError", "get_tool_definitions", "register", "run_tool"]
