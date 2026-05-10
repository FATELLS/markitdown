"""
cleaner.py — Markdown后处理清理管线

处理顺序:
0. PPTX特有噪声清理（Slide标记、纯数字页码）
1. 删除 <!-- image --> 及其前后空行
2. 删除 MarkitDown 元数据行
3. 删除 SMTP 邮件头
4. 删除截断标记 [截断，原文共N字符]
5. 控制字符清理 (保留 \t\n\r)
6. NaN值替换
7. 重复标签去重
8. 超长行处理 (按|拆分表格或截断)
9. 连续空行压缩
10. 模板噪音过滤（跨页重复短行去重）
11. 行尾空白清理
12. 纯页码行删除
13. 空目录项清理
14. 长分隔线清理
15. 版权声明块删除
16. 大文档截断(aggressive模式)
"""

import re
import logging

log = logging.getLogger("markitdown_enhanced.cleaner")


def _remove_pptx_noise(md_text: str) -> str:
    """PPTX特有噪声清理：删除Slide标记行和纯数字页码行"""
    # 删除 <!-- Slide number: X --> 行
    md_text = re.sub(r'^<!--\s*Slide\s+number\s*:\s*\d+\s*-->\s*$', '', md_text, flags=re.MULTILINE)
    # 删除纯数字行（页码如 "1", "2"）
    md_text = re.sub(r'^\d{1,4}\s*$', '', md_text, flags=re.MULTILINE)
    # 删除 "第X页" 格式
    md_text = re.sub(r'^第\d+页\s*$', '', md_text, flags=re.MULTILINE)
    return md_text


def deduplicate_template_lines(text: str, min_length: int = 2, max_length: int = 40, min_occurrences: int = 3) -> str:
    """
    跨页重复短行去重（模板噪音过滤）。

    统计所有非空行出现次数，长度在 min_length~max_length 之间的短行，
    出现≥min_occurrences次视为模板噪音并删除。

    排除：以 # 开头的标题行、以 | 开头的表格行、以 ``` 开头的代码块行。

    Args:
        text: Markdown文本
        min_length: 最短行长度
        max_length: 最长行长度
        min_occurrences: 最少出现次数阈值

    Returns:
        清理后的文本
    """
    lines = text.split('\n')

    # 统计行频次
    from collections import Counter
    line_counts = Counter()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        length = len(stripped)
        if min_length <= length <= max_length:
            # 排除标题行、表格行、代码块行
            if stripped.startswith('#') or stripped.startswith('|') or stripped.startswith('```'):
                continue
            line_counts[stripped] += 1

    # 找出模板噪音行
    noise_lines = {line for line, count in line_counts.items() if count >= min_occurrences}

    if noise_lines:
        log.debug("模板噪音过滤: 发现%d种重复短行（出现≥%d次）", len(noise_lines), min_occurrences)

    # 过滤
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped in noise_lines:
            continue
        cleaned.append(line)

    return '\n'.join(cleaned)


def _remove_html_image_comments(md_text: str) -> str:
    """删除 <!-- image --> 标记及其前后空行"""
    md_text = re.sub(r'<!--\s*image\s*-->', '', md_text, flags=re.IGNORECASE)
    return md_text


