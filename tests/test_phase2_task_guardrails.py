from datetime import time

import pytest

from pawpal_system import (
	CareTask,
	Frequency,
	Pet,
	PetCareApp,
	TaskCategory,
	TaskValidationError,
)


def _build_owner_with_pet(app: PetCareApp):
	owner = app.create_owner_profile()
	pet = Pet(name="Mochi", species="Dog", age_years=3, weight_kg=12.0)
	app.save_pet_info(owner.owner_id, pet)
	return owner, pet


def test_add_task_rejects_non_positive_duration_and_returns_repair_hint():
	app = PetCareApp()
	owner, pet = _build_owner_with_pet(app)

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

	assert len(pet.tasks) == 0
	assert any(v.code == "INVALID_DURATION" for v in exc_info.value.result.violations)
	assert any("duration_min" in hint for hint in exc_info.value.result.repair_hints)


def test_add_task_rejects_invalid_time_window_and_suggests_nearest_end_time():
	app = PetCareApp()
	owner, pet = _build_owner_with_pet(app)

	invalid_task = CareTask(
		title="Backward window",
		category=TaskCategory.FEEDING,
		duration_min=20,
		priority=2,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=12, minute=0),
		latest_end=time(hour=11, minute=45),
	)

	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(owner.owner_id, pet.pet_id, invalid_task)

	assert len(pet.tasks) == 0
	assert any(v.code == "INVALID_TIME_WINDOW" for v in exc_info.value.result.violations)
	assert any("Set latest_end to" in hint for hint in exc_info.value.result.repair_hints)


def test_add_task_rejects_incoherent_custom_recurrence():
	app = PetCareApp()
	owner, pet = _build_owner_with_pet(app)

	invalid_task = CareTask(
		title="Mixed recurrence",
		category=TaskCategory.PLAY,
		duration_min=30,
		priority=1,
		frequency=Frequency.CUSTOM,
		custom_days_of_week=[1, 3],
		custom_interval_days=2,
		earliest_start=time(hour=15, minute=0),
		latest_end=time(hour=16, minute=0),
	)

	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(owner.owner_id, pet.pet_id, invalid_task)

	assert len(pet.tasks) == 0
	assert any(v.code == "INCOHERENT_RECURRENCE_CUSTOM_MODE" for v in exc_info.value.result.violations)
	assert any("Choose one mode" in hint for hint in exc_info.value.result.repair_hints)


def test_add_task_rejects_duplicate_and_suggests_merge():
	app = PetCareApp()
	owner, pet = _build_owner_with_pet(app)

	first_task = CareTask(
		title="Evening Walk",
		category=TaskCategory.WALKING,
		duration_min=25,
		priority=3,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=18, minute=0),
		latest_end=time(hour=19, minute=0),
	)
	app.add_task(owner.owner_id, pet.pet_id, first_task)

	duplicate_task = CareTask(
		title="Evening Walk",
		category=TaskCategory.WALKING,
		duration_min=25,
		priority=1,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=18, minute=0),
		latest_end=time(hour=19, minute=0),
	)

	with pytest.raises(TaskValidationError) as exc_info:
		app.add_task(owner.owner_id, pet.pet_id, duplicate_task)

	assert len(pet.tasks) == 1
	assert any(v.code == "DUPLICATE_TASK" for v in exc_info.value.result.violations)
	assert any("Merge with existing task" in hint for hint in exc_info.value.result.repair_hints)


def test_edit_task_rejects_invalid_update_and_keeps_original_values():
	app = PetCareApp()
	owner, pet = _build_owner_with_pet(app)

	task = CareTask(
		title="Morning Medication",
		category=TaskCategory.MEDICATION,
		duration_min=10,
		priority=3,
		frequency=Frequency.DAILY,
		earliest_start=time(hour=8, minute=0),
		latest_end=time(hour=9, minute=0),
	)
	app.add_task(owner.owner_id, pet.pet_id, task)

	with pytest.raises(TaskValidationError) as exc_info:
		app.edit_task(
			owner.owner_id,
			task.task_id,
			duration_min=15,
			earliest_start=time(hour=10, minute=0),
			latest_end=time(hour=9, minute=30),
		)

	assert any(v.code == "INVALID_TIME_WINDOW" for v in exc_info.value.result.violations)

	persisted_task = pet.tasks[0]
	assert persisted_task.duration_min == 10
	assert persisted_task.earliest_start == time(hour=8, minute=0)
	assert persisted_task.latest_end == time(hour=9, minute=0)
