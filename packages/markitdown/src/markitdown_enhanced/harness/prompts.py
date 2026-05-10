"""
prompts.py — LLM可解释提取Prompt模板 + 输出解析
"""

import re
import logging

log = logging.getLogger("markitdown_enhanced.harness.prompts")


# PPTX可解释提取prompt
PPTX_INTERPRET_PROMPT = """你是一个文档理解助手。请对以下PPT幻灯片内容进行分析，生成结构化的内容概述。

要求：
1. 先生成3-5句话的全文摘要，概括整个PPT的核心主题和关键信息
2. 按幻灯片逐页生成概述，每页1-2句话概括该页讲什么
3. 忽略重复出现的页脚、logo文字、模板固定内容
4. 使用中文输出
5. 摘要部分要信息密度高，不说废话

输出格式（严格遵守）：
## 摘要
[3-5句话摘要]

## 逐页概述
### 第1页：[页面标题或主题]
[1-2句话概述]

### 第2页：[页面标题或主题]
[1-2句话概述]

---

以下是原始幻灯片内容：
{content}
"""

# PDF可解释提取prompt
PDF_INTERPRET_PROMPT = """你是一个文档理解助手。请对以下文档内容进行分析，生成结构化的内容概述。

要求：
1. 先生成3-5句话的全文摘要，概括文档的核心主题和关键信息
2. 按文档的章节结构分段生成概述，每段1-2句话
3. 忽略页眉页脚、目录、版权声明等模板内容
4. 使用中文输出
5. 摘要部分要信息密度高，不说废话

输出格式（严格遵守）：
## 摘要
[3-5句话摘要]

## 内容概述
### [章节标题]
[1-2句话概述]

---

以下是原始文档内容：
{content}
"""

# 通用文档prompt
GENERAL_INTERPRET_PROMPT = """你是一个文档理解助手。请对以下文档内容进行分析，生成结构化的内容概述。

要求：
1. 先生成3-5句话的全文摘要
2. 按文档结构分段概述，每段1-2句话
3. 使用中文输出
4. 信息密度高，不说废话

输出格式（严格遵守）：
## 摘要
[3-5句话摘要]

## 内容概述
### [章节标题]
[1-2句话概述]

---

以下是原始文档内容：
{content}
"""

# doc_type -> prompt 映射
_PROMPT_MAP = {
    "pptx": PPTX_INTERPRET_PROMPT,
    "pdf": PDF_INTERPRET_PROMPT,
}

SYSTEM_PROMPT = "你是一个专业的文档理解助手，擅长从文档内容中提取关键信息和生成结构化摘要。"


def get_prompt(doc_type: str) -> str:
    """根据文档类型获取对应的prompt模板"""
    return _PROMPT_MAP.get(doc_type.lower(), GENERAL_INTERPRET_PROMPT)


def parse_interpret_output(output: str) -> dict:
    """
    解析LLM的可解释输出，提取摘要和分段概述。

    Args:
        output: LLM返回的文本

    Returns:
        {"summary": str, "sections": [{"title": str, "summary": str}]}
    """
    result = {"summary": "", "sections": []}

    if not output:
        return result

    # 提取摘要部分
    summary_match = re.search(
        r'##\s*摘要\s*\n(.*?)(?=\n##\s)',
        output,
        re.DOTALL
    )
    if summary_match:
        result["summary"] = summary_match.group(1).strip()
    else:
        # 尝试在内容前查找（如果LLM没有严格遵循格式）
        lines = output.strip().split("\n")
        summary_lines = []
        in_summary = False
        for line in lines:
            if line.strip() == "## 摘要":
                in_summary = True
                continue
            if in_summary:
                if line.startswith("## "):
                    break
                summary_lines.append(line.strip())
        if summary_lines:
            result["summary"] = " ".join(s for s in summary_lines if s)

    # 提取分段概述部分
    # 匹配 ### 开头的段落
    section_pattern = re.compile(
        r'###\s+(.+?)\s*\n(.*?)(?=\n###|\n---|\Z)',
        re.DOTALL
    )
    sections_found = False
    for m in section_pattern.finditer(output):
        title = m.group(1).strip()
        content = m.group(2).strip()
        # 跳过摘要标题本身
        if title.startswith("摘要"):
            continue
        if content:
            result["sections"].append({"title": title, "summary": content})
            sections_found = True

    if not sections_found and result["summary"]:
        # 如果没有找到分段，尝试把剩余内容作为单个section
        log.debug("未找到分段概述，尝试简单解析")

    return result
