"""
markitdown_enhanced CLI — 文档转换+增强后处理

用法:
    python -m markitdown_enhanced input.docx -o output.md
    python -m markitdown_enhanced input.pptx --interpret --llm-model gpt-4o
"""

import argparse
import sys
import os
import re
import logging

from .converter import DocumentConverter
from .cleaner import clean_markdown, replace_base64_images
from .keywords import extract_keywords
from .scanner import is_scanned_pdf, validate_file_type
from .generator import generate_doc_obj


def main():
    parser = argparse.ArgumentParser(
        prog="markitdown_enhanced",
        description="文档转换 + 增强后处理（清洗、关键词、可解释提取）",
    )
    parser.add_argument("input", help="输入文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出文件路径（默认stdout）")
    parser.add_argument("--output-dir", default=None, help="输出目录（用于generate-doc-obj模式）")
    parser.add_argument("--aggressive", action="store_true", help="启用大文档截断模式")
    parser.add_argument("--gen-obj", action="store_true", help="生成document_obj文件（带frontmatter）")
    parser.add_argument(
        "--interpret", action="store_true",
        help="启用LLM可解释提取（需要LLM API配置）",
    )
    parser.add_argument("--llm-provider", default=None, help="LLM provider (default: openai)")
    parser.add_argument("--llm-model", default=None, help="LLM模型名称 (default: from env LLM_MODEL)")
    parser.add_argument("--llm-base-url", default=None, help="LLM API地址 (default: from env LLM_BASE_URL)")
    parser.add_argument("--llm-api-key", default=None, help="LLM API密钥 (default: from env LLM_API_KEY)")
    parser.add_argument("--doc-type", default=None, help="覆盖文档类型（pptx/pdf/...）")
    parser.add_argument("--engine", default="auto",
                        help="首选转换引擎 (auto/markitdown/docling/pymupdf, default: auto)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志输出")

    args = parser.parse_args()

    # 日志配置
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    log = logging.getLogger("markitdown_enhanced")

    input_path = args.input
    if not os.path.isfile(input_path):
        print(f"错误: 文件不存在 — {input_path}", file=sys.stderr)
        sys.exit(1)

    # 文件类型验证
    ext = os.path.splitext(input_path)[1].lower()
    doc_type = args.doc_type or ext.lstrip(".")
    if not validate_file_type(input_path):
        log.warning("文件类型不支持: %s", ext)

    log.info("开始处理: %s (类型: %s)", input_path, doc_type)

    # === 步骤1: 多引擎文件转换 ===
    log.info("步骤1: 文档转换 (引擎: %s)...", args.engine)
    try:
        converter = DocumentConverter(preferred_engine=args.engine)
        md_text = converter.convert(input_path)
    except Exception as e:
        log.error("文档转换失败: %s", e)
        sys.exit(1)

    if not md_text.strip():
        log.error("转换结果为空")
        sys.exit(1)

    log.info("转换完成: %d字符", len(md_text))

    # === 步骤1.5: 图片识别（DOCX从文件直接提取，其他格式处理base64占位符） ===
    describe_fn = None
    if args.interpret:
        log.info("步骤1.5: 检测并识别图片...")
        try:
            from .harness import LLMSummarizer

            llm_kwargs = {}
            if args.llm_provider:
                llm_kwargs["provider"] = args.llm_provider
            if args.llm_model:
                llm_kwargs["model"] = args.llm_model
            if args.llm_base_url:
                llm_kwargs["base_url"] = args.llm_base_url
            if args.llm_api_key:
                llm_kwargs["api_key"] = args.llm_api_key

            _llm = LLMSummarizer(**llm_kwargs)
            describe_fn = _llm.describe_image

            # DOCX: 直接从文件提取PNG/JPEG图片，调LLM识别后替换markdown中的占位符
            if doc_type.lower() == "docx":
                from .converter import extract_docx_images
                doc_images = extract_docx_images(input_path)
                if doc_images:
                    log.info("开始识别%d张DOCX图片...", len(doc_images))
                    descriptions = []
                    for img in doc_images:
                        import base64 as b64mod
                        b64_str = b64mod.b64encode(img["data"]).decode("ascii")
                        desc = _llm.describe_image(b64_str, img["mime_type"])
                        descriptions.append(desc)
                        if desc:
                            log.info("  图片识别成功: %s (%d字)", img.get("alt_text", "")[:30], len(desc))
                        else:
                            log.info("  图片识别跳过: %s", img.get("alt_text", "")[:30])

                    # 按顺序替换markdown中的data:image占位符（仅替换同类型）
                    png_idx = 0
                    def docx_image_replacer(match):
                        nonlocal png_idx
                        alt = match.group(1) or ""
                        mime = match.group(2)
                        # EMF占位符直接清理
                        if "emf" in mime or "wmf" in mime:
                            if alt:
                                return f"*[{alt}]*"
                            return ""
                        # PNG/JPEG占位符按顺序用LLM描述替换
                        if png_idx < len(descriptions) and descriptions[png_idx]:
                            desc = descriptions[png_idx]
                            png_idx += 1
                            if alt:
                                return f"**[{alt}]** {desc}"
                            return f"*[图片] {desc}*"
                        else:
                            png_idx += 1
                            if alt:
                                return f"*[图片: {alt}]*"
                            return "*[图片]*"

                    md_text = re.sub(
                        r'!\[([^\]]*)\]\(data:(image/[\w.+-]+);base64,?[^)]*\)',
                        docx_image_replacer,
                        md_text,
                    )
                    log.info("DOCX图片替换完成: %d字符", len(md_text))
                else:
                    md_text = replace_base64_images(md_text)
            else:
                # 非DOCX: 处理markdown中可能存在的base64图片
                md_text = replace_base64_images(md_text, describe_fn=describe_fn)

            log.info("图片识别完成: %d字符", len(md_text))
        except Exception as e:
            log.warning("图片识别失败，跳过: %s", e)
            md_text = replace_base64_images(md_text)  # 兜底清理
    else:
        md_text = replace_base64_images(md_text)

    # === 步骤2: 增强清洗 ===
    log.info("步骤2: 增强清洗...")
    md_text = clean_markdown(md_text, aggressive=args.aggressive)
    log.info("清洗完成: %d字符", len(md_text))

    # === 步骤3: 关键词提取 ===
    log.info("步骤3: 关键词提取...")
    keywords = extract_keywords(md_text)
    if keywords:
        log.info("关键词: %s", keywords)
    else:
        log.info("未提取到关键词")

    # === 步骤4: 可解释提取（可选） ===
    interpret_result = None
    if args.interpret:
        log.info("步骤4: LLM可解释提取...")
        try:
            # 复用步骤2.5创建的LLM实例，避免重复初始化
            if describe_fn and hasattr(describe_fn, '__self__'):
                summarizer = describe_fn.__self__
            else:
                from .harness import LLMSummarizer

                llm_kwargs = {}
                if args.llm_provider:
                    llm_kwargs["provider"] = args.llm_provider
                if args.llm_model:
                    llm_kwargs["model"] = args.llm_model
                if args.llm_base_url:
                    llm_kwargs["base_url"] = args.llm_base_url
                if args.llm_api_key:
                    llm_kwargs["api_key"] = args.llm_api_key

                summarizer = LLMSummarizer(**llm_kwargs)

            interpret_result = summarizer.summarize(md_text, doc_type=doc_type)

            summary_text = interpret_result.get("summary", "")
            section_count = len(interpret_result.get("sections", []))
            log.info("可解释提取完成: 摘要%d字, %d个分段", len(summary_text), section_count)
        except ImportError as e:
            log.error("无法导入LLM模块: %s", e)
            sys.exit(1)
        except Exception as e:
            log.error("LLM可解释提取失败: %s", e)
            sys.exit(1)
    else:
        log.info("步骤4: 跳过可解释提取（未启用--interpret）")

    # === 步骤5: 输出 ===
    if args.gen_obj:
        # 生成 document_obj 文件
        log.info("步骤5: 生成document_obj...")
        output_dir = args.output_dir or os.path.dirname(os.path.abspath(input_path))
        out_path = generate_doc_obj(
            file_path=input_path,
            md_content=md_text,
            output_dir=output_dir,
            keywords=keywords,
            doc_type_override=args.doc_type,
            content_status="scanned_image" if doc_type.lower() == "pdf" and is_scanned_pdf(input_path) else None,
            interpret_result=interpret_result,
        )
        print(f"已生成: {out_path}")
    else:
        # 直接输出Markdown
        output_text = md_text

        # 如果有interpret_result，在正文前插入可解释层
        if interpret_result:
            parts = []
            name = os.path.splitext(os.path.basename(input_path))[0]

            parts.append(f"# {name}")
            parts.append("")

            if keywords:
                parts.extend(["## 关键词", "", keywords, ""])

            summary = interpret_result.get("summary", "")
            if summary:
                parts.extend(["## 摘要", "", summary, ""])

            sections = interpret_result.get("sections", [])
            if sections:
                parts.extend(["## 内容概述", ""])
                for section in sections:
                    title = section.get("title", "")
                    section_summary = section.get("summary", "")
                    parts.append(f"### {title}")
                    if section_summary:
                        parts.extend(["", section_summary, ""])
                    else:
                        parts.append("")

            parts.extend(["---", ""])
            parts.append(md_text)

            output_text = "\n".join(parts)

        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(f"已输出: {args.output}")
        else:
            print(output_text)

    log.info("处理完成")


if __name__ == "__main__":
    main()
