from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	ConstraintType,
	DailySchedule,
	Frequency,
	Owner,
	OwnerPreference,
	Pet,
	PetCareApp,
	ScheduleItem,
	ScheduleStatus,
	SchedulingConstraint,
	TaskCategory,
	TaskValidationError,
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

	pet = Pet(name="Buddy", species="Dog", age_years=4, weight_kg=24.0)
	app.save_pet_info(owner.owner_id, pet)
	return owner, pet, today


# Verifies marking a scheduled task as complete updates completion fields.
def test_mark_task_completion_updates_schedule_item_status():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning Walk",
			category=TaskCategory.WALKING,
			duration_min=30,
			priority=9,
			earliest_start=time(hour=7, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items

	item_id = schedule.items[0].item_id
	assert schedule.items[0].completed is False
	assert schedule.items[0].completed_at is None

	app.mark_task_completion(owner.owner_id, today, item_id, completed=True)

	updated_schedule = app.schedules_by_owner_date[(owner.owner_id, today)]
	updated_item = next(item for item in updated_schedule.items if item.item_id == item_id)
	assert updated_item.completed is True
	assert updated_item.completed_at is not None


# Verifies completed tasks remain completed after schedule regeneration on the same date.
def test_completed_task_persists_after_regeneration_same_date():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	walk_task = CareTask(
		title="Morning Walk",
		category=TaskCategory.WALKING,
		duration_min=30,
		priority=9,
		earliest_start=time(hour=7, minute=0),
		latest_end=time(hour=10, minute=0),
	)
	owner.add_task(pet.pet_id, walk_task)

	first_schedule = app.run_daily_planning(owner.owner_id, today)
	first_walk_item = next(item for item in first_schedule.items if item.task and item.task.task_id == walk_task.task_id)
	app.mark_task_completion(owner.owner_id, today, first_walk_item.item_id, completed=True)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Lunch Feed",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=6,
			earliest_start=time(hour=12, minute=0),
			latest_end=time(hour=14, minute=0),
		),
	)

	regenerated_schedule = app.run_daily_planning(owner.owner_id, today)
	regenerated_walk_item = next(
		item
		for item in regenerated_schedule.items
		if item.task and item.task.task_id == walk_task.task_id
	)

	assert regenerated_walk_item.completed is True
	assert regenerated_walk_item.completed_at is not None


# Verifies adding a task through owner API actually appends to the pet's task list.
def test_add_task_increases_pet_task_count():
	app = PetCareApp()
	owner, pet, _ = _build_owner_with_pet(app)

	initial_count = len(pet.tasks)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Breakfast",
			category=TaskCategory.FEEDING,
			duration_min=15,
			priority=10,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=30),
		),
	)

	assert len(pet.tasks) == initial_count + 1


# Verifies morning tasks are scheduled and their end times obey expected morning limits.
def test_scheduler_respects_time_windows_for_morning_tasks():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning walk",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=3,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Feed breakfast",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=30),
			latest_end=time(hour=9, minute=30),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Playdate",
			category=TaskCategory.PLAY,
			duration_min=60,
			priority=2,
			frequency=Frequency.CUSTOM,
			custom_days_of_week=[today.weekday()],
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=30),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Vet appointment",
			category=TaskCategory.VET,
			duration_min=120,
			priority=3,
			frequency=Frequency.CUSTOM,
			custom_days_of_week=[today.weekday()],
			earliest_start=time(hour=12, minute=0),
			latest_end=time(hour=14, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items

	scheduled_titles = {item.task.title for item in schedule.items if item.task}
	morning_tasks = {"Morning walk", "Feed breakfast", "Playdate"}
	assert morning_tasks.issubset(scheduled_titles), (
		"Expected all morning tasks to be scheduled so their time-window assertions are meaningful"
	)

	for item in schedule.items:
		assert item.task is not None
		assert item.end_time is not None
		if item.task.latest_end is not None and not item.task.is_flexible:
			assert item.end_time.time() <= item.task.latest_end

	for item in schedule.items:
		if item.task and item.task.title in morning_tasks:
			assert item.end_time is not None
			assert item.end_time.time() <= time(hour=10, minute=0)


# Verifies explanations contain specific placement/skip decisions and non-empty reason codes.
def test_scheduler_provides_specific_decision_explanations():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Breakfast",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Long Grooming",
			category=TaskCategory.GROOMING,
			duration_min=180,
			is_flexible=False,
			priority=2,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=30),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.explanations

	messages = [explanation.message for explanation in schedule.explanations]
	assert any("Placed 'Breakfast'" in message for message in messages)
	assert any("Skipped 'Long Grooming'" in message for message in messages)

	breakfast_item = next(item for item in schedule.items if item.task and item.task.title == "Breakfast")
	assert breakfast_item.reason_code is not None
	assert breakfast_item.reason_code.strip() != ""
	assert "window_aware_priority" not in breakfast_item.reason_code


