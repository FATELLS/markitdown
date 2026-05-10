"""
markitdown_enhanced — 文档后处理增强模块

提供 MarkItDown 的中文优化、Markdown 清洗、关键词提取、扫描件检测等功能。
作为独立子包，不破坏原项目结构。

用法:
    from markitdown_enhanced import clean_markdown, extract_keywords, is_scanned_pdf, generate_doc_obj
"""

from .cleaner import clean_markdown
from .keywords import extract_keywords
from .scanner import is_scanned_pdf, validate_file_type, should_skip_path
from .generator import generate_doc_obj

__all__ = [
    "clean_markdown",
    "extract_keywords",
    "is_scanned_pdf",
    "validate_file_type",
    "should_skip_path",
    "generate_doc_obj",
]
