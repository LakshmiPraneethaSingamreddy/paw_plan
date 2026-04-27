from datetime import date, datetime, time

import pawpal_system

from pawpal_system import (
	AgentRole,
	AvailabilityWindow,
	CareTask,
	DailySchedule,
	Frequency,
	Pet,
	PetCareApp,
	ScheduleCandidate,
	ScheduleItem,
	SchedulerAgentOutput,
	TaskCategory,
	ValidationResult,
	ValidationViolation,
	ViolationSeverity,
)


def _build_owner_with_day_window(app: PetCareApp, start_hour: int = 6, end_hour: int = 22):
	owner = app.create_owner_profile()
	today = date.today()
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(hour=start_hour, minute=0),
			end_time=time(hour=end_hour, minute=0),
		)
	)
	pet = Pet(name="Nova", species="Dog", age_years=5, weight_kg=21.0)
	app.save_pet_info(owner.owner_id, pet)
	return owner, pet, today


def _make_dirty_schedule(
	owner: PetCareApp,
	pet_id,
	today: date,
	first_task: CareTask,
	second_task: CareTask,
	time_pairs: tuple[tuple[time, time], tuple[time, time]],
) -> tuple[ScheduleCandidate, DailySchedule]:
	first_start, first_end = time_pairs[0]
	second_start, second_end = time_pairs[1]
	schedule = DailySchedule(date=today)
	schedule.items = [
		ScheduleItem(
			start_time=datetime.combine(today, first_start),
			end_time=datetime.combine(today, first_end),
			reason_code="TEST_DIRTY_FIRST",
			task=first_task,
			pet_id=pet_id,
		),
		ScheduleItem(
			start_time=datetime.combine(today, second_start),
			end_time=datetime.combine(today, second_end),
			reason_code="TEST_DIRTY_SECOND",
			task=second_task,
			pet_id=pet_id,
		),
	]
	schedule.planning_metadata = {
		"reason_codes": ["TEST_DIRTY_FIRST", "TEST_DIRTY_SECOND"],
		"scheduled_count": len(schedule.items),
	}
	candidate = ScheduleCandidate(
		proposed_items=list(schedule.items),
		objective_score=float(len(schedule.items)),
		rationale_summary="Synthetic dirty candidate for phase 5 testing.",
		planning_summary_metadata=dict(schedule.planning_metadata),
		reason_codes=("TEST_DIRTY_FIRST", "TEST_DIRTY_SECOND"),
		generated_by=AgentRole.SCHEDULER,
		advisory_only=True,
	)
	return candidate, schedule


class _StaticSchedulerAgent:
	def __init__(self, candidate: ScheduleCandidate, schedule: DailySchedule):
		self._candidate = candidate
		self._schedule = schedule

	def propose_candidate(self, _context):
		return SchedulerAgentOutput(
			candidate=self._candidate,
			baseline_schedule=self._schedule,
			duration_ms=1,
		)


# Verifies the lightweight repair step regenerates overlapping items before the ladder escalates.
def test_phase5_lightweight_repair_regenerates_overlaps_and_records_diagnostics():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app)

	first_task = CareTask(
		title="Breakfast",
		category=TaskCategory.FEEDING,
		duration_min=60,
		priority=4,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=10, minute=0),
		is_flexible=False,
	)
	second_task = CareTask(
		title="Play",
		category=TaskCategory.PLAY,
		duration_min=30,
		priority=2,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=11, minute=0),
		is_flexible=True,
	)
	owner.add_task(pet.pet_id, first_task)
	owner.add_task(pet.pet_id, second_task)

	candidate, schedule = _make_dirty_schedule(
		app,
		pet.pet_id,
		today,
		first_task,
		second_task,
		((time(hour=8, minute=0), time(hour=9, minute=0)), (time(hour=8, minute=30), time(hour=9, minute=30))),
	)
	app.scheduler_agent = _StaticSchedulerAgent(candidate, schedule)

	final_schedule = app.run_daily_planning(owner.owner_id, today)

	assert final_schedule.items[0].start_time.time() == time(hour=8, minute=0)
	assert final_schedule.items[1].start_time.time() == time(hour=9, minute=0)
	assert final_schedule.planning_metadata["phase5_repair_strategy"] == "lightweight"
	assert app.planning_loop_diagnostics_by_owner_date[(owner.owner_id, today)]
	assert any(diagnostic.repair_strategy == "lightweight" for diagnostic in app.planning_loop_diagnostics_by_owner_date[(owner.owner_id, today)])


