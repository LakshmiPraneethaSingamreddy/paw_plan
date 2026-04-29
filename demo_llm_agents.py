"""
Demo: LLM explanation enhancement in PawPal+

This script shows how the deterministic scheduler generates a schedule and
the LLMExplanationAgent rewrites the technical notes into friendly language.

Before running:
  export OPENAI_API_KEY="sk-your-key"
  (or set it in your .env file)

Optional:
  export LLM_EXPLANATION_MODEL="gpt-4o-mini"
  export LLM_MAX_TOKENS="1500"
"""

from datetime import date, time
from pawpal_system import (
	AvailabilityWindow,
	CareTask,
	Pet,
	PetCareApp,
	TaskCategory,
	OwnerPreference,
)


def build_demo_data(app: PetCareApp):
	"""Create a sample owner, pets, and tasks."""
	owner = app.create_owner_profile()
	owner.name = "Jordan"
	owner.timezone = "US/Eastern"

	today = date.today()
	owner.preference = OwnerPreference(
		max_tasks_per_block=3,
		preferred_task_order="feeding, walk, play",
		avoid_late_night=False,
		notification_lead_min=15,
	)

	owner.availability_windows.append(
		AvailabilityWindow(
			day_of_week=today.weekday(),
			start_time=time(hour=7, minute=0),
			end_time=time(hour=21, minute=0),
		)
	)

	buddy = Pet(name="Buddy", species="Dog", age_years=5, weight_kg=25.0)
	luna = Pet(name="Luna", species="Cat", age_years=3, weight_kg=4.5)
	app.save_pet_info(owner.owner_id, buddy)
	app.save_pet_info(owner.owner_id, luna)

	owner.add_task(buddy.pet_id, CareTask(
		title="Morning walk", category=TaskCategory.WALKING,
		duration_min=30, priority=4,
		earliest_start=time(7, 0), latest_end=time(9, 0), is_flexible=False,
	))
	owner.add_task(buddy.pet_id, CareTask(
		title="Breakfast", category=TaskCategory.FEEDING,
		duration_min=15, priority=5,
		earliest_start=time(8, 0), latest_end=time(9, 30), is_flexible=False,
	))
	owner.add_task(buddy.pet_id, CareTask(
		title="Playtime", category=TaskCategory.PLAY,
		duration_min=45, priority=2,
		earliest_start=time(11, 0), latest_end=time(15, 0), is_flexible=True,
	))
	owner.add_task(buddy.pet_id, CareTask(
		title="Evening walk", category=TaskCategory.WALKING,
		duration_min=25, priority=3,
		earliest_start=time(18, 0), latest_end=time(20, 0), is_flexible=False,
	))
	owner.add_task(luna.pet_id, CareTask(
		title="Breakfast", category=TaskCategory.FEEDING,
		duration_min=10, priority=5,
		earliest_start=time(7, 30), latest_end=time(9, 0), is_flexible=False,
	))
	owner.add_task(luna.pet_id, CareTask(
		title="Play session", category=TaskCategory.PLAY,
		duration_min=20, priority=2,
		earliest_start=time(12, 0), latest_end=time(15, 0), is_flexible=True,
	))
	owner.add_task(luna.pet_id, CareTask(
		title="Dinner", category=TaskCategory.FEEDING,
		duration_min=10, priority=4,
		earliest_start=time(18, 0), latest_end=time(20, 0), is_flexible=False,
	))

	return owner, today


def print_schedule(schedule, title: str = "Schedule"):
	print(f"\n{'=' * 60}")
	print(f"{title.center(60)}")
	print(f"{'=' * 60}")
	print(f"Date: {schedule.date.isoformat()}")
	print(f"Total planned: {schedule.total_planned_min} minutes")
	print("-" * 60)

	for item in schedule.items:
		task_name = item.task.title if item.task else "Unknown"
		start = item.start_time.strftime("%H:%M") if item.start_time else "N/A"
		end = item.end_time.strftime("%H:%M") if item.end_time else "N/A"
		reason = item.reason_code or "NO_REASON"
		print(f"{start:5s}-{end:5s} | {task_name:20s} | {reason:30s}")

	print("-" * 60)
	print("\nRaw explanations (deterministic):")
	for explanation in schedule.explanations[:5]:
		if explanation.message:
			print(f"  • {explanation.message[:80]}...")


def main():
	print("\n" + "=" * 60)
	print("PawPal+ LLM Explanation Enhancement Demo".center(60))
	print("=" * 60)
	print("\nScheduling is always deterministic.")
	print("The LLM rewrites the technical notes into friendly language.\n")

	app = PetCareApp()
	owner, today = build_demo_data(app)
	app.save_owner_info(owner)

	print(f"Owner: {owner.name}  |  Pets: {', '.join(p.name for p in owner.pets)}")
	print(f"Tasks: {sum(len(p.tasks) for p in owner.pets)}  |  Date: {today.isoformat()}")

	# Step 1 — deterministic schedule
	print("\n" + "=" * 60)
	print("STEP 1: Generate schedule (deterministic)".center(60))
	print("=" * 60)
	schedule = app.run_daily_planning(owner.owner_id, today)
	print_schedule(schedule, "Schedule")

	# Step 2 — AI explanation enhancement
	print("\n" + "=" * 60)
	print("STEP 2: Enhance explanations with AI".center(60))
	print("=" * 60)

	from llm_agents import LLMExplanationAgent
	agent = LLMExplanationAgent()

	if not agent.is_available():
		print("⚠  LLM client not available — set OPENAI_API_KEY to see the enhancement.")
		return

	raw_lines = [explanation.message for explanation in schedule.explanations if explanation.message]
	enhanced = agent.enhance_explanations_text(raw_lines)

	if enhanced:
		print("\nAI-enhanced explanation:")
		print("-" * 60)
		print(enhanced)
		print("-" * 60)
	else:
		print("⚠  AI call failed. Check your API key and model name.")

	print("\n" + "=" * 60)
	print("Demo complete!".center(60))
	print("=" * 60)


if __name__ == "__main__":
	main()
