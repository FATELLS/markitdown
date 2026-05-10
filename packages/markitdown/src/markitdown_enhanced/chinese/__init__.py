"""
chinese — 中文优化配置

提供 HuggingFace 镜像设置等中文环境优化。
"""

import os
import logging

log = logging.getLogger("markitdown_enhanced.chinese")

# HuggingFace 镜像列表
HF_MIRRORS = [
    "https://hf-mirror.com",
    "https://mirrors.tuna.tsinghua.edu.cn/hugging-face-models",
]


def enable_chinese_optimization() -> dict:
    """
    启用中文优化：设置 HuggingFace 镜像等环境变量

    Returns:
        设置的环境变量字典
    """
    env_vars = {}

    # 设置 HuggingFace 镜像
    hf_mirror = os.environ.get("HF_ENDPOINT", "")
    if not hf_mirror:
        os.environ["HF_ENDPOINT"] = HF_MIRRORS[0]
        env_vars["HF_ENDPOINT"] = HF_MIRRORS[0]
        log.info("已设置 HF_ENDPOINT=%s", HF_MIRRORS[0])

    return env_vars
