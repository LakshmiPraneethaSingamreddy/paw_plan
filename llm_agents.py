"""LLM-backed explanation enhancer for PawPal+ schedules."""

from __future__ import annotations

import logging
from typing import Any, Optional

try:
	from openai import OpenAI, APIError, APIConnectionError, RateLimitError
except ImportError:  # pragma: no cover - handled gracefully
	OpenAI = None
	APIError = APIConnectionError = RateLimitError = Exception

from llm_config import LLMConfig, LLMPromptTemplates, get_llm_config

logger = logging.getLogger(__name__)


class LLMExplanationAgent:
	"""Rewrites deterministic schedule explanations into friendly natural language."""

	def __init__(self, llm_config: Optional[LLMConfig] = None):
		self.llm_config = llm_config or get_llm_config()
		self.client: Any = None
		self._init_client()

	def _init_client(self) -> None:
		if self.llm_config.is_valid() and OpenAI is not None:
			try:
				self.client = OpenAI(api_key=self.llm_config.api_key)
				logger.info("OpenAI client initialized for explanation enhancement.")
			except Exception as e:
				logger.warning(f"Failed to initialize OpenAI client: {e}")
				self.client = None
		else:
			logger.info("LLM config not valid; explanation enhancer disabled.")

	def is_available(self) -> bool:
		"""Return True if the LLM client is ready to make calls."""
		return self.client is not None

	def enhance_explanations_text(self, raw_lines: list[str]) -> Optional[str]:
		"""Take raw deterministic explanation lines and return a friendly paragraph."""
		if not raw_lines:
			return None
		prompt = LLMPromptTemplates.explanation_enhancer_prompt("\n".join(raw_lines))
		return self._call_llm(prompt)

	def _call_llm(self, prompt: str) -> Optional[str]:
		if not self.client:
			return None

		completion_kwargs = {
			"model": self.llm_config.explanation_model,
			"messages": [
				{"role": "system", "content": "You are a friendly pet care assistant."},
				{"role": "user", "content": prompt},
			],
			"timeout": self.llm_config.timeout_seconds,
		}
		if self.llm_config.explanation_model.startswith("gpt-5"):
			completion_kwargs["max_completion_tokens"] = self.llm_config.max_tokens
		else:
			completion_kwargs["max_tokens"] = self.llm_config.max_tokens
			completion_kwargs["temperature"] = self.llm_config.temperature

		try:
			message = self.client.chat.completions.create(**completion_kwargs)
			choice = message.choices[0]
			if choice.finish_reason == "length":
				logger.warning(
					"Explanation response was cut off by max_tokens limit "
					f"(max_tokens={self.llm_config.max_tokens}). "
					"Increase LLM_MAX_TOKENS if explanations are truncated."
				)
			return choice.message.content
		except (APIError, APIConnectionError, RateLimitError) as e:
			logger.warning(f"LLM API call failed: {e}.")
			return None
		except Exception as e:
			logger.error(f"Unexpected error calling LLM: {e}")
			return None
