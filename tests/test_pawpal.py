import importlib
from datetime import date, datetime, time, timedelta
import sys
import types
from uuid import uuid4

import pytest

from pawpal_system import (
	AgentRole,
	AvailabilityWindow,
	CareTask,
	ConstraintType,
	DailySchedule,
	DETERMINISTIC_FALLBACK_POLICY,
	DeterministicExplanationAgent,
	Frequency,
	HARD_CONSTRAINT_RULES,
	LocalRetrievalCorpus,
	Owner,
	OwnerPreference,
	Pet,
	PetCareApp,
	PlanExplanation,
	RetrievalSnippet,
	ScheduleItem,
	ScheduleStatus,
	SchedulingConstraint,
	SCHEDULE_SOURCE_OF_TRUTH,
	ScheduleCandidate,
	SchedulerAgentOutput,
	TaskCategory,
	TaskValidationError,
	ValidationResult,
	ValidationViolation,
	ViolationSeverity,
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


class _FakeSessionState(dict):
	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError as exc:
			raise AttributeError(name) from exc

	def __setattr__(self, name, value):
		self[name] = value


class _FakeColumn:
	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False


class _FakeStreamlit(types.ModuleType):
	def __init__(self):
		super().__init__("streamlit")
		self.session_state = _FakeSessionState()
		self.calls: list[tuple[str, tuple, dict]] = []

	def _record(self, name: str, *args, **kwargs):
		self.calls.append((name, args, kwargs))

	def set_page_config(self, *args, **kwargs):
		self._record("set_page_config", *args, **kwargs)

	def markdown(self, *args, **kwargs):
		self._record("markdown", *args, **kwargs)

	def divider(self, *args, **kwargs):
		self._record("divider", *args, **kwargs)

	def subheader(self, *args, **kwargs):
		self._record("subheader", *args, **kwargs)

	def text_input(self, label, value="", **kwargs):
		self._record("text_input", label, value, **kwargs)
		return value

	def number_input(self, label, value=0, **kwargs):
		self._record("number_input", label, value, **kwargs)
		return value

	def checkbox(self, label, value=False, **kwargs):
		self._record("checkbox", label, value, **kwargs)
		return value

	def multiselect(self, label, options, default=None, **kwargs):
		self._record("multiselect", label, options, default, **kwargs)
		return list(default or [])

	def time_input(self, label, value=None, **kwargs):
		self._record("time_input", label, value, **kwargs)
		return value

	def date_input(self, label, value=None, **kwargs):
		self._record("date_input", label, value, **kwargs)
		return value

	def selectbox(self, label, options, index=0, **kwargs):
		self._record("selectbox", label, options, index, **kwargs)
		if not options:
			return None
		if index is None:
			return options[0]
		if isinstance(index, int):
			return options[min(index, len(options) - 1)]
		return options[0]

	def button(self, label, **kwargs):
		self._record("button", label, **kwargs)
		return False

	def columns(self, specs, **kwargs):
		self._record("columns", specs, **kwargs)
		count = specs if isinstance(specs, int) else len(specs)
		return [_FakeColumn() for _ in range(count)]

	def write(self, *args, **kwargs):
		self._record("write", *args, **kwargs)

	def success(self, *args, **kwargs):
		self._record("success", *args, **kwargs)

	def error(self, *args, **kwargs):
		self._record("error", *args, **kwargs)

	def info(self, *args, **kwargs):
		self._record("info", *args, **kwargs)

	def warning(self, *args, **kwargs):
		self._record("warning", *args, **kwargs)

	def caption(self, *args, **kwargs):
		self._record("caption", *args, **kwargs)

	def table(self, *args, **kwargs):
		self._record("table", *args, **kwargs)

	def rerun(self, *args, **kwargs):
		self._record("rerun", *args, **kwargs)

	def text_area(self, label, value="", **kwargs):
		self._record("text_area", label, value, **kwargs)
		return value

	def __getattr__(self, name):
		def _noop(*args, **kwargs):
			self._record(name, *args, **kwargs)
			return None

		return _noop


def _load_app_module_with_fake_streamlit(monkeypatch):
	fake_streamlit = _FakeStreamlit()
	monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
	sys.modules.pop("app", None)
	module = importlib.import_module("app")
	return module, fake_streamlit


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


# Verifies weekly task with missing weekday is auto-repaired to task creation day.
def test_weekly_task_without_weekday_is_auto_repaired():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

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

	assert len(pet.tasks) == 1
	assert pet.tasks[0].weekly_day_of_week == today.weekday()


# Verifies custom interval task missing anchor date is auto-repaired to task creation date.
def test_custom_interval_without_anchor_is_auto_repaired():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

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

	assert len(pet.tasks) == 1
	assert pet.tasks[0].custom_anchor_date == today


# Verifies non-positive custom intervals are auto-repaired to 1 before persistence.
def test_custom_interval_non_positive_is_auto_repaired():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

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

	assert len(pet.tasks) == 1
	assert pet.tasks[0].custom_interval_days == 1


# Verifies zero/negative durations are auto-repaired to the default minimum before persistence.
def test_scheduler_auto_repairs_zero_or_negative_duration_tasks():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

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

	assert len(pet.tasks) == 2
	assert all(t.duration_min == 15 for t in pet.tasks)


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


def test_phase8_agent_handoff_contract_keeps_scheduler_advisory_only_and_retrieval_hinted():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	owner.preference = OwnerPreference(
		max_tasks_per_block=3,
		preferred_task_order="feeding, walk, play",
		avoid_late_night=True,
		notification_lead_min=20,
	)

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

	context = app._build_planning_context(owner.owner_id, owner, today)
	candidate, baseline_schedule, duration_ms = app._run_scheduler_agent_wrapper(context)

	assert candidate.generated_by == AgentRole.SCHEDULER
	assert candidate.advisory_only is True
	assert candidate.rationale_metadata["source_of_truth"] == SCHEDULE_SOURCE_OF_TRUTH
	assert candidate.rationale_metadata["fallback_policy"] == DETERMINISTIC_FALLBACK_POLICY
	assert candidate.rationale_metadata["hard_constraint_rules"] == list(HARD_CONSTRAINT_RULES)
	assert candidate.reason_codes == tuple(baseline_schedule.planning_metadata.get("reason_codes", []))
	assert baseline_schedule.planning_metadata["retrieval_hint_count"] > 0
	assert duration_ms >= 0


def test_phase8_guardrail_rejection_returns_actionable_repair_hints():
	app = PetCareApp()
	owner, pet, _today = _build_owner_with_pet(app)

	walk = CareTask(
		title="Morning Walk",
		category=TaskCategory.WALKING,
		duration_min=30,
		priority=3,
		earliest_start=time(hour=7, minute=0),
		latest_end=time(hour=9, minute=0),
	)
	owner.add_task(pet.pet_id, walk)

	# Exact duplicate triggers DUPLICATE_TASK (non-repairable) so still raises.
	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(
			owner.owner_id,
			pet.pet_id,
			CareTask(
				title="Morning Walk",
				category=TaskCategory.WALKING,
				duration_min=30,
				priority=3,
				earliest_start=time(hour=7, minute=0),
				latest_end=time(hour=9, minute=0),
			),
		)

	result = exc_info.value.result
	assert len(pet.tasks) == 1
	assert any(violation.code == "DUPLICATE_TASK" for violation in result.violations)
	assert any(hint.startswith("Retrieved correction hint from") for hint in result.repair_hints)
	assert any(hint.startswith("Normalization suggestion from retrieval:") for hint in result.repair_hints)
	assert any("align this task with" in hint for hint in result.repair_hints)


def test_phase8_self_check_converges_after_single_retry(monkeypatch):
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Retryable feed",
			category=TaskCategory.FEEDING,
			duration_min=15,
			priority=3,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
		),
	)

	state = {"calls": 0}

	def flaky_validator(*_args, **_kwargs):
		state["calls"] += 1
		if state["calls"] == 1:
			result = ValidationResult(status="fail")
			result.add_violation(
				ValidationViolation(
					code="TRANSIENT_PHASE8_FAILURE",
					message="Synthetic transient failure.",
					severity=ViolationSeverity.MEDIUM,
					repair_hint="Retry once.",
				)
			)
			return result
		return ValidationResult(status="pass")

	monkeypatch.setattr(sys.modules["pawpal_system"], "validate_schedule_candidate", flaky_validator)

	schedule = app.run_daily_planning(owner.owner_id, today)
	key = (owner.owner_id, today)

	assert schedule.items
	assert len(app.planning_telemetry_by_owner_date[key]) == 2
	assert all(not telemetry.used_deterministic_fallback for telemetry in app.planning_telemetry_by_owner_date[key])
	assert any("retry scheduled" in entry.lower() for entry in app.planning_logs_by_owner_date[key])
	assert any("passed validation" in entry.lower() for entry in app.planning_logs_by_owner_date[key])
	assert app.planning_loop_diagnostics_by_owner_date[key][0].validation_status == "fail"


