"""
client.py — LLM调用客户端

使用OpenAI兼容接口调用LLM，支持重试、超时、超长文本截断。
"""

import os
import time
import logging

log = logging.getLogger("markitdown_enhanced.harness.client")

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "openai 库未安装。请运行: pip install openai\n"
        "本项目使用 OpenAI 兼容接口调用 LLM，绝大多数模型 API 都支持此协议。"
    )

from .prompts import get_prompt, SYSTEM_PROMPT, parse_interpret_output


class LLMSummarizer:
    """LLM可解释提取客户端"""

    MAX_INPUT_CHARS = 15000
    HEAD_CHARS = 12000
    TAIL_CHARS = 3000

    def __init__(
        self,
        provider: str = "openai",
        model: str = None,
        base_url: str = None,
        api_key: str = None,
        max_tokens: int = 4096,
        timeout: int = 120,
    ):
        """
        LLM调用封装。

        Args:
            provider: 目前只支持 openai 兼容接口
            model: 模型名称，默认从环境变量 LLM_MODEL 读取
            base_url: API地址，默认从环境变量 LLM_BASE_URL 读取
            api_key: API密钥，默认从环境变量 LLM_API_KEY 读取
            max_tokens: 最大输出token数
            timeout: 请求超时秒数
        """
        self.provider = provider
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL")
        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        self.max_tokens = max_tokens
        self.timeout = timeout

        # 构建 OpenAI 客户端
        client_kwargs = {
            "timeout": timeout,
        }
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)

        log.info(
            "LLMSummarizer 初始化: provider=%s, model=%s, base_url=%s",
            self.provider,
            self.model,
            self.base_url or "(default)",
        )

    def summarize(
        self,
        text: str,
        doc_type: str = "general",
        language: str = "zh",
    ) -> dict:
        """
        对文档内容生成可解释层摘要。

        Args:
            text: 文档Markdown文本
            doc_type: 文档类型 (pptx/pdf/general)
            language: 输出语言

        Returns:
            {
                "summary": "全文摘要（3-5句话）",
                "sections": [
                    {"title": "第1页：封面", "summary": "..."},
                    {"title": "第2页：需求分析", "summary": "..."},
                ]
            }
        """
        prompt_template = get_prompt(doc_type)
        prompt = prompt_template.format(content=text)

        raw_output = self._call_llm(prompt, system=SYSTEM_PROMPT)
        result = parse_interpret_output(raw_output)

        log.info(
            "LLM摘要完成: summary=%d字, sections=%d个",
            len(result["summary"]),
            len(result["sections"]),
        )
        return result

    def _call_llm(self, prompt: str, system: str = None) -> str:
        """
        底层调用LLM。

        支持重试（3次，指数退避）。
        自动检测文本长度，超长文本截断并提示。

        Args:
            prompt: 用户prompt
            system: 系统prompt

        Returns:
            LLM输出文本
        """
        # 超长文本截断
        if len(prompt) > self.MAX_INPUT_CHARS:
            original_len = len(prompt)
            head = prompt[: self.HEAD_CHARS]
            tail = prompt[-self.TAIL_CHARS :]
            prompt = head + "\n\n...[中间部分已省略，原文共{:,}字符]...\n\n" + tail
            log.warning(
                "输入文本过长(%d字符)，已截断为%d字符",
                original_len,
                len(prompt),
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # 重试逻辑：3次，间隔 1s/2s/4s
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                )
                return response.choices[0].message.content.strip()

            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt  # 1, 2, 4
                log.warning(
                    "LLM调用失败(第%d次): %s, %ds后重试...",
                    attempt + 1,
                    str(e),
                    wait_time,
                )
                if attempt < 2:
                    time.sleep(wait_time)

        raise RuntimeError(f"LLM调用失败（已重试3次）: {last_error}") from last_error
