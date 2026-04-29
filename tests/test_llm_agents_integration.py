"""Tests for LLM explanation enhancer integration."""

from datetime import date, time
from unittest.mock import Mock, patch
import pytest

from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	Pet,
	PetCareApp,
	TaskCategory,
)


def test_app_uses_deterministic_scheduler_by_default():
	"""Scheduling always uses the deterministic agent."""
	app = PetCareApp()

	owner = app.create_owner_profile()
	owner.name = "Alice"
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=date.today().weekday(),
			start_time=time(hour=8, minute=0),
			end_time=time(hour=18, minute=0),
		)
	)

	pet = Pet(name="Fluffy", species="cat", age_years=3, weight_kg=4.0)
	app.save_pet_info(owner.owner_id, pet)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Feed cat",
			category=TaskCategory.FEEDING,
			duration_min=10,
			priority=3,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=18, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, date.today())
	assert schedule is not None
	assert len(schedule.items) > 0


def test_llm_explanation_agent_has_correct_interface():
	"""LLMExplanationAgent exposes enhance_explanations_text."""
	with patch("llm_config.get_llm_config") as mock_config:
		mock_config.return_value = Mock(
			is_valid=Mock(return_value=False),
			explanation_model="gpt-4o-mini",
			max_tokens=1500,
			temperature=0.7,
			timeout_seconds=60,
		)
		try:
			from llm_agents import LLMExplanationAgent

			agent = LLMExplanationAgent()
			assert hasattr(agent, "enhance_explanations_text")
			assert callable(agent.enhance_explanations_text)
			assert hasattr(agent, "is_available")
			assert callable(agent.is_available)
		except ImportError:
			pytest.skip("llm_agents module not available")


def test_llm_explanation_agent_returns_none_without_client():
	"""enhance_explanations_text returns None gracefully when no API key."""
	with patch("llm_config.get_llm_config") as mock_config:
		mock_config.return_value = Mock(
			is_valid=Mock(return_value=False),
			explanation_model="gpt-4o-mini",
			max_tokens=1500,
			temperature=0.7,
			timeout_seconds=60,
		)
		try:
			from llm_agents import LLMExplanationAgent

			agent = LLMExplanationAgent()
			assert agent.is_available() is False
			result = agent.enhance_explanations_text(["Morning walk at 07:00", "Breakfast at 07:30"])
			assert result is None
		except ImportError:
			pytest.skip("llm_agents module not available")


def test_llm_config_validates_api_credentials():
	"""LLM config validates API credentials correctly."""
	from llm_config import LLMConfig

	assert LLMConfig(enabled=True, api_key=None).is_valid() is False
	assert LLMConfig(enabled=True, api_key="sk-test-key-12345").is_valid() is True
	assert LLMConfig(enabled=False, api_key="sk-test-key-12345").is_valid() is False


def test_llm_config_loads_from_environment():
	"""LLM config can be loaded from environment variables."""
	with patch.dict("os.environ", {
		"OPENAI_API_KEY": "sk-test-key",
		"LLM_SCHEDULER_MODEL": "gpt-5-mini",
		"LLM_EXPLANATION_MODEL": "gpt-5-nano",
		"LLM_ENABLED": "true",
	}):
		from llm_config import LLMConfig
		config = LLMConfig.from_env()

		assert config.api_key == "sk-test-key"
		assert config.scheduler_model == "gpt-5-mini"
		assert config.explanation_model == "gpt-5-nano"
		assert config.model == "gpt-5-mini"
		assert config.enabled is True
		assert config.is_valid() is True


if __name__ == "__main__":
	pytest.main([__file__, "-v"])