def test_phase8_self_check_triggers_deterministic_fallback(monkeypatch):
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Fallback walk",
			category=TaskCategory.WALKING,
			duration_min=20,
			priority=3,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
		),
	)

	def always_fail_validator(*_args, **_kwargs):
		result = ValidationResult(status="fail")
		result.add_violation(
			ValidationViolation(
				code="UNRECOVERABLE_PHASE8_FAILURE",
				message="Synthetic critical failure.",
				severity=ViolationSeverity.CRITICAL,
				repair_hint="Do not retry.",
			)
		)
		return result

	monkeypatch.setattr(sys.modules["pawpal_system"], "validate_schedule_candidate", always_fail_validator)

	schedule = app.run_daily_planning(owner.owner_id, today)
	key = (owner.owner_id, today)

	assert schedule.items
	assert len(app.planning_telemetry_by_owner_date[key]) == 1
	assert app.planning_telemetry_by_owner_date[key][0].used_deterministic_fallback is True
	assert app.planning_telemetry_by_owner_date[key][0].fallback_reason == "stop_condition_triggered"
	assert any("deterministic fallback triggered" in entry.lower() for entry in app.planning_logs_by_owner_date[key])


def test_phase8_explanation_groundedness_requires_supported_claims_and_all_attributions():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	owner.preference = OwnerPreference(
		max_tasks_per_block=2,
		preferred_task_order="feeding, walk, play",
		avoid_late_night=True,
		notification_lead_min=15,
	)

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
	context = app._build_planning_context(owner.owner_id, owner, today)
	agent = DeterministicExplanationAgent()
	retrieved_snippets = app._retrieve_context_snippets(
		owner=owner,
		schedule_date=today,
		query="hard constraints source of truth fallback breakfast",
		top_k=3,
	)

	assert len(retrieved_snippets) >= 2
	good_message = (
		f"Retrieved context for {today.isoformat()} supports the plan. Sources: "
		+ "; ".join(f"[{snippet.attribution}] {snippet.content}" for snippet in retrieved_snippets)
		+ "."
	)
	good = PlanExplanation(
		message=good_message,
		rule_applied="phase6_retrieved_context",
		impact_score=0.95,
	)
	assert agent._passes_groundedness_guardrails(
		good,
		schedule=schedule,
		context=context,
		retrieved_snippets=retrieved_snippets,
	)

	bad = PlanExplanation(
		message=(
			f"Retrieved context for {today.isoformat()} is the best schedule ever. Sources: "
			f"[{retrieved_snippets[0].attribution}] {retrieved_snippets[0].content}."
		),
		rule_applied="phase6_retrieved_context",
		impact_score=0.95,
	)
	assert agent._passes_groundedness_guardrails(
		bad,
		schedule=schedule,
		context=context,
		retrieved_snippets=retrieved_snippets,
	) is False


