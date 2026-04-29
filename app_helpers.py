from __future__ import annotations

from datetime import time

import streamlit as st

from pawpal_system import CareTask, Frequency, TaskValidationError


def pet_option_label(pet_id, pet_by_id):
	"""Return a readable dropdown label for pet selection options."""
	if pet_id is None:
		return "Select a pet"
	pet = pet_by_id.get(pet_id)
	if pet is None:
		return "Unknown pet"
	return f"{pet.name or 'Unnamed'} ({pet.species or 'unknown'})"


def show_task_guardrail_feedback(error: TaskValidationError) -> None:
	"""Render task validation violations and repair hints in a compact UI block."""
	st.error("Task was not saved because validation guardrails failed.")
	for line in build_task_guardrail_feedback_lines(error):
		st.write(line)
	retrieval_hints = [
		h for h in error.result.repair_hints
		if h.startswith("Normalization suggestion from retrieval:")
		or h.startswith("Retrieved correction hint from routine:")
	]
	if retrieval_hints:
		st.info("Suggested fixes:")
		for hint in retrieval_hints:
			st.write(f"- {hint}")


def build_task_guardrail_feedback_lines(error: TaskValidationError) -> list[str]:
	"""Return the violation lines shown in the task guardrail UI."""
	return [f"- {violation.code}: {violation.message}" for violation in error.result.violations]


def build_schedule_warning_messages(schedule, conflicts=None) -> list[str]:
	"""Return warning text for schedule generation and conflict displays."""
	warnings: list[str] = []
	if conflicts:
		warnings.append(
			f"Detected {len(conflicts)} schedule conflict(s). Focus on moving flexible tasks first to reduce overlap."
		)

	if getattr(schedule, "items", None):
		return warnings

	has_no_day_availability = any(
		explanation.rule_applied == "availability_required"
		for explanation in getattr(schedule, "explanations", [])
	)
	if has_no_day_availability:
		warnings.append(
			"No availability is configured for the selected day. Add an availability window for that weekday and try again."
		)
	else:
		warnings.append("No tasks could be scheduled. Check pet tasks and owner availability.")
	return warnings


def build_plan_explanation_lines(schedule) -> list[str]:
	"""Return display-ready explanation lines for the plan summary."""
	return [f"- {explanation.message}" for explanation in getattr(schedule, "explanations", [])]


def filter_task_pairs_for_display(task_pairs, scheduler_service, pet_id=None, flexible_only=None):
	"""Use scheduler helper when available; otherwise apply local fallback filtering."""
	if hasattr(scheduler_service, "filter_task_pairs_for_display"):
		return scheduler_service.filter_task_pairs_for_display(
			task_pairs,
			pet_id=pet_id,
			flexible_only=flexible_only,
		)

	filtered = task_pairs
	if pet_id is not None:
		filtered = [(pet, task) for pet, task in filtered if pet.pet_id == pet_id]
	if flexible_only is None:
		return filtered
	return [(pet, task) for pet, task in filtered if task.is_flexible == flexible_only]


def sort_task_pairs_for_display(task_pairs, scheduler_service):
	"""Use scheduler helper when available; otherwise apply local fallback sorting."""
	if hasattr(scheduler_service, "sort_task_pairs_for_display"):
		return scheduler_service.sort_task_pairs_for_display(task_pairs)

	def _task_display_sort_key(task: CareTask) -> tuple[int, time, int, str]:
		start = task.earliest_start if task.earliest_start is not None else time(hour=23, minute=59)
		has_no_start = 1 if task.earliest_start is None else 0
		return (has_no_start, start, -task.priority, task.title.lower())

	return sorted(task_pairs, key=lambda pair: _task_display_sort_key(pair[1]))


def sort_schedule_items_for_display(items, scheduler_service):
	"""Use scheduler helper when available; otherwise apply local fallback sorting."""
	if hasattr(scheduler_service, "sort_schedule_items_for_display"):
		return scheduler_service.sort_schedule_items_for_display(items)
	return sorted(items, key=lambda item: item.start_time or time(hour=23, minute=59))


def get_schedule_conflicts(schedule, scheduler_service):
	"""Use scheduler helper when available; otherwise apply local overlap detection."""
	if hasattr(scheduler_service, "get_schedule_conflicts"):
		return scheduler_service.get_schedule_conflicts(schedule)

	sorted_items = sorted(
		[item for item in schedule.items if item.start_time is not None and item.end_time is not None],
		key=lambda schedule_item: schedule_item.start_time,
	)
	conflicts = []
	for previous_item, current_item in zip(sorted_items, sorted_items[1:]):
		if previous_item.end_time > current_item.start_time:
			conflicts.append((previous_item, current_item))
	return conflicts