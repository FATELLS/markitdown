"""
keywords.py — 关键词提取

基于jieba分词TF-IDF，改进：
- 跳过代码块
- 跳过表格行
- 扩大停用词列表（SQL语法词、CSS属性、表格边框字符等）
"""

import re
import logging

log = logging.getLogger("markitdown_enhanced.keywords")

# 扩展停用词列表
STOP_WORDS = {
    # English common
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "Notes", "image", "Unnamed", "nan", "NaN",
    # CSS properties / HTML attributes
    "pt", "px", "opt", "td", "align", "font", "padding", "margin", "border",
    "color", "select", "span", "div", "class", "style", "width", "height",
    # SQL keywords
    "select", "from", "where", "into", "set", "table", "column", "row",
    "null", "true", "false", "int", "varchar", "varchar2", "number", "float",
    "double", "text", "date", "timestamp", "default", "primary", "key",
    "foreign", "reference", "constraint", "index", "create", "alter", "drop",
    "insert", "update", "delete", "grant", "revoke", "commit", "rollback",
    "begin", "end", "case", "when", "then", "else", "if", "exists", "like",
    "between", "values", "count", "sum", "avg", "min", "max", "distinct",
    "dual",
    # Common English prepositions/conjunctions (in Chinese text)
    "in", "is", "as", "on", "by", "to", "or", "of", "with", "use",
    # SQL / query fragments
    "mode", "name", "type", "id", "desc", "asc", "all", "any", "some",
    "no", "yes", "top", "limit", "offset", "order", "group", "having",
    "union", "intersect", "except", "join", "left", "right", "inner",
    "outer", "cross", "natural", "full", "using",
    # Table border characters
    "+---", "+----", "-----", "|---", "|----",
}


def _remove_code_blocks(text: str) -> str:
    """移除代码块（``` ... ``` 之间的内容）"""
    return re.sub(r'```[\s\S]*?```', '', text)


def _remove_inline_code(text: str) -> str:
    """移除行内代码"""
    return re.sub(r'`[^`]+`', '', text)


def _is_table_line(line: str) -> bool:
    """判断是否为表格行"""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith('|'):
        return True
    if re.match(r'^[\s|+\-:]+$', stripped):
        return True
    return False


def extract_keywords(md_text: str, top_n: int = 8) -> str:
    """
    从Markdown正文提取关键词（基于jieba分词TF-IDF）

    改进点：
    - 先移除代码块内容
    - 跳过表格行
    - 使用扩展停用词列表

    Args:
        md_text: Markdown文本
        top_n: 返回关键词数量

    Returns:
        逗号分隔的关键词字符串
    """
    try:
        import jieba.analyse
    except ImportError:
        log.warning("jieba未安装，跳过关键词提取")
        return ""

    # 移除代码块
    text = _remove_code_blocks(md_text)
    text = _remove_inline_code(text)

    # 按行处理
    lines = text.split("\n")
    text_lines = []
    for l in lines:
        stripped = l.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if _is_table_line(l):
            continue
        if stripped.startswith("---"):
            continue
        if stripped.startswith("<!--"):
            continue
        text_lines.append(stripped)

    text = " ".join(text_lines[:200])  # 取前200行足够

    if not text.strip():
        return ""

    keywords = jieba.analyse.extract_tags(text, topK=top_n + 5)
    keywords = [k for k in keywords if k not in STOP_WORDS and len(k) >= 2][:top_n]
    return ", ".join(keywords)
