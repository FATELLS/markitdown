# SPDX-FileCopyrightText: 2024-present Adam Fourney <adamfo@microsoft.com>
#
# SPDX-License-Identifier: MIT
import argparse
import sys
import codecs
import logging
from textwrap import dedent
from importlib.metadata import entry_points
from .__about__ import __version__
from ._markitdown import MarkItDown, StreamInfo, DocumentConverterResult


def main():
    parser = argparse.ArgumentParser(
        description="Convert various file formats to markdown.",
        prog="markitdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage=dedent(
            """
            SYNTAX:

                markitdown <OPTIONAL: FILENAME>
                If FILENAME is empty, markitdown reads from stdin.

            EXAMPLE:

                markitdown example.pdf

                OR

                cat example.pdf | markitdown

                OR

                markitdown < example.pdf

                OR to save to a file use

                markitdown example.pdf -o example.md

                OR

                markitdown example.pdf > example.md

            ENHANCED (post-processing):

                markitdown example.pdf --enhanced-clean
                markitdown example.pdf --enhanced-clean --extract-keywords
                markitdown example.pdf --scan-detect
                markitdown example.pdf --gen-doc-obj -o output_dir/
            """
        ).strip(),
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="show the version number and exit",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output file name. If not provided, output is written to stdout.",
    )

    parser.add_argument(
        "-x",
        "--extension",
        help="Provide a hint about the file extension (e.g., when reading from stdin).",
    )

    parser.add_argument(
        "-m",
        "--mime-type",
        help="Provide a hint about the file's MIME type.",
    )

    parser.add_argument(
        "-c",
        "--charset",
        help="Provide a hint about the file's charset (e.g, UTF-8).",
    )

    parser.add_argument(
        "-d",
        "--use-docintel",
        action="store_true",
        help="Use Document Intelligence to extract text instead of offline conversion. Requires a valid Document Intelligence Endpoint.",
    )

    parser.add_argument(
        "-e",
        "--endpoint",
        type=str,
        help="Document Intelligence Endpoint. Required if using Document Intelligence.",
    )

    parser.add_argument(
        "-p",
        "--use-plugins",
        action="store_true",
        help="Use 3rd-party plugins to convert files. Use --list-plugins to see installed plugins.",
    )

    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="List installed 3rd-party plugins. Plugins are loaded when using the -p or --use-plugin option.",
    )

    parser.add_argument(
        "--keep-data-uris",
        action="store_true",
        help="Keep data URIs (like base64-encoded images) in the output. By default, data URIs are truncated.",
    )

    # ===== Enhanced post-processing arguments =====
    enhanced_group = parser.add_argument_group(
        "Enhanced Post-Processing",
        "Additional processing options for document extraction quality.",
    )

    enhanced_group.add_argument(
        "--enhanced-clean",
        action="store_true",
        help="Enable 15-step Markdown post-processing pipeline (remove noise, clean tables, compress blank lines, etc.).",
    )

    enhanced_group.add_argument(
        "--extract-keywords",
        action="store_true",
        help="Extract Chinese keywords using jieba TF-IDF (requires jieba). Keywords are appended after conversion.",
    )

    enhanced_group.add_argument(
        "--scan-detect",
        action="store_true",
        help="Detect if a PDF is a scanned image (requires PyMuPDF/fitz). Warns and skips scanned PDFs.",
    )

    enhanced_group.add_argument(
        "--gen-doc-obj",
        action="store_true",
        help="Generate document_obj format with frontmatter metadata. Requires -o to specify output directory.",
    )

    enhanced_group.add_argument(
        "--chinese-opt",
        action="store_true",
        help="Enable Chinese optimizations (HuggingFace mirror, etc.).",
    )

    enhanced_group.add_argument(
        "--aggressive",
        action="store_true",
        help="Aggressive mode: truncate very large documents (>50000 lines). Only effective with --enhanced-clean.",
    )

    enhanced_group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for enhanced processing.",
    )

    parser.add_argument("filename", nargs="?")
    args = parser.parse_args()

    # Setup logging for enhanced features
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s - %(levelname)s - %(message)s",
        )

    # Chinese optimization
    if args.chinese_opt:
        try:
            from markitdown_enhanced.chinese import enable_chinese_optimization
            enable_chinese_optimization()
        except ImportError:
            print("Warning: markitdown_enhanced.chinese not available, skipping Chinese optimization.", file=sys.stderr)

    # Parse the extension hint
    extension_hint = args.extension
    if extension_hint is not None:
        extension_hint = extension_hint.strip().lower()
        if len(extension_hint) > 0:
            if not extension_hint.startswith("."):
                extension_hint = "." + extension_hint
        else:
            extension_hint = None

    # Parse the mime type
    mime_type_hint = args.mime_type
    if mime_type_hint is not None:
        mime_type_hint = mime_type_hint.strip()
        if len(mime_type_hint) > 0:
            if mime_type_hint.count("/") != 1:
                _exit_with_error(f"Invalid MIME type: {mime_type_hint}")
        else:
            mime_type_hint = None

    # Parse the charset
    charset_hint = args.charset
    if charset_hint is not None:
        charset_hint = charset_hint.strip()
        if len(charset_hint) > 0:
            try:
                charset_hint = codecs.lookup(charset_hint).name
            except LookupError:
                _exit_with_error(f"Invalid charset: {charset_hint}")
        else:
            charset_hint = None

    stream_info = None
    if (
        extension_hint is not None
        or mime_type_hint is not None
        or charset_hint is not None
    ):
        stream_info = StreamInfo(
            extension=extension_hint, mimetype=mime_type_hint, charset=charset_hint
        )

    if args.list_plugins:
        # List installed plugins, then exit
        print("Installed MarkItDown 3rd-party Plugins:\n")
        plugin_entry_points = list(entry_points(group="markitdown.plugin"))
        if len(plugin_entry_points) == 0:
            print("  * No 3rd-party plugins installed.")
            print(
                "\nFind plugins by searching for the hashtag #markitdown-plugin on GitHub.\n"
            )
        else:
            for entry_point in plugin_entry_points:
                print(f"  * {entry_point.name:<16}\t(package: {entry_point.value})")
            print(
                "\nUse the -p (or --use-plugins) option to enable 3rd-party plugins.\n"
            )
        sys.exit(0)

    if args.use_docintel:
        if args.endpoint is None:
            _exit_with_error(
                "Document Intelligence Endpoint is required when using Document Intelligence."
            )
        elif args.filename is None:
            _exit_with_error("Filename is required when using Document Intelligence.")

        markitdown = MarkItDown(
            enable_plugins=args.use_plugins, docintel_endpoint=args.endpoint
        )
    else:
        markitdown = MarkItDown(enable_plugins=args.use_plugins)

    # Scan detect: check if PDF is scanned before conversion
    if args.scan_detect and args.filename:
        try:
            from markitdown_enhanced.scanner import is_scanned_pdf
            if args.filename.lower().endswith(".pdf"):
                if is_scanned_pdf(args.filename):
                    print(f"WARNING: {args.filename} appears to be a scanned image PDF (no extractable text). Skipping.", file=sys.stderr)
                    sys.exit(0)
                else:
                    if args.verbose:
                        print("Scan detection: PDF contains extractable text, proceeding.", file=sys.stderr)
        except ImportError:
            print("Warning: markitdown_enhanced.scanner not available, skipping scan detection.", file=sys.stderr)

    if args.filename is None:
        result = markitdown.convert_stream(
            sys.stdin.buffer,
            stream_info=stream_info,
            keep_data_uris=args.keep_data_uris,
        )
    else:
        result = markitdown.convert(
            args.filename, stream_info=stream_info, keep_data_uris=args.keep_data_uris
        )

    # Apply enhanced post-processing
    md_text = result.markdown
    keywords_str = ""

    # Enhanced clean
    if args.enhanced_clean:
        try:
            from markitdown_enhanced.cleaner import clean_markdown
            md_text = clean_markdown(md_text, aggressive=args.aggressive)
            if args.verbose:
                print(f"Enhanced clean applied.", file=sys.stderr)
        except ImportError:
            print("Warning: markitdown_enhanced.cleaner not available, skipping clean.", file=sys.stderr)

    # Extract keywords
    if args.extract_keywords:
        try:
            from markitdown_enhanced.keywords import extract_keywords
            keywords_str = extract_keywords(md_text, top_n=8)
            if keywords_str and args.verbose:
                print(f"Keywords: {keywords_str}", file=sys.stderr)
        except ImportError:
            print("Warning: markitdown_enhanced.keywords not available, skipping keyword extraction.", file=sys.stderr)

    # Generate doc_obj format
    if args.gen_doc_obj:
        try:
            from markitdown_enhanced.generator import generate_doc_obj
            if not args.output:
                _exit_with_error("--gen-doc-obj requires -o to specify output directory.")
            output_path = generate_doc_obj(
                file_path=args.filename or "stdin",
                md_content=md_text,
                output_dir=args.output,
                keywords=keywords_str,
            )
            print(f"Document object generated: {output_path}", file=sys.stderr)
            return
        except ImportError:
            print("Warning: markitdown_enhanced.generator not available, skipping doc_obj generation.", file=sys.stderr)

    # Append keywords to output if extracted (and not using gen-doc-obj)
    if keywords_str and not args.gen_doc_obj:
        md_text = md_text + f"\n\n## 关键词\n\n{keywords_str}\n"

    # Handle output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md_text)
    else:
        # Handle stdout encoding errors more gracefully
        print(
            md_text.encode(sys.stdout.encoding, errors="replace").decode(
                sys.stdout.encoding
            )
        )


def _exit_with_error(message: str):
    print(message)
    sys.exit(1)


if __name__ == "__main__":
    main()
