from datetime import date, time

from pawpal_system import (
	AgentRole,
	AvailabilityWindow,
	CareTask,
	DeterministicSchedulerAgent,
	Frequency,
	Pet,
	PetCareApp,
	ScheduleCandidate,
	SchedulerAgentOutput,
	TaskCategory,
)


def _build_owner_with_pet(app: PetCareApp):
	owner = app.create_owner_profile()
	today = date.today()
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


# Verifies scheduler agent returns candidate metadata while preserving deterministic engine output.
def test_scheduler_agent_returns_candidate_with_machine_readable_metadata():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

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
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Weekly grooming",
			category=TaskCategory.GROOMING,
			duration_min=30,
			priority=1,
			frequency=Frequency.WEEKLY,
			weekly_day_of_week=(today.weekday() + 1) % 7,
			earliest_start=time(hour=15, minute=0),
			latest_end=time(hour=16, minute=0),
		),
	)

	context = app._build_planning_context(owner.owner_id, owner, today)
	candidate, baseline_schedule, _ = app._run_scheduler_agent_wrapper(context)

	assert candidate.generated_by == AgentRole.SCHEDULER
	assert candidate.advisory_only is True
	assert candidate.rationale_metadata["source_of_truth"] == "SchedulerService.generate_daily_schedule"
	assert candidate.planning_summary_metadata["scheduled_count"] == len(baseline_schedule.items)
	assert candidate.planning_summary_metadata["recurrence_skipped_count"] == 1
	assert set(candidate.reason_codes) == set(candidate.planning_summary_metadata["reason_codes"])


# Verifies run_daily_planning uses the modular scheduler agent interface.
def test_orchestrator_calls_scheduler_agent_interface_once():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning walk",
			category=TaskCategory.WALKING,
			duration_min=25,
			priority=2,
			earliest_start=time(hour=7, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)

	class SpySchedulerAgent:
		def __init__(self, deterministic_agent: DeterministicSchedulerAgent):
			self.calls = 0
			self._deterministic_agent = deterministic_agent

		def propose_candidate(self, context):
			self.calls += 1
			return self._deterministic_agent.propose_candidate(context)

	spy_agent = SpySchedulerAgent(DeterministicSchedulerAgent(app.scheduler_service))
	app.scheduler_agent = spy_agent

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items
	assert spy_agent.calls == 1


# Verifies reason codes and planning summary metadata are attached to deterministic outputs.
def test_scheduler_outputs_machine_readable_reason_codes_and_summary_metadata():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Flexible play",
			category=TaskCategory.PLAY,
			duration_min=60,
			priority=1,
			is_flexible=True,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Vet check",
			category=TaskCategory.VET,
			duration_min=45,
			priority=4,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items
	assert schedule.planning_metadata["scheduled_count"] == len(schedule.items)
	assert schedule.planning_metadata["ordering_policy"] == "non_flexible_then_priority_then_deadline"
	assert schedule.planning_metadata["strategy"] == "defer_flexible_then_remove_lower_priority_rigid"

	for item in schedule.items:
		assert item.reason_code.startswith("PLACED_")

	context = app._build_planning_context(owner.owner_id, owner, today)
	candidate, _, _ = app._run_scheduler_agent_wrapper(context)
	assert candidate.reason_codes
	assert "reason_codes" in candidate.planning_summary_metadata