def test_phase8_rag_retrieval_preserves_relevance_and_attribution():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)
	owner.preference = OwnerPreference(
		max_tasks_per_block=2,
		preferred_task_order="breakfast, walk",
		avoid_late_night=False,
		notification_lead_min=15,
	)

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
	candidate, baseline_schedule, _duration_ms = app._run_scheduler_agent_wrapper(context)
	retrieved_snippets = app._retrieve_context_snippets(
		owner=owner,
		schedule_date=today,
		query="Breakfast preferred task order hard constraints",
		top_k=3,
	)
	agent = DeterministicExplanationAgent()
	explanations = agent.expand_explanations(
		context=context,
		candidate=candidate,
		schedule=baseline_schedule,
		retrieved_snippets=retrieved_snippets,
	)
	retrieved_context_explanations = [explanation for explanation in explanations if explanation.rule_applied == "phase6_retrieved_context"]

	assert retrieved_snippets
	assert retrieved_snippets[0].source_type in {"owner_preference", "routine", "policy"}
	assert "Breakfast" in retrieved_snippets[0].content or "preferred_task_order" in retrieved_snippets[0].content
	assert any(snippet.attribution.startswith("policy:") for snippet in retrieved_snippets)
	assert retrieved_context_explanations
	assert all(snippet.attribution in retrieved_context_explanations[0].message for snippet in retrieved_snippets)