def _remove_markitdown_metadata(md_text: str) -> str:
    """删除 MarkitDown 元数据行"""
    md_text = re.sub(r'^- MarkitDown提取.*$', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^- 提取时间:.*$', '', md_text, flags=re.MULTILINE)
    return md_text


def _remove_smtp_headers(md_text: str) -> str:
    """删除 SMTP 邮件头（从 Received:/Date:/From:/To:/Subject:/Message-ID: 等开始到正文）"""
    lines = md_text.split('\n')
    cleaned = []
    in_headers = False
    header_start_line = -1

    for i, line in enumerate(lines):
        stripped = line.strip()

        if re.match(r'^(Received|Date|From|To|Subject|Message-ID|Cc|Bcc|Reply-To|In-Reply-To|References|X-[\w-]+|MIME-Version|Content-Type|Content-Transfer-Encoding)\s*:', stripped):
            if not in_headers:
                in_headers = True
                header_start_line = i
            continue

        if in_headers:
            if stripped and (line[0] in (' ', '\t')):
                continue
            if not stripped:
                continue
            in_headers = False

        cleaned.append(line)

    md_text = '\n'.join(cleaned)
    return md_text


def _remove_truncation_markers(md_text: str) -> str:
    """删除各种格式的截断标记"""
    md_text = re.sub(r'\s*\.\.\.\s*\[截断，原文共\d+字符\]', '', md_text)
    md_text = re.sub(r'\s*\[截断，原文共\d+字符\]', '', md_text)
    md_text = re.sub(r'^\|[.: -]{40,}\|?\s*$', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^[.:\\-]{40,}\s*$', '', md_text, flags=re.MULTILINE)
    lines = md_text.split('\n')
    cleaned = []
    in_code = False
    for line in lines:
        if line.strip().startswith('```'):
            in_code = not in_code
            cleaned.append(line)
            continue
        if not in_code:
            line = re.sub(r'\s+\.{3,}\s*$', '', line)
        cleaned.append(line)
    md_text = '\n'.join(cleaned)
    return md_text


def _remove_control_chars(md_text: str) -> str:
    """控制字符清理（保留 \t\n\r）"""
    md_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', md_text)
    return md_text


def _replace_nan(md_text: str) -> str:
    """NaN值替换（独立出现，非SQL函数上下文中的）"""
    md_text = re.sub(r'(?<!\w)NaN(?!\w)', '—', md_text)
    return md_text


def _deduplicate_labels(md_text: str) -> str:
    """重复标签去重（如PPT提取的 ### Notes:）— 保留第一个，删除后续"""
    for pattern in [r'### Notes:']:
        parts = md_text.split(pattern)
        if len(parts) > 1:
            md_text = parts[0] + pattern + "".join(parts[1:])
    return md_text


def _handle_long_lines(md_text: str, threshold: int = 2000, hard_limit: int = 500) -> str:
    """超长行处理：包含 | 时拆分为表格行，否则截断并标注"""
    lines = md_text.split('\n')
    processed = []

    for line in lines:
        if len(line) <= threshold:
            processed.append(line)
            continue

        if '|' in line:
            cells = line.split('|')
            table_lines = []
            for cell in cells:
                cell = cell.strip()
                if cell:
                    table_lines.append(f"| {cell} |")
            if table_lines:
                processed.extend(table_lines)
                log.debug("超长行(%d字符)已拆分为%d行表格", len(line), len(table_lines))
                continue

        truncated = line[:hard_limit]
        processed.append(truncated)
        log.debug("超长行(%d字符)已截断到%d字符", len(line), hard_limit)

    return '\n'.join(processed)


def _compress_blank_lines(md_text: str) -> str:
    """连续空行压缩（最多2个空行）"""
    md_text = re.sub(r'\n{4,}', '\n\n\n', md_text)
    return md_text


def _strip_trailing_whitespace(md_text: str) -> str:
    """行尾空白清理"""
    md_text = re.sub(r'[ \t]+$', '', md_text, flags=re.MULTILINE)
    return md_text


def _remove_page_numbers(md_text: str) -> str:
    """纯页码行删除"""
    md_text = re.sub(r'^\d{1,4}$', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^第\d+页$', '', md_text, flags=re.MULTILINE)
    return md_text


def _remove_empty_toc_items(md_text: str) -> str:
    """空目录项（只有点号或省略号）"""
    md_text = re.sub(r'^[\.\s·]{3,}$', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^\.{3,}\s*\d*$', '', md_text, flags=re.MULTILINE)
    return md_text


def _remove_long_separators(md_text: str) -> str:
    """长分隔线"""
    md_text = re.sub(r'^[-=_*]{30,}$', '', md_text, flags=re.MULTILINE)
    return md_text


def _remove_copyright_blocks(md_text: str) -> str:
    """版权声明块删除"""
    lines = md_text.split("\n")
    cleaned = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if re.search(r'(版权所有|Copyright.*reserved|All Rights Reserved|未经.*不得.*转载)', s, re.I):
            while i < len(lines):
                s2 = lines[i].strip()
                if s2 and not re.search(r'(版权|copyright|©|保留|reserved|许可|license|proprietary|机密|confidential)', s2, re.I):
                    if not re.match(r'^[-=]{10,}$', s2):
                        break
                i += 1
            continue
        cleaned.append(lines[i])
        i += 1
    return "\n".join(cleaned)


def _truncate_large_doc(md_text: str, max_lines: int = 3000) -> str:
    """大文档截断"""
    body_lines = md_text.split("\n")
    if len(body_lines) > 50000:
        truncated = body_lines[:max_lines]
        truncation_note = f"\n\n> **[文档截断]** 原文共 {len(body_lines):,} 行，此处保留前 {max_lines:,} 行。完整内容请查看源文件。\n"
        md_text = "\n".join(truncated) + truncation_note
    return md_text


def clean_markdown(md_text: str, aggressive: bool = False) -> str:
    """
    清理Markdown文本中的噪音

    处理管线按顺序执行所有清理步骤。

    Args:
        md_text: 原始Markdown文本
        aggressive: 额外处理大文档（>50000行）的截断

    Returns:
        清理后的Markdown文本
    """
    original_len = len(md_text)

    # 0. PPTX特有噪声清理
    md_text = _remove_pptx_noise(md_text)

    # 1. 删除 <!-- image --> 标记
    md_text = _remove_html_image_comments(md_text)

    # 2. 删除 MarkitDown 元数据行
    md_text = _remove_markitdown_metadata(md_text)

    # 3. 删除 SMTP 邮件头
    md_text = _remove_smtp_headers(md_text)

    # 4. 删除截断标记
    md_text = _remove_truncation_markers(md_text)

    # 5. 控制字符清理
    md_text = _remove_control_chars(md_text)

    # 6. NaN值替换
    md_text = _replace_nan(md_text)

    # 7. 重复标签去重
    md_text = _deduplicate_labels(md_text)

    # 8. 超长行处理
    md_text = _handle_long_lines(md_text)

    # 9. 连续空行压缩
    md_text = _compress_blank_lines(md_text)

    # 10. 模板噪音过滤（跨页重复短行去重）
    md_text = deduplicate_template_lines(md_text)

    # 11. 行尾空白清理
    md_text = _strip_trailing_whitespace(md_text)

    # 12. 纯页码行删除
    md_text = _remove_page_numbers(md_text)

    # 13. 空目录项清理
    md_text = _remove_empty_toc_items(md_text)

    # 14. 长分隔线清理
    md_text = _remove_long_separators(md_text)

    # 15. 版权声明块删除
    md_text = _remove_copyright_blocks(md_text)

    # 16. 清理后可能产生多余空行，再压缩一次
    md_text = _compress_blank_lines(md_text)

    # 17. 大文档截断
    if aggressive:
        md_text = _truncate_large_doc(md_text)

    cleaned_len = len(md_text)
    if original_len != cleaned_len:
        log.debug("清理: %d → %d 字符 (减少%d)", original_len, cleaned_len, original_len - cleaned_len)

    return md_text.strip()
