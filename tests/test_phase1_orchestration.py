from datetime import date, time

import pawpal_system

from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	Pet,
	PetCareApp,
	TaskCategory,
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


# Verifies orchestration retries after a failed validation and logs each loop iteration.
def test_orchestrator_retry_path_executes_and_logs(monkeypatch):
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Retryable task",
			category=TaskCategory.FEEDING,
			duration_min=15,
			priority=2,
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
					code="RETRYABLE_TEST_FAILURE",
					message="Synthetic retryable failure",
					severity=ViolationSeverity.MEDIUM,
					repair_hint="Try again",
				)
			)
			return result
		return ValidationResult(status="pass")

	monkeypatch.setattr(pawpal_system, "validate_schedule_candidate", flaky_validator)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule.items

	key = (owner.owner_id, today)
	telemetry = app.planning_telemetry_by_owner_date[key]
	logs = app.planning_logs_by_owner_date[key]

	assert len(telemetry) == 2
	assert telemetry[0].used_deterministic_fallback is False
	assert telemetry[1].used_deterministic_fallback is False
	assert any("retry scheduled" in entry.lower() for entry in logs)
	assert any("passed validation" in entry.lower() for entry in logs)


# Verifies deterministic fallback path executes and is captured in telemetry/logs.
def test_orchestrator_fallback_path_executes_and_logs(monkeypatch):
	app = PetCareApp()
	owner, pet, today = _build_owner_with_pet(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Fallback task",
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
				code="CRITICAL_TEST_FAILURE",
				message="Synthetic critical failure",
				severity=ViolationSeverity.CRITICAL,
				repair_hint="Do not retry",
			)
		)
		return result

	monkeypatch.setattr(pawpal_system, "validate_schedule_candidate", always_fail_validator)

	schedule = app.run_daily_planning(owner.owner_id, today)
	assert schedule is not None

	key = (owner.owner_id, today)
	telemetry = app.planning_telemetry_by_owner_date[key]
	logs = app.planning_logs_by_owner_date[key]

	assert len(telemetry) == 1
	assert telemetry[0].used_deterministic_fallback is True
	assert telemetry[0].fallback_reason == "stop_condition_triggered"
	assert any("fallback triggered" in entry.lower() for entry in logs)
