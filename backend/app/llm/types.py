"""LLM 内部统一消息格式（design §8.1）。

消息历史始终以本格式存储/流转，适配器负责与各 API 格式互转。
换源/换模型时不存在格式漂移。lessons 2.4：thinking 等带签名的块
不进本格式（跨模型回放会 400）——M4 起做序列消毒时依赖此性质。
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


Block = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class UMessage:
    role: Literal["user", "assistant"]
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class TextDeltaEvent:
    """流式文本增量。"""


    text: str


@dataclass
class ToolCallEvent:
    """一个完整工具调用（input 的 partial_json 已拼装完毕）。"""


    id: str
    name: str
    input: dict[str, Any]


@dataclass
class MessageDoneEvent:
    """一次 LLM 调用的最终产物。"""


    message: UMessage
    stop_reason: str | None
    usage: Usage


StreamEvent = TextDeltaEvent | ToolCallEvent | MessageDoneEvent