# Verifies higher-priority rigid tasks survive contention with lower-priority flexible tasks.
def test_scheduler_prioritizes_high_priority_over_low_with_backtracking():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Play with mochi",
			category=TaskCategory.PLAY,
			duration_min=60,
			priority=1,
			is_flexible=True,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="buy mochi ice cream",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=1,
			is_flexible=True,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="take mochi to vet",
			category=TaskCategory.VET,
			duration_min=40,
			priority=3,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=30),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items

	scheduled_titles = {item.task.title for item in schedule.items if item.task}
	assert "take mochi to vet" in scheduled_titles, "High-priority vet task should be scheduled"

	messages = [explanation.message.lower() for explanation in schedule.explanations]
	assert any("vet" in msg or "defer" in msg for msg in messages), (
		"Explanations should mention vet task or deferring"
	)


# Verifies scheduler defers flexible tasks instead of dropping them when placing a rigid task.
def test_scheduler_defers_flexible_tasks_over_removing_them():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Flexible playtime",
			category=TaskCategory.PLAY,
			duration_min=60,
			priority=1,
			is_flexible=True,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=18, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Crucial vet appointment",
			category=TaskCategory.VET,
			duration_min=40,
			priority=3,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert len(schedule.items) == 2, "Both tasks should be scheduled"

	scheduled_titles = [item.task.title if item.task else "" for item in schedule.items]
	assert "Flexible playtime" in scheduled_titles
	assert "Crucial vet appointment" in scheduled_titles

	vet_item = next(item for item in schedule.items if item.task and item.task.title == "Crucial vet appointment")
	play_item = next(item for item in schedule.items if item.task and item.task.title == "Flexible playtime")

	assert vet_item.start_time < play_item.start_time, "Non-flexible vet should be scheduled before flexible playtime"

	messages = [explanation.message.lower() for explanation in schedule.explanations]
	assert any("defer" in msg for msg in messages), "Should mention deferring flexible tasks"


# Verifies non-flexible tasks are ordered before flexible ones during scheduling.
def test_scheduler_non_flexible_tasks_prioritized_in_ordering():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Flexible low-priority task",
			category=TaskCategory.PLAY,
			duration_min=30,
			priority=1,
			is_flexible=True,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=20, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Non-flexible medium-priority task",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=2,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert len(schedule.items) == 2, f"Expected 2 items, got {len(schedule.items)}"

	feeding_item = next((item for item in schedule.items if item.task and item.task.title == "Non-flexible medium-priority task"), None)
	play_item = next((item for item in schedule.items if item.task and item.task.title == "Flexible low-priority task"), None)

	assert feeding_item is not None, "Non-flexible feeding task should be scheduled"
	assert play_item is not None, "Flexible play task should be scheduled"
	assert feeding_item.start_time < play_item.start_time, (
		"Non-flexible task should be scheduled before flexible task regardless of priority"
	)


