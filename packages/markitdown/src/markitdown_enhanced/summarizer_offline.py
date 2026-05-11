"""
summarizer_offline.py — 纯算法离线摘要生成

替代LLM可解释提取（步骤4），完全不依赖任何LLM API。

核心算法：
1. TextRank 句子排序（纯Python实现，不依赖sklearn）
2. 基于标题层级（#、##、###）的自动分段
3. 关键数据提取（数字、百分比、金额）
4. 基于TF的句子权重计算（jieba分词）

输出格式与LLM管线完全一致：
    {
        "summary": "全文摘要",
        "sections": [{"title": "章节标题", "summary": "章节概述"}]
    }
"""

import re
import math
import logging
from collections import Counter, defaultdict

log = logging.getLogger("markitdown_enhanced.summarizer_offline")


# ============================================================================
# TextRank 核心实现（纯Python，无sklearn依赖）
# ============================================================================

def _tokenize_chinese(text: str) -> list:
    """
    中文分词（使用jieba），过滤停用词和短词。

    Args:
        text: 输入文本

    Returns:
        分词后的词语列表
    """
    try:
        import jieba
        import jieba.posseg as pseg

        words = []
        for word, flag in pseg.cut(text):
            # 过滤停用词、标点、单字、纯数字
            if len(word) < 2:
                continue
            if flag in ("x", "w", "uj", "eng"):  # 标点、助词、英文
                continue
            if re.match(r'^[\d.,]+$', word):  # 纯数字
                continue
            words.append(word.lower())
        return words
    except ImportError:
        # jieba不可用时，用简单分词
        log.warning("jieba不可用，使用简单分词")
        return [w.lower() for w in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', text)]


def _sentence_similarity(s1_words: list, s2_words: list) -> float:
    """
    计算两个句子（已分词）的相似度（基于词频向量余弦相似度）。

    Args:
        s1_words: 句子1的词语列表
        s2_words: 句子2的词语列表

    Returns:
        余弦相似度 [0, 1]
    """
    if not s1_words or not s2_words:
        return 0.0

    # 词频统计
    c1 = Counter(s1_words)
    c2 = Counter(s2_words)

    # 共同词汇
    all_words = set(c1.keys()) | set(c2.keys())

    # 余弦相似度
    dot_product = sum(c1[w] * c2[w] for w in all_words)
    norm1 = math.sqrt(sum(v ** 2 for v in c1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in c2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def _build_similarity_matrix(sentences_words: list) -> list:
    """
    构建句子相似度矩阵。

    Args:
        sentences_words: 句子词语列表的列表

    Returns:
        相似度矩阵（二维列表）
    """
    n = len(sentences_words)
    if n == 0:
        return []

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim = _sentence_similarity(sentences_words[i], sentences_words[j])
            matrix[i][j] = sim
            matrix[j][i] = sim

    return matrix


def _textrank_scores(similarity_matrix: list, damping: float = 0.85, max_iter: int = 100, tol: float = 1e-5) -> list:
    """
    TextRank算法计算句子权重。

    Args:
        similarity_matrix: 句子相似度矩阵
        damping: 阻尼系数（类似PageRank）
        max_iter: 最大迭代次数
        tol: 收敛阈值

    Returns:
        各句子的权重列表
    """
    n = len(similarity_matrix)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    # 初始化权重为均匀分布
    scores = [1.0 / n] * n

    for _ in range(max_iter):
        new_scores = [0.0] * n
        for i in range(n):
            # 计算从其他节点到i的权重传递
            rank_sum = 0.0
            for j in range(n):
                if i == j:
                    continue
                # j到i的边权重 = similarity(j, i)
                # j的出度权重 = sum of similarity(j, k) for all k
                out_sum = sum(similarity_matrix[j])
                if out_sum > 0:
                    rank_sum += (similarity_matrix[j][i] / out_sum) * scores[j]

            new_scores[i] = (1 - damping) / n + damping * rank_sum

        # 归一化
        total = sum(new_scores)
        if total > 0:
            new_scores = [s / total * n for s in new_scores]

        # 检查收敛
        diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
        scores = new_scores
        if diff < tol:
            break

    return scores


def _split_sentences(text: str) -> list:
    """
    将文本分割为句子列表。

    支持中文（。！？）、英文（.!?）、以及换行分隔。

    Args:
        text: 输入文本

    Returns:
        句子列表
    """
    # 先按标题层级拆分，保留标题信息
    # 按句子结束符拆分
    sentences = re.split(r'(?<=[。！？.!?\n])\s*', text)
    # 过滤空句和过短句子
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 5]
    return sentences


def _extract_key_sentences(text: str, top_n: int = 5) -> list:
    """
    使用TextRank提取关键句子。

    Args:
        text: 输入文本
        top_n: 提取句子数量

    Returns:
        按重要性排序的句子列表
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []
    if len(sentences) <= top_n:
        return sentences

    # 分词
    sentences_words = [_tokenize_chinese(s) for s in sentences]

    # 构建相似度矩阵
    sim_matrix = _build_similarity_matrix(sentences_words)

    # TextRank计算权重
    scores = _textrank_scores(sim_matrix)

    # 按权重排序，同时考虑句子位置（前面的句子略微加权）
    # 位置权重：前30%的句子给1.2倍加权
    n = len(sentences)
    position_boost = [1.0] * n
    for i in range(n):
        if i < n * 0.3:
            position_boost[i] = 1.2

    # 综合权重
    final_scores = [scores[i] * position_boost[i] for i in range(n)]

    # 排序并取top_n
    ranked = sorted(range(n), key=lambda i: final_scores[i], reverse=True)[:top_n]
    # 按原文顺序输出
    ranked.sort()
    return [sentences[i] for i in ranked]


# ============================================================================
# 基于标题层级的自动分段
# ============================================================================

def _split_sections_by_headings(md_text: str) -> list:
    """
    基于Markdown标题层级（#、##、###）将文档自动分段。

    Args:
        md_text: Markdown文本

    Returns:
        分段列表: [{"title": str, "content": str, "level": int}, ...]
    """
    lines = md_text.split('\n')
    sections = []
    current_title = "概述"
    current_content = []
    current_level = 0

    for line in lines:
        # 匹配Markdown标题
        heading_match = re.match(r'^(#{1,4})\s+(.+)$', line.strip())
        if heading_match:
            # 保存前一个section
            if current_content:
                content_text = '\n'.join(current_content).strip()
                if content_text:
                    sections.append({
                        "title": current_title,
                        "content": content_text,
                        "level": current_level,
                    })
            # 开始新section
            current_level = len(heading_match.group(1))
            current_title = heading_match.group(2).strip()
            current_content = []
        else:
            current_content.append(line)

    # 最后一个section
    if current_content:
        content_text = '\n'.join(current_content).strip()
        if content_text:
            sections.append({
                "title": current_title,
                "content": content_text,
                "level": current_level,
            })

    return sections


# ============================================================================
# 关键数据提取
# ============================================================================

def _extract_key_data(text: str) -> list:
    """
    从文本中提取关键数据点（数字、百分比、金额等）。

    Args:
        text: 输入文本

    Returns:
        关键数据字符串列表
    """
    data_points = []

    # 匹配百分比
    percentages = re.findall(r'[\d.,]+%\s*(?:增长|下降|提升|减少|增幅|降幅)?', text)
    data_points.extend(percentages)

    # 匹配金额（人民币、美元、万、亿）
    amounts = re.findall(
        r'[\d.,]+\s*(?:万元|亿美元|美元|人民币|元|万亿|千亿|百万|万|亿)\s*(?:人民币|美元)?',
        text
    )
    data_points.extend(amounts)

    # 匹配重要数字搭配（如"增长XX%"、"达到XX"等上下文）
    number_contexts = re.findall(
        r'(?:增长|下降|提升|减少|达到|超过|突破|约为|约|将近|接近|同比|环比)\s*[\d.,]+\s*(?:%|万|亿|元|人|次|个|项|件|台|套|家|户)?',
        text
    )
    data_points.extend(number_contexts)

    # 去重并限制数量
    seen = set()
    unique = []
    for dp in data_points:
        dp_clean = dp.strip()
        if dp_clean and dp_clean not in seen and len(dp_clean) <= 30:
            seen.add(dp_clean)
            unique.append(dp_clean)

    return unique[:20]  # 最多20个数据点


# ============================================================================
# 段落摘要生成
# ============================================================================

def _generate_section_summary(section_content: str, max_length: int = 150) -> str:
    """
    为单个段落生成摘要。

    策略：
    1. 如果段落短（<=200字），直接使用
    2. 如果段落长，用TextRank提取关键句子
    3. 追加关键数据点

    Args:
        section_content: 段落内容
        max_length: 摘要最大长度

    Returns:
        段落摘要文本
    """
    # 清理内容
    content = section_content.strip()
    if not content:
        return ""

    # 移除代码块
    content_no_code = re.sub(r'```[\s\S]*?```', '', content)
    # 移除表格（保留标题和说明文字）
    content_no_table = re.sub(r'^\|.+\|$', '', content_no_code, flags=re.MULTILINE)
    content_clean = re.sub(r'\n{3,}', '\n\n', content_no_table).strip()

    if len(content_clean) <= max_length:
        return content_clean

    # 提取关键句子（取2-3句）
    key_sentences = _extract_key_sentences(content_clean, top_n=3)
    summary = ''.join(key_sentences)

    # 截断到最大长度
    if len(summary) > max_length:
        summary = summary[:max_length].rsplit('。', 1)[0] + '。'

    return summary


# ============================================================================
# 主函数：离线摘要生成
# ============================================================================

def generate_offline_summary(md_text: str, doc_type: str = "general") -> dict:
    """
    纯算法生成文档摘要和分段概述（替代LLM可解释提取）。

    输出格式与LLM管线完全一致：
        {
            "summary": "全文摘要（3-5句话）",
            "sections": [
                {"title": "章节标题", "summary": "章节概述"},
                ...
            ]
        }

    处理流程：
    1. 移除代码块和表格，提取纯文本
    2. 基于标题层级自动分段
    3. 对每个段落用TextRank提取关键句子生成摘要
    4. 全文用TextRank提取关键句子生成总体摘要
    5. 提取并保留关键数据点

    Args:
        md_text: 清洗后的Markdown文本
        doc_type: 文档类型 (pptx/pdf/general)

    Returns:
        摘要结果字典
    """
    result = {"summary": "", "sections": []}

    if not md_text or not md_text.strip():
        return result

    # 移除frontmatter（如果有）
    fm_match = re.match(r'^---\n(.*?\n)---\n(.*)', md_text, re.DOTALL)
    body_text = fm_match.group(2) if fm_match else md_text

    # 预处理：移除代码块、base64图片、HTML注释
    clean_body = re.sub(r'```[\s\S]*?```', '', body_text)
    clean_body = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_body)
    clean_body = re.sub(r'<!--[\s\S]*?-->', '', clean_body)
    # 移除表格分隔行
    clean_body = re.sub(r'^\|[\s:|-]+\|$', '', clean_body, flags=re.MULTILINE)
    # 压缩空行
    clean_body = re.sub(r'\n{3,}', '\n\n', clean_body).strip()

    if not clean_body:
        return result

    # 步骤1：自动分段
    sections = _split_sections_by_headings(clean_body)

    if not sections:
        # 没有标题的文档，按段落分段
        paragraphs = [p.strip() for p in clean_body.split('\n\n') if p.strip()]
        if paragraphs:
            sections = [{"title": f"段落{i+1}", "content": p, "level": 1}
                       for i, p in enumerate(paragraphs[:20])]

    if not sections:
        return result

    # 步骤2：为每个section生成摘要
    for section in sections:
        summary = _generate_section_summary(section["content"])
        if summary:
            result["sections"].append({
                "title": section["title"],
                "summary": summary,
            })

    # 步骤3：生成全文摘要
    # 收集所有关键句子
    all_key_sentences = _extract_key_sentences(clean_body, top_n=5)
    full_summary = ''.join(all_key_sentences)

    # 提取关键数据追加到摘要
    key_data = _extract_key_data(clean_body)
    if key_data:
        data_str = '；'.join(key_data[:8])
        if full_summary:
            full_summary += f' 关键数据：{data_str}。'
        else:
            full_summary = f'文档包含以下关键数据：{data_str}。'

    # 限制摘要长度
    if len(full_summary) > 500:
        full_summary = full_summary[:500].rsplit('。', 1)[0] + '。'

    result["summary"] = full_summary.strip()

    # 步骤4：对PPTX特殊处理 — 如果section过多（每页一个），合并相邻section
    if doc_type.lower() == "pptx" and len(result["sections"]) > 15:
        result["sections"] = _merge_pptx_sections(result["sections"])

    log.info(
        "离线摘要完成: summary=%d字, sections=%d个",
        len(result["summary"]),
        len(result["sections"]),
    )

    return result


def _merge_pptx_sections(sections: list, max_sections: int = 10) -> list:
    """
    PPTX模式：将过多的section合并为逻辑分组。

    PPTX通常每页一个section，过多时按每3-4页合并为一组。

    Args:
        sections: 原始分段列表
        max_sections: 合并后最大分段数

    Returns:
        合并后的分段列表
    """
    if len(sections) <= max_sections:
        return sections

    # 按max_sections均分
    group_size = max(1, len(sections) // max_sections)
    merged = []

    for i in range(0, len(sections), group_size):
        group = sections[i:i + group_size]
        if len(group) == 1:
            merged.append(group[0])
        else:
            # 合并标题
            titles = [s["title"] for s in group]
            # 尝试提取标题中的页码信息
            title_str = "、".join(titles[:3])
            if len(titles) > 3:
                title_str += f" 等{len(titles)}页"

            # 合并摘要（取每段前100字）
            summaries = []
            for s in group:
                if s["summary"]:
                    summ = s["summary"]
                    if len(summ) > 100:
                        summ = summ[:100].rsplit('。', 1)[0] + '。'
                    summaries.append(summ)

            merged.append({
                "title": title_str,
                "summary": ' '.join(summaries),
            })

    return merged
