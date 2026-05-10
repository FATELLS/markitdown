"""
converter.py — 多引擎文档转换器

支持8种引擎自动fallback:
  markitdown, docling, pymupdf, antiword, textutil, libreoffice, openpyxl, python-pptx

用法:
    from markitdown_enhanced import DocumentConverter
    converter = DocumentConverter()
    md_text = converter.convert("input.docx")
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("markitdown_enhanced.converter")

# 配置HuggingFace镜像（国内环境）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 文件大小阈值: 超过此值优先使用PyMuPDF（更快）
_LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB


class DocumentConverter:
    """多引擎文档转换器，自动选择最佳引擎"""

    def __init__(self, preferred_engine: str = "auto"):
        """
        Args:
            preferred_engine: 首选引擎
                "auto" — 按文件类型和大小自动选择
                "markitdown" — 只用MarkItDown原生
                "docling" — 优先Docling
                "pymupdf" — 优先PyMuPDF
        """
        self.preferred_engine = preferred_engine

    def convert(self, file_path: str) -> str:
        """
        转换文档为Markdown文本。
        按优先级尝试多个引擎，第一个成功的就返回。

        引擎选择逻辑:
          PDF (<=10MB): markitdown → docling → pymupdf
          PDF (>10MB):  pymupdf → markitdown → docling
          DOCX:         markitdown → docling → libreoffice转码→markitdown
          DOC:          antiword → textutil → libreoffice转码→docling
          XLSX:         markitdown → openpyxl手动提取
          PPTX:         markitdown → python-pptx手动提取
          其他:         markitdown → docling

        Returns:
            转换后的Markdown文本
        Raises:
            RuntimeError: 所有引擎都失败时
        """
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = Path(file_path).suffix.lower()
        file_size = os.path.getsize(file_path)

        log.info("开始转换: %s (类型: %s, 大小: %.1fMB)",
                 os.path.basename(file_path), ext, file_size / 1024 / 1024)

        if self.preferred_engine == "markitdown":
            # 只用原生引擎
            engines = [self._try_markitdown]
        elif self.preferred_engine == "docling":
            engines = [self._try_docling, self._try_markitdown, self._try_pymupdf]
        elif self.preferred_engine == "pymupdf":
            engines = [self._try_pymupdf, self._try_markitdown, self._try_docling]
        elif ext == ".pdf":
            if file_size > _LARGE_FILE_THRESHOLD:
                engines = [self._try_pymupdf, self._try_markitdown, self._try_docling]
            else:
                engines = [self._try_markitdown, self._try_docling, self._try_pymupdf]
        elif ext == ".docx":
            engines = [self._try_markitdown, self._try_docling, self._try_libreoffice_docx]
        elif ext == ".doc":
            engines = [self._try_antiword, self._try_textutil, self._try_libreoffice_doc]
        elif ext in (".xlsx", ".xls"):
            engines = [self._try_markitdown, self._try_openpyxl]
        elif ext == ".pptx":
            engines = [self._try_markitdown, self._try_python_pptx]
        else:
            engines = [self._try_markitdown, self._try_docling]

        last_error = None
        for engine_fn in engines:
            engine_name = engine_fn.__name__.replace("_try_", "")
            log.info("尝试引擎: %s", engine_name)
            try:
                result = engine_fn(file_path)
                if result and len(result.strip()) >= 10:
                    log.info("引擎 %s 成功: %d字符", engine_name, len(result))
                    return result
                else:
                    log.warning("引擎 %s 返回内容过短(%d字符), 跳过",
                                engine_name, len(result.strip()) if result else 0)
            except Exception as e:
                log.warning("引擎 %s 失败: %s", engine_name, e)
                last_error = e

        raise RuntimeError(
            f"所有引擎均失败: {file_path}\n"
            f"尝试了: {[fn.__name__.replace('_try_', '') for fn in engines]}\n"
            f"最后错误: {last_error}"
        )

    # =========================================================================
    # 引擎方法
    # =========================================================================

    def _try_markitdown(self, file_path: str) -> Optional[str]:
        """用MarkItDown原生引擎"""
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(file_path)
        text = result.text_content or ""
        if len(text.strip()) < 10:
            return None
        return text

    def _try_docling(self, file_path: str) -> Optional[str]:
        """用Docling引擎（需要docling包）"""
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(file_path)
            md = result.document.export_to_markdown()
            if len(md.strip()) < 10:
                return None
            return md
        except ImportError:
            log.debug("docling未安装")
            return None
        except Exception as e:
            log.debug("docling转换异常: %s", e)
            return None

    def _try_pymupdf(self, file_path: str) -> Optional[str]:
        """用PyMuPDF提取PDF文本"""
        try:
            import fitz
            doc = fitz.open(file_path)
            pages = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text)
            doc.close()
            md = "\n\n".join(pages)
            if len(md.strip()) < 10:
                return None
            return md
        except ImportError:
            log.debug("fitz(PyMuPDF)未安装")
            return None
        except Exception as e:
            log.debug("pymupdf提取异常: %s", e)
            return None

    def _try_antiword(self, file_path: str) -> Optional[str]:
        """用antiword提取.doc文件"""
        try:
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return None
            text = result.stdout
            if len(text.strip()) < 10:
                return None
            return text
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        except Exception as e:
            log.debug("antiword异常: %s", e)
            return None

    def _try_textutil(self, file_path: str) -> Optional[str]:
        """用macOS textutil提取（.doc/.docx）"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                out_path = f.name
            try:
                subprocess.run(
                    ["textutil", "-convert", "txt", "-output", out_path, file_path],
                    capture_output=True, timeout=30,
                )
                with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if len(text.strip()) < 10:
                    return None
                return text
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)
        except Exception as e:
            log.debug("textutil异常: %s", e)
            return None

    def _try_libreoffice_docx(self, file_path: str) -> Optional[str]:
        """用LibreOffice将DOCX重新转码后再提取"""
        try:
            with tempfile.TemporaryDirectory(prefix="lo_convert_") as tmpdir:
                subprocess.run(
                    ["/opt/homebrew/bin/soffice", "--headless", "--convert-to", "docx",
                     "--outdir", tmpdir, file_path],
                    capture_output=True, timeout=120,
                )
                docx_files = [f for f in os.listdir(tmpdir) if f.endswith(".docx")]
                if not docx_files:
                    return None
                converted = os.path.join(tmpdir, docx_files[0])
                # 用markitdown提取转换后的文件
                text = self._try_markitdown(converted)
                if not text:
                    text = self._try_docling(converted)
                return text
        except Exception as e:
            log.debug("libreoffice(docx)异常: %s", e)
            return None

    def _try_libreoffice_doc(self, file_path: str) -> Optional[str]:
        """用LibreOffice将.doc转码后再提取"""
        try:
            with tempfile.TemporaryDirectory(prefix="lo_convert_") as tmpdir:
                subprocess.run(
                    ["/opt/homebrew/bin/soffice", "--headless", "--convert-to", "docx",
                     "--outdir", tmpdir, file_path],
                    capture_output=True, timeout=120,
                )
                docx_files = [f for f in os.listdir(tmpdir) if f.endswith(".docx")]
                if not docx_files:
                    return None
                converted = os.path.join(tmpdir, docx_files[0])
                text = self._try_docling(converted)
                if not text:
                    text = self._try_markitdown(converted)
                return text
        except Exception as e:
            log.debug("libreoffice(doc)异常: %s", e)
            return None

    def _try_openpyxl(self, file_path: str) -> Optional[str]:
        """用openpyxl手动提取xlsx"""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file_path, read_only=True, data_only=True)
            parts = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                parts.append(f"## {sheet_name}\n")
                rows = list(ws.iter_rows(values_only=True))
                if rows:
                    header = [str(c) if c is not None else "" for c in rows[0]]
                    parts.append("| " + " | ".join(header) + " |")
                    parts.append("| " + " | ".join(["---"] * len(header)) + " |")
                    for row in rows[1:101]:
                        cells = [str(c) if c is not None else "—" for c in row]
                        parts.append("| " + " | ".join(cells) + " |")
                parts.append("")
            wb.close()
            md = "\n".join(parts)
            if len(md.strip()) < 10:
                return None
            return md
        except Exception as e:
            log.debug("openpyxl异常: %s", e)
            return None

    def _try_python_pptx(self, file_path: str) -> Optional[str]:
        """用python-pptx手动提取pptx"""
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                parts.append(f"### Slide {i}\n")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            text = para.text.strip()
                            if text:
                                parts.append(text)
                parts.append("")
            md = "\n".join(parts)
            if len(md.strip()) < 10:
                return None
            return md
        except Exception as e:
            log.debug("python-pptx异常: %s", e)
            return None