# Verifies weekly tasks run only on the configured weekday.
def test_weekly_task_schedules_only_on_matching_weekday():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Weekly grooming",
			category=TaskCategory.GROOMING,
			duration_min=30,
			priority=2,
			frequency=Frequency.WEEKLY,
			weekly_day_of_week=today.weekday(),
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=12, minute=0),
		),
	)

	today_schedule = app.run_daily_planning(owner.owner_id, today)
	assert any(item.task and item.task.title == "Weekly grooming" for item in today_schedule.items)

	next_day = today + timedelta(days=1)
	next_day_schedule = app.run_daily_planning(owner.owner_id, next_day)
	assert not any(item.task and item.task.title == "Weekly grooming" for item in next_day_schedule.items)


# Verifies custom interval recurrence includes only matching interval days.
def test_custom_interval_task_schedules_on_interval_days_only():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=(today + timedelta(days=1)).weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=(today + timedelta(days=2)).weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Custom meds",
			category=TaskCategory.MEDICATION,
			duration_min=15,
			priority=3,
			frequency=Frequency.CUSTOM,
			custom_interval_days=2,
			custom_anchor_date=today,
			earliest_start=time(hour=9, minute=0),
			latest_end=time(hour=11, minute=0),
		),
	)

	today_schedule = app.run_daily_planning(owner.owner_id, today)
	assert any(item.task and item.task.title == "Custom meds" for item in today_schedule.items)

	day_plus_one_schedule = app.run_daily_planning(owner.owner_id, today + timedelta(days=1))
	assert not any(item.task and item.task.title == "Custom meds" for item in day_plus_one_schedule.items)

	day_plus_two_schedule = app.run_daily_planning(owner.owner_id, today + timedelta(days=2))
	assert any(item.task and item.task.title == "Custom meds" for item in day_plus_two_schedule.items)


# Verifies schedules are empty when requested weekday has no configured availability.
def test_scheduler_returns_empty_for_unconfigured_weekday_even_if_other_days_exist():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	next_day = today + timedelta(days=1)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Daily fallback walk",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=2,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, next_day)
	assert not any(item.task and item.task.title == "Daily fallback walk" for item in schedule.items)
	assert any(
		explanation.rule_applied == "availability_required"
		for explanation in schedule.explanations
	)


# Verifies returned schedule items are sorted chronologically.
def test_schedule_items_returned_in_chronological_order():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Late morning walk",
			category=TaskCategory.WALKING,
			duration_min=15,
			priority=2,
			earliest_start=time(hour=10, minute=0),
			latest_end=time(hour=12, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Early breakfast",
			category=TaskCategory.FEEDING,
			duration_min=15,
			priority=2,
			earliest_start=time(hour=7, minute=30),
			latest_end=time(hour=9, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Mid-morning meds",
			category=TaskCategory.MEDICATION,
			duration_min=15,
			priority=2,
			earliest_start=time(hour=9, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert len(schedule.items) == 3

	start_times = [item.start_time for item in schedule.items]
	assert all(start is not None for start in start_times)
	assert start_times == sorted(start_times)


# Verifies daily tasks generate new schedule items on subsequent days after completion.
def test_marking_daily_task_complete_creates_next_day_schedule_item():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	next_day = today + timedelta(days=1)
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=next_day.weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Daily dinner",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=18, minute=0),
			latest_end=time(hour=20, minute=0),
		),
	)

	today_schedule = app.run_daily_planning(owner.owner_id, today)
	today_item = next(item for item in today_schedule.items if item.task and item.task.title == "Daily dinner")

	app.mark_task_completion(owner.owner_id, today, today_item.item_id, completed=True)

	next_day_schedule = app.run_daily_planning(owner.owner_id, next_day)
	next_day_item = next(item for item in next_day_schedule.items if item.task and item.task.title == "Daily dinner")

	assert today_item.completed is True
	assert next_day_item.item_id != today_item.item_id
	assert next_day_item.completed is False


# Verifies regenerate resolves direct overlaps and records overlap-adjustment explanation.
def test_regenerate_flags_duplicate_time_conflicts():
	today = date.today()

	task_a = CareTask(
		title="Breakfast",
		category=TaskCategory.FEEDING,
		duration_min=30,
		priority=3,
	)
	task_b = CareTask(
		title="Walk",
		category=TaskCategory.WALKING,
		duration_min=30,
		priority=2,
	)

	duplicate_start = datetime.combine(today, time(hour=9, minute=0))
	duplicate_end = datetime.combine(today, time(hour=9, minute=30))

	schedule = DailySchedule(
		date=today,
		status=ScheduleStatus.DRAFT,
		items=[
			ScheduleItem(task=task_a, start_time=duplicate_start, end_time=duplicate_end),
			ScheduleItem(task=task_b, start_time=duplicate_start, end_time=duplicate_end),
		],
	)

	schedule.regenerate()

	assert len(schedule.items) == 2
	first, second = schedule.items
	assert first.end_time <= second.start_time
	assert any("adjusted 1 overlaps" in explanation.message for explanation in schedule.explanations)


# Verifies planner handles pets with no tasks by returning an empty schedule plus summary.
def test_scheduler_handles_pet_with_no_tasks():
	app = PetCareApp()
	owner, _pet, today = _build_owner_with_pet(app)

	schedule = app.run_daily_planning(owner.owner_id, today)

	assert schedule.items == []
	assert any("scheduled 0 task(s)" in explanation.message for explanation in schedule.explanations)


# Verifies planner returns empty schedule when no availability windows exist.
def test_scheduler_returns_empty_when_no_availability_windows():
	app = PetCareApp()
	owner = app.create_owner_profile()
	pet = Pet(name="Buddy", species="Dog", age_years=4, weight_kg=24.0)
	app.save_pet_info(owner.owner_id, pet)
	today = date.today()

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Breakfast",
			category=TaskCategory.FEEDING,
			duration_min=15,
			priority=2,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)

	assert schedule.items == []
	assert any(
		explanation.rule_applied == "availability_required"
		for explanation in schedule.explanations
	)