def test_phase8_same_inputs_produce_same_schedule_projection():
	def _build_projection(app: PetCareApp):
		owner, pet, today = _build_owner_with_pet(app)
		owner.preference = OwnerPreference(
			max_tasks_per_block=2,
			preferred_task_order="feeding, walk, play",
			avoid_late_night=True,
			notification_lead_min=15,
		)
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
		owner.add_task(
			pet.pet_id,
			CareTask(
				title="Morning walk",
				category=TaskCategory.WALKING,
				duration_min=30,
				priority=2,
				frequency=Frequency.DAILY,
				earliest_start=time(hour=8, minute=30),
				latest_end=time(hour=10, minute=0),
				is_flexible=True,
			),
		)
		schedule = app.run_daily_planning(owner.owner_id, today)
		return {
			"items": [
				(
					item.task.title if item.task else None,
					item.start_time,
					item.end_time,
					item.reason_code,
					item.completed,
				)
				for item in schedule.items
			],
			"explanations": [(explanation.rule_applied, explanation.message) for explanation in schedule.explanations],
			"metadata": {
				key: schedule.planning_metadata.get(key)
				for key in (
					"strategy",
					"ordering_policy",
					"scheduled_count",
					"unscheduled_count",
					"reason_codes",
					"retrieval_hint_count",
					"phase5_repair_strategy",
					"phase5_repair_detail",
				)
			},
		}

	projection_one = _build_projection(PetCareApp())
	projection_two = _build_projection(PetCareApp())

	assert projection_one == projection_two


def test_phase8_ui_smoke_helpers_render_guardrails_explanations_and_warnings(monkeypatch):
	app_module, fake_streamlit = _load_app_module_with_fake_streamlit(monkeypatch)
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

	# Exact duplicate of "Breakfast" triggers DUPLICATE_TASK (non-repairable).
	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(
			owner.owner_id,
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

	fake_streamlit.calls.clear()
	app_module._show_task_guardrail_feedback(exc_info.value)
	assert any(name == "error" and "validation guardrails failed" in args[0].lower() for name, args, _kwargs in fake_streamlit.calls)
	assert any(name == "write" and "DUPLICATE_TASK" in args[0] for name, args, _kwargs in fake_streamlit.calls if args)
	assert any(name == "info" and args[0] == "Suggested fixes:" for name, args, _kwargs in fake_streamlit.calls)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert app_module._build_plan_explanation_lines(schedule)
	assert all(line.startswith("- ") for line in app_module._build_plan_explanation_lines(schedule))

	conflict_start = datetime.combine(today, time(hour=9, minute=0))
	conflict_end = datetime.combine(today, time(hour=9, minute=30))
	conflict_schedule = DailySchedule(
		date=today,
		items=[
			ScheduleItem(
				start_time=conflict_start,
				end_time=conflict_end,
				reason_code="TEST_CONFLICT_ONE",
				task=CareTask(title="One", category=TaskCategory.FEEDING, duration_min=30, priority=2),
			),
			ScheduleItem(
				start_time=datetime.combine(today, time(hour=9, minute=15)),
				end_time=datetime.combine(today, time(hour=9, minute=45)),
				reason_code="TEST_CONFLICT_TWO",
				task=CareTask(title="Two", category=TaskCategory.WALKING, duration_min=30, priority=1),
			),
		],
	)
	conflicts = app_module._get_schedule_conflicts(conflict_schedule)
	warning_messages = app_module._build_schedule_warning_messages(conflict_schedule, conflicts=conflicts)
	assert warning_messages
	assert warning_messages[0].startswith("Detected 1 schedule conflict(s)")

	empty_schedule = DailySchedule(
		date=today,
		explanations=[
			PlanExplanation(
				message="No availability is configured for the selected day.",
				rule_applied="availability_required",
				impact_score=1.0,
			)
		],
	)
	assert app_module._build_schedule_warning_messages(empty_schedule) == [
		"No availability is configured for the selected day. Add an availability window for that weekday and try again."
	]
