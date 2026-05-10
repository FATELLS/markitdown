"""
harness — LLM可解释提取模块

提供LLM调用客户端、Prompt模板和输出解析功能，
用于对文档内容生成结构化摘要和逐页/逐段概述。
"""

from .client import LLMSummarizer
from .prompts import parse_interpret_output

__all__ = [
    "LLMSummarizer",
    "parse_interpret_output",
]
