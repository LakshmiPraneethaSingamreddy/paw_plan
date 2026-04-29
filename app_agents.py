from __future__ import annotations

import streamlit as st

from app_helpers import build_plan_explanation_lines
from llm_agents import LLMExplanationAgent
from llm_config import get_llm_config


def render_ai_explanation_section(schedule, owner_id, schedule_date) -> None:
	"""Render the optional AI explanation controls and cached summary."""
	if not schedule.explanations:
		return

	enhance_key = f"llm_expl_{owner_id}_{schedule_date.isoformat()}"
	enhanced_text = st.session_state.get(enhance_key)

	header_left, header_right = st.columns([3, 1])
	with header_left:
		st.markdown("### Plan explanation")
	with header_right:
		if enhanced_text:
			if st.button("Clear AI summary", key=f"clear_{enhance_key}"):
				del st.session_state[enhance_key]
				st.rerun()
		elif get_llm_config().is_valid():
			if st.button("✨ Explain with AI", key=f"btn_{enhance_key}"):
				raw_lines = build_plan_explanation_lines(schedule)
				with st.spinner("Generating AI explanation..."):
					agent = LLMExplanationAgent()
					enhanced = agent.enhance_explanations_text([line.lstrip("- ") for line in raw_lines])
				if enhanced:
					st.session_state[enhance_key] = enhanced
					st.rerun()
				else:
					cfg = get_llm_config()
					st.warning(
						f"AI explanation call failed (model: `{cfg.explanation_model}`). "
						"Check your OPENAI_API_KEY and that LLM_EXPLANATION_MODEL is a valid model name."
					)

	if enhanced_text:
		st.info(enhanced_text)
		st.caption(f"✨ Rewritten by AI · {get_llm_config().explanation_model}")
	else:
		raw_lines = build_plan_explanation_lines(schedule)
		for explanation_line in raw_lines:
			st.write(explanation_line)