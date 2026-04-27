from datetime import date, time

from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	Frequency,
	Pet,
	PetCareApp,
	PlanExplanation,
	TaskCategory,
)


def _build_owner_with_day_window(app: PetCareApp):
	owner = app.create_owner_profile()
	today = date.today()
	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(hour=6, minute=0),
			end_time=time(hour=22, minute=0),
		)
	)
	pet = Pet(name="Nori", species="Dog", age_years=4, weight_kg=19.0)
	app.save_pet_info(owner.owner_id, pet)
	return owner, pet, today


# Verifies phase-4 explanation expansion runs after schedule generation and keeps list model compatibility.
def test_phase4_explanation_agent_preserves_planexplanation_list_contract():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app)

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
	assert schedule.explanations
	assert all(isinstance(explanation, PlanExplanation) for explanation in schedule.explanations)
	assert any(explanation.rule_applied.startswith("phase4_") for explanation in schedule.explanations)


# Verifies grounded explanations include concrete feasibility facts for chosen times.
def test_phase4_item_explanations_include_feasibility_reasoning():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Morning walk",
			category=TaskCategory.WALKING,
			duration_min=30,
			priority=2,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=7, minute=0),
			latest_end=time(hour=10, minute=0),
			is_flexible=False,
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	grounded_items = [
		explanation
		for explanation in schedule.explanations
		if explanation.rule_applied == "phase4_grounded_item"
	]
	assert grounded_items
	for explanation in grounded_items:
		assert "Feasible because" in explanation.message
		assert "reason_code=" in explanation.message
		assert "priority=" in explanation.message
		assert "flexible=" in explanation.message


# Verifies conflict/deferral facts are grounded in final schedule state metrics.
def test_phase4_conflict_and_deferral_explanation_is_state_grounded():
	app = PetCareApp()
	owner, pet, today = _build_owner_with_day_window(app)

	owner.add_task(
		pet.pet_id,
		CareTask(
			title="Vet check",
			category=TaskCategory.VET,
			duration_min=45,
			priority=4,
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=10, minute=0),
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
			frequency=Frequency.DAILY,
			earliest_start=time(hour=8, minute=0),
			latest_end=time(hour=9, minute=0),
			is_flexible=True,
		),
	)

	schedule = app.run_daily_planning(owner.owner_id, today)
	facts = [
		explanation.message
		for explanation in schedule.explanations
		if explanation.rule_applied == "phase4_conflict_and_deferral_facts"
	]
	assert facts
	assert "overlap(s) detected" in facts[0]
	assert "deferral" in facts[0]
