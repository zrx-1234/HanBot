"""工具基类与注册表（design §6，lessons 3.1/3.2）。

Tool dataclass：name/description/input_schema 对模型可见；
execute/timeout_s/max_result_chars 是内部字段，不进 schema。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """工具执行错误。错误文本会作为 tool_result(is_error=True) 还给模型，
    不算任务失败（design §5.8）。"""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    execute: Callable[[dict[str, Any]], Awaitable[str]]
    timeout_s: int = 60
    max_result_chars: int = 100_000
    # lessons 3.3：并发分区字段，Phase 1 全串行，P3 启用并发批
    concurrency_safe: bool = False
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def definition(self) -> dict[str, Any]:
        """模型可见的定义（不含内部字段）。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    _TOOLS[tool.name] = tool


def get_tool_definitions() -> list[dict[str, Any]]:
    """按名排序的工具定义列表（顺序稳定，lessons 3.2）。"""
    return [_TOOLS[name].definition() for name in sorted(_TOOLS)]


async def run_tool(name: str, tool_input: dict[str, Any]) -> str:
    """执行工具，返回结果文本（含截断尾注）。

    未知工具/入参错误抛 ToolError；执行期异常包装成 ToolError。
    """
    tool = _TOOLS.get(name)
    if tool is None:
        raise ToolError(f"未知工具：{name}")
    try:
        result = await tool.execute(tool_input)
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001 —— 工具错误的细节要还给模型
        raise ToolError(f"工具 {name} 执行失败：{type(e).__name__}: {e}") from e
    if len(result) > tool.max_result_chars:
        result = (
            result[: tool.max_result_chars]
            + f"\n[结果已截断到 {tool.max_result_chars} 字符]"
        )
    return result