# Verifies weekly recurrence now requires an explicit weekday and rejects missing values.
def test_weekly_task_without_weekday_is_rejected_by_guardrails():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	with pytest.raises(TaskValidationError) as exc_info:
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Weekly fallback grooming",
				category=TaskCategory.GROOMING,
				duration_min=20,
				priority=2,
				frequency=Frequency.WEEKLY,
				weekly_day_of_week=None,
				earliest_start=time(hour=8, minute=0),
				latest_end=time(hour=12, minute=0),
			),
		)

	assert len(pet.tasks) == 0
	assert any(v.code == "INCOHERENT_RECURRENCE_WEEKLY_DAY" for v in exc_info.value.result.violations)


# Verifies custom interval recurrence requires an anchor date in Phase 2.
def test_custom_interval_without_anchor_is_rejected_by_guardrails():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	with pytest.raises(TaskValidationError) as exc_info:
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Custom no-anchor meds",
				category=TaskCategory.MEDICATION,
				duration_min=10,
				priority=2,
				frequency=Frequency.CUSTOM,
				custom_interval_days=2,
				custom_anchor_date=None,
				earliest_start=time(hour=9, minute=0),
				latest_end=time(hour=11, minute=0),
			),
		)

	assert len(pet.tasks) == 0
	assert any(v.code == "INCOHERENT_RECURRENCE_CUSTOM_ANCHOR" for v in exc_info.value.result.violations)


# Verifies non-positive custom intervals are rejected before persistence.
def test_custom_interval_non_positive_is_rejected_by_guardrails():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	with pytest.raises(TaskValidationError) as exc_info:
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Broken interval task",
				category=TaskCategory.MEDICATION,
				duration_min=10,
				priority=2,
				frequency=Frequency.CUSTOM,
				custom_interval_days=0,
				custom_anchor_date=today,
				earliest_start=time(hour=9, minute=0),
				latest_end=time(hour=11, minute=0),
			),
		)

	assert len(pet.tasks) == 0
	assert any(v.code == "INCOHERENT_RECURRENCE_CUSTOM_INTERVAL" for v in exc_info.value.result.violations)


