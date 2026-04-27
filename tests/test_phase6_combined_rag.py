from datetime import date, time

import pytest

from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	Frequency,
	LocalRetrievalCorpus,
	PlanExplanation,
	RetrievalSnippet,
	OwnerPreference,
	Pet,
	PetCareApp,
	DeterministicExplanationAgent,
	TaskCategory,
	TaskValidationError,
)


def _build_owner_with_preferences_and_window(app: PetCareApp):
	owner = app.create_owner_profile()
	today = date.today()
	owner.preference = OwnerPreference(
		max_tasks_per_block=2,
		preferred_task_order="feeding, walk, play",
		avoid_late_night=True,
		notification_lead_min=30,
	)
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)
	pet = Pet(name="Nova", species="Dog", age_years=5, weight_kg=21.0)
	app.save_pet_info(owner.owner_id, pet)
	return owner, pet, today


def test_phase6_explanation_includes_retrieved_sources_and_attribution():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_preferences_and_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Breakfast",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
			is_flexible=False,
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	retrieved_explanations = [
		explanation
		for explanation in schedule.explanations
		if explanation.rule_applied == "phase6_retrieved_context"
	]

	assert retrieved_explanations
	assert any("Sources:" in explanation.message for explanation in retrieved_explanations)
	assert any("policy:hard_constraints" in explanation.message for explanation in retrieved_explanations)
	assert schedule.planning_metadata["retrieval_hint_count"] > 0


def test_phase6_retrieval_chunks_content_and_gracefully_yields_nothing_on_low_confidence():
	corpus = LocalRetrievalCorpus(
		[
			RetrievalSnippet(
				source_type="policy",
				source_label="rules",
				content="alpha; beta; gamma",
			),
		]
	)

	chunked_results = corpus.retrieve("beta", top_k=3)
	assert chunked_results
	assert chunked_results[0].source_label.endswith("#chunk2")
	assert chunked_results[0].content == "beta"

	assert corpus.retrieve("zzzz-nonmatching-query", top_k=3) == []


def test_phase7_task_validation_appends_retrieval_corrections():
	app = PetCareApp()
	owner, pet, _today = _build_owner_with_preferences_and_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Bad duration",
			category=TaskCategory.WALKING,
			duration_min=15,
			priority=2,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=9, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	invalid_task = CareTask(
		title="Bad duration",
		category=TaskCategory.WALKING,
		duration_min=0,
		priority=2,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=9, minute=0),
		latest_end=time(hour=10, minute=0),
	)

	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(owner.owner_id, pet.pet_id, invalid_task)

	assert any(v.code == "INVALID_DURATION" for v in exc_info.value.result.violations)
	assert any(
		hint.startswith("Retrieved correction hint from")
		for hint in exc_info.value.result.repair_hints
	)
	assert any(
		hint.startswith("Normalization suggestion from retrieval:")
		for hint in exc_info.value.result.repair_hints
	)


def test_phase7_scheduler_wrapper_attaches_advisory_retrieval_hints():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_preferences_and_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning walk",
			category=TaskCategory.WALKING,
			duration_min=25,
			priority=2,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=7, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)

	context = app._build_planning_context(owner.owner_id, owner, today)
	candidate, baseline_schedule, _ = app._run_scheduler_agent_wrapper(context)

	assert candidate.rationale_metadata["retrieval_hints"]
	assert baseline_schedule.planning_metadata["retrieval_hint_count"] > 0


def test_phase6_groundedness_guard_rejects_obvious_unsupported_claims():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_preferences_and_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Breakfast",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
			is_flexible=False,
		),
	)

	context = app._build_planning_context(owner.owner_id, owner, today)
	agent = DeterministicExplanationAgent()
	fake_explanation = PlanExplanation(
		message="This is the best schedule ever.",
		rule_applied="phase4_grounded_summary",
		impact_score=1.0,
	)

	assert agent._passes_groundedness_guardrails(
		fake_explanation,
		schedule=app.run_daily_planning(owner.owner_id, today),
		context=context,
		retrieved_snippets=[],
	) is False