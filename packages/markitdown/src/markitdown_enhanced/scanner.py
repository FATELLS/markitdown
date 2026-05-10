"""
scanner.py — 文件前置检测

提供扫描件PDF检测、文件类型验证、路径过滤等功能。
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("markitdown_enhanced.scanner")

# 文件签名（magic bytes）-> 实际扩展名
FILE_SIGNATURES = {
    b'%PDF': '.pdf',
    b'PK\x03\x04': '.zip',  # ZIP-based (docx, xlsx, pptx, etc.)
    b'\xd0\xcf\x11\xe0': '.doc',  # OLE2 (old .doc, .xls, .ppt)
    b'\x89PNG': '.png',
    b'\xff\xd8\xff': '.jpg',
    b'GIF8': '.gif',
    b'BM': '.bmp',
    b'II*\x00': '.tiff',  # TIFF little-endian
    b'MM\x00*': '.tiff',  # TIFF big-endian
    b'<?xml': '.xml',
    b'{': '.json',
    b'<!DOCTYPE': '.html',
    b'<html': '.html',
}

# 不应作为源文件提取的目录
SKIP_DIRECTORY_PATTERNS = [
    "马虾分析报告",
]


def should_skip_path(file_path: str) -> bool:
    """
    判断是否应跳过该路径（非源文件目录）

    跳过工作产出目录（如马虾分析报告），这些不是源文件。
    """
    abs_path = os.path.abspath(file_path)
    path_parts = Path(abs_path).parts

    for pattern in SKIP_DIRECTORY_PATTERNS:
        if pattern in path_parts:
            log.debug("跳过非源文件目录: %s", file_path)
            return True

    return False


def validate_file_type(file_path: str) -> Optional[str]:
    """
    验证文件实际类型，不信任扩展名

    读取文件前几个字节与已知签名比对。

    Returns:
        检测到的实际扩展名（如 '.pdf'），或 None 表示无法识别
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
    except (IOError, OSError):
        return None

    if not header:
        return None

    for signature, detected_ext in FILE_SIGNATURES.items():
        if header.startswith(signature):
            return detected_ext

    # 尝试 python-magic（如果可用）
    try:
        import magic
        mime = magic.from_file(file_path, mime=True)
        mime_map = {
            'application/pdf': '.pdf',
            'image/png': '.png',
            'image/jpeg': '.jpg',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/tiff': '.tiff',
            'text/html': '.html',
            'text/xml': '.xml',
            'application/json': '.json',
            'text/csv': '.csv',
            'text/plain': '.txt',
        }
        return mime_map.get(mime)
    except ImportError:
        pass

    return None


def is_scanned_pdf(file_path: str) -> bool:
    """
    用PyMuPDF检测PDF是否为纯扫描件

    判断标准：平均每页可提取文本 < 100 字符视为扫描件。
    但如果任何单页 >= 200 字符，则认为包含有效文本，不是扫描件。
    这样可以避免截图PDF（每页仅少量OCR残留）被误判为有文字。

    Args:
        file_path: PDF文件路径

    Returns:
        True 表示是扫描件（图片PDF），False 表示包含可提取文本
    """
    try:
        import fitz
    except ImportError:
        log.warning("PyMuPDF(fitz)未安装，无法检测扫描件")
        return False

    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count
        if page_count == 0:
            doc.close()
            return False

        total_chars = 0
        for page in doc:
            text = page.get_text().strip()
            total_chars += len(text)
            # 如果某页有足够多文本，肯定不是扫描件
            if len(text) >= 200:
                doc.close()
                return False
        doc.close()

        avg_chars = total_chars / page_count
        return avg_chars < 100
    except Exception as e:
        log.warning("检测扫描件失败: %s — %s", file_path, e)
        return False
