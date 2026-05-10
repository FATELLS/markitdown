"""
generator.py — document_obj Markdown文件生成

生成带 frontmatter 的 Markdown 文件，包含文档元信息和正文。
"""

import os
from pathlib import Path
from datetime import datetime
import logging

log = logging.getLogger("markitdown_enhanced.generator")


def generate_doc_obj(
    file_path: str,
    md_content: str,
    output_dir: str,
    keywords: str = "",
    doc_type_override: str = None,
    extractor_override: str = None,
    content_status: str = None,
    interpret_result: dict = None,
) -> str:
    """
    生成 document_obj Markdown文件

    格式:
    ---
    obj_type: document
    name: 文件名（不含扩展名）
    doc_type: PDF/DOCX/...
    file_path: 原始文件绝对路径
    extracted_at: 提取时间
    extractor: markitdown
    keywords: 关键词1, 关键词2, ...
    content_status: ok / scanned_image (可选)
    ---
    # 标题

    ## 关键词

    词1, 词2

    ---

    [Markdown正文]

    当提供interpret_result时，body格式变为：
    # 标题

    ## 关键词

    ## 摘要

    ## 内容概述

    ---

    [Markdown正文（无损层）]

    Args:
        file_path: 原始文件路径
        md_content: 清理后的Markdown正文
        output_dir: 输出目录
        keywords: 关键词字符串
        doc_type_override: 覆盖文件类型
        extractor_override: 覆盖提取器名称
        content_status: 内容状态标记 (如 "scanned_image")
        interpret_result: LLM可解释提取结果 {"summary": str, "sections": [...]}

    Returns:
        输出文件路径
    """
    abs_path = os.path.abspath(file_path)
    name = Path(file_path).stem
    ext = Path(file_path).suffix.lower().lstrip(".")
    doc_type = doc_type_override or ext.upper()
    extractor = extractor_override or "markitdown"

    # 从文件路径推导分类目录
    rel_to_parent = os.path.relpath(abs_path, os.path.dirname(abs_path))
    category_dir = os.path.dirname(abs_path)

    # 构建frontmatter
    frontmatter_lines = [
        "---",
        f"obj_type: document",
        f"name: {name}",
        f"doc_type: {doc_type}",
        f"file_path: {abs_path}",
        f"extracted_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"extractor: {extractor}",
    ]
    if keywords:
        frontmatter_lines.append(f"keywords: {keywords}")
    if category_dir:
        frontmatter_lines.append(f"category: {category_dir}")
    if content_status:
        frontmatter_lines.append(f"content_status: {content_status}")
    frontmatter_lines.append("---")

    frontmatter = "\n".join(frontmatter_lines)

    # 构建body
    body_lines = [f"# {name}", ""]
    if keywords:
        body_lines.extend(["## 关键词", "", keywords, ""])

    # 可解释层（如果提供）
    if interpret_result:
        # 摘要
        summary = interpret_result.get("summary", "")
        if summary:
            body_lines.extend(["## 摘要", "", summary, ""])

        # 内容概述
        sections = interpret_result.get("sections", [])
        if sections:
            body_lines.extend(["## 内容概述", ""])
            for section in sections:
                title = section.get("title", "")
                section_summary = section.get("summary", "")
                body_lines.append(f"### {title}")
                if section_summary:
                    body_lines.extend(["", section_summary, ""])
                else:
                    body_lines.append("")

    body_lines.extend(["---", "", md_content])
    body = "\n".join(body_lines)

    # 生成文件名: doc_{name}_{ext}_obj.md
    obj_filename = f"doc_{name}_{ext}_obj.md"

    # 输出路径
    out_path = os.path.join(output_dir, obj_filename)

    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(frontmatter + "\n" + body)

    return out_path