# Verifies zero/negative durations are rejected before persistence.
def test_scheduler_rejects_zero_or_negative_duration_tasks():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	with pytest.raises(TaskValidationError):
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Zero duration task",
				category=TaskCategory.FEEDING,
				duration_min=0,
				priority=3,
				earliest_start=time(hour=8, minute=0),
				latest_end=time(hour=9, minute=0),
			),
		)

	with pytest.raises(TaskValidationError):
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Negative duration task",
				category=TaskCategory.PLAY,
				duration_min=-10,
				priority=3,
				earliest_start=time(hour=9, minute=0),
				latest_end=time(hour=10, minute=0),
			),
		)

	assert len(pet.tasks) == 0


# Verifies deterministic ordering for tasks with identical priority and time windows.
def test_identical_priority_time_tasks_schedule_in_deterministic_order():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Task A",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=2,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Task B",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=2,
			is_flexible=False,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule_1 = app.run_daily_planning(owner.owner_id, today)
	schedule_2 = app.run_daily_planning(owner.owner_id, today)

	order_1 = [item.task.title for item in schedule_1.items if item.task]
	order_2 = [item.task.title for item in schedule_2.items if item.task]

	assert order_1 == ["Task A", "Task B"]
	assert order_2 == ["Task A", "Task B"]


# Verifies completion API raises a clear error when no schedule exists for the date.
def test_mark_task_completion_raises_when_schedule_not_found():
	app = PetCareApp()
	owner, _pet, today = _build_owner_with_pet(app)

	with pytest.raises(ValueError, match="Schedule not found"):
		app.mark_task_completion(owner.owner_id, today, uuid4(), completed=True)


# Verifies schedule-level completion API raises when item ID is unknown.
def test_mark_item_completion_raises_when_item_not_found():
	schedule = DailySchedule(date=date.today(), status=ScheduleStatus.DRAFT)

	with pytest.raises(ValueError, match="Schedule item not found"):
		schedule.mark_item_completion(item_id=uuid4(), completed=True)


# Verifies regenerate enforces required schedule date.
def test_regenerate_raises_when_date_is_missing():
	schedule = DailySchedule(date=None, status=ScheduleStatus.DRAFT)

	with pytest.raises(ValueError, match="Schedule date is required to regenerate"):
		schedule.regenerate()


# Verifies regenerate does not move locked overlapping items.
def test_regenerate_does_not_adjust_locked_overlaps():
	today = date.today()
	start = datetime.combine(today, time(hour=9, minute=0))
	first_end = datetime.combine(today, time(hour=10, minute=0))
	locked_end = datetime.combine(today, time(hour=10, minute=30))

	first_item = ScheduleItem(
		task=CareTask(title="Task 1", category=TaskCategory.FEEDING, duration_min=60, priority=3),
		start_time=start,
		end_time=first_end,
	)
	locked_item = ScheduleItem(
		task=CareTask(title="Task 2", category=TaskCategory.WALKING, duration_min=60, priority=2),
		start_time=datetime.combine(today, time(hour=9, minute=30)),
		end_time=locked_end,
		locked=True,
	)

	schedule = DailySchedule(
		date=today,
		status=ScheduleStatus.DRAFT,
		items=[first_item, locked_item],
	)

	schedule.regenerate()

	assert len(schedule.items) == 2
	assert schedule.items[0].end_time > schedule.items[1].start_time
	assert any("adjusted 0 overlaps" in explanation.message for explanation in schedule.explanations)


# Verifies custom weekday recurrence schedules only on explicitly selected weekdays.
def test_custom_days_of_week_recurrence_filters_correctly():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	next_day = today + timedelta(days=1)

	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=next_day.weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Custom weekday-only task",
			category=TaskCategory.MEDICATION,
			duration_min=15,
			priority=2,
			frequency=Frequency.CUSTOM,
			custom_days_of_week=[next_day.weekday()],
			earliest_start=time(hour=9, minute=0),
			latest_end=time(hour=11, minute=0),
		),
	)

	today_schedule = app.run_daily_planning(owner.owner_id, today)
	next_day_schedule = app.run_daily_planning(owner.owner_id, next_day)

	assert not any(item.task and item.task.title == "Custom weekday-only task" for item in today_schedule.items)
	assert any(item.task and item.task.title == "Custom weekday-only task" for item in next_day_schedule.items)