# Verifies targeted repair moves a flexible task back inside the owner availability window.
def test_phase5_targeted_repair_moves_flexible_task_into_availability():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app, start_hour=8, end_hour=10)

	first_task = CareTask(
		title="Breakfast",
		category=TaskCategory.FEEDING,
		duration_min=60,
		priority=4,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=9, minute=0),
		is_flexible=False,
	)
	second_task = CareTask(
		title="Play",
		category=TaskCategory.PLAY,
		duration_min=60,
		priority=2,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=30),
		latest_end=time(hour=10, minute=30),
		is_flexible=True,
	)
	owner.add_task(pet.pet_id, first_task)
	owner.add_task(pet.pet_id, second_task)

	candidate, schedule = _make_dirty_schedule(
		app,
		pet.pet_id,
		today,
		first_task,
		second_task,
		((time(hour=8, minute=0), time(hour=9, minute=0)), (time(hour=9, minute=30), time(hour=10, minute=30))),
	)
	app.scheduler_agent = _StaticSchedulerAgent(candidate, schedule)

	final_schedule = app.run_daily_planning(owner.owner_id, today)
	flexible_item = next(item for item in final_schedule.items if item.task and item.task.title == "Play")

	assert flexible_item.start_time.time() == time(hour=9, minute=0)
	assert flexible_item.end_time.time() == time(hour=10, minute=0)
	assert final_schedule.planning_metadata["phase5_repair_strategy"] == "targeted"
	assert any(diagnostic.repair_strategy == "targeted" for diagnostic in app.planning_loop_diagnostics_by_owner_date[(owner.owner_id, today)])


# Verifies the ladder can advance to structural repair and stays bounded when earlier repairs do not satisfy validation.
def test_phase5_structural_repair_is_reached_before_budget_exhaustion(monkeypatch):
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app)

	first_task = CareTask(
		title="Breakfast",
		category=TaskCategory.FEEDING,
		duration_min=30,
		priority=4,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=10, minute=0),
		is_flexible=False,
	)
	second_task = CareTask(
		title="Play",
		category=TaskCategory.PLAY,
		duration_min=30,
		priority=2,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=10, minute=0),
		is_flexible=True,
	)
	owner.add_task(pet.pet_id, first_task)
	owner.add_task(pet.pet_id, second_task)

	candidate, schedule = _make_dirty_schedule(
		app,
		pet.pet_id,
		today,
		first_task,
		second_task,
		((time(hour=8, minute=0), time(hour=8, minute=30)), (time(hour=8, minute=15), time(hour=8, minute=45))),
	)
	schedule.planning_metadata["phase5_force_repair"] = True
	candidate.planning_summary_metadata["phase5_force_repair"] = True
	app.scheduler_agent = _StaticSchedulerAgent(candidate, schedule)

	strategy_calls: list[str] = []

	def validator(candidate_to_validate, *_args, **_kwargs):
		strategy = candidate_to_validate.planning_summary_metadata.get("phase5_repair_strategy")
		strategy_calls.append(strategy or "initial")
		if strategy == "structural":
			return ValidationResult(status="pass")
		result = ValidationResult(status="fail")
		result.add_violation(
			ValidationViolation(
				code="PHASE5_TEST_FAILURE",
				message="Synthetic failure to force the ladder forward.",
				severity=ViolationSeverity.MEDIUM,
				repair_hint="Try the next repair strategy.",
			)
		)
		return result

	monkeypatch.setattr(pawpal_system, "validate_schedule_candidate", validator)

	final_schedule = app.run_daily_planning(owner.owner_id, today)

	assert final_schedule.planning_metadata["phase5_repair_strategy"] == "structural"
	assert strategy_calls[:4] == ["initial", "lightweight", "targeted", "structural"]
	diagnostics = app.planning_loop_diagnostics_by_owner_date[(owner.owner_id, today)]
	assert any(diagnostic.repair_strategy == "structural" for diagnostic in diagnostics)
	assert all(diagnostic.fallback_used is False for diagnostic in diagnostics if diagnostic.stage != "fallback")