# Verifies avoid_late_night owner preference filters out tasks ending at or after 22:00.
def test_apply_constraints_respects_avoid_late_night_preference():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	owner.preference = OwnerPreference(avoid_late_night=True)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Late task",
			category=TaskCategory.PLAY,
			duration_min=30,
			priority=2,
			earliest_start=time(hour=21, minute=30),
			latest_end=time(hour=22, minute=30),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Early task",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=2,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	titles = {item.task.title for item in schedule.items if item.task}

	assert "Early task" in titles
	assert "Late task" not in titles


# Verifies hard constraints remove tasks that violate constraint validation.
def test_apply_constraints_respects_hard_constraint_filtering():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	hard_constraint = SchedulingConstraint(
		name="No tasks ending after 09:00",
		constraint_type=ConstraintType.TIME_AVAILABILITY,
		is_hard_constraint=True,
		allowed_end=time(hour=9, minute=0),
	)
	app.scheduler_service.constraints.append(hard_constraint)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Allowed task",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=2,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Blocked task",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=3,
			earliest_start=time(hour=8, minute=30),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	titles = {item.task.title for item in schedule.items if item.task}

	assert "Allowed task" in titles
	assert "Blocked task" not in titles


# Verifies invalid availability windows are surfaced in skip explanations.
def test_invalid_availability_window_yields_clear_skip_reason():
	app = PetCareApp()
	owner = app.create_owner_profile()
	today = date.today()

	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(hour=18, minute=0),
			end_time=time(hour=8, minute=0),
		)
	)

	pet = Pet(name="Buddy", species="Dog", age_years=4, weight_kg=24.0)
	app.save_pet_info(owner.owner_id, pet)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Needs valid window",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=2,
			earliest_start=time(hour=9, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert not any(item.task and item.task.title == "Needs valid window" for item in schedule.items)
	assert any(
		"availability window" in explanation.message and "is invalid" in explanation.message
		for explanation in schedule.explanations
	)


# Verifies flexible tasks can overflow past deadlines while rigid tasks remain within deadlines.
def test_flexible_tasks_can_overflow_past_deadline_assertive():
	app = PetCareApp()
	owner = Owner(name="Test Owner", timezone="America/Chicago")
	owner.preference = OwnerPreference(avoid_late_night=False)
	app.owners_by_id[owner.owner_id] = owner

	pet = Pet(name="Mochi", species="Dog", age_years=2, height_cm=30, weight_kg=5)
	owner.add_pet(pet)

	today = date.today()
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(8, 0),
			end_time=time(18, 0),
		)
	)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning walk",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=3,
			earliest_start=time(8, 0),
			latest_end=time(10, 0),
			is_flexible=False,
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Feed",
			category=TaskCategory.FEEDING,
			duration_min=20,
			priority=3,
			earliest_start=time(8, 0),
			latest_end=time(9, 30),
			is_flexible=False,
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Play",
			category=TaskCategory.PLAY,
			duration_min=60,
			priority=1,
			earliest_start=time(8, 0),
			latest_end=time(10, 0),
			is_flexible=True,
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Vet appointment",
			category=TaskCategory.VET,
			duration_min=60,
			priority=3,
			earliest_start=time(8, 0),
			latest_end=time(10, 30),
			is_flexible=True,
		),
	)
	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Buy ice cream",
			category=TaskCategory.FEEDING,
			duration_min=30,
			priority=1,
			earliest_start=time(8, 0),
			latest_end=time(10, 0),
			is_flexible=True,
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items

	overflow_flexible = [
		item
		for item in schedule.items
		if item.task
		and item.task.is_flexible
		and item.task.latest_end is not None
		and item.end_time is not None
		and item.end_time.time() > item.task.latest_end
	]
	assert overflow_flexible, "Expected at least one flexible task to overflow past its deadline"

	for item in schedule.items:
		if item.task and not item.task.is_flexible and item.task.latest_end is not None:
			assert item.end_time is not None
			assert item.end_time.time() <= item.task.latest_end
