from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from enum import Enum
import re
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4


class TaskCategory(Enum):
	"""Categories of pet care tasks.
	
	Attributes:
		FEEDING: Task for feeding the pet.
		WALKING: Task for walking the pet.
		MEDICATION: Task for administering medication.
		GROOMING: Task for grooming the pet.
		PLAY: Task for playing with the pet.
		VET: Task for veterinary appointments.
	"""
	FEEDING = "Feeding"
	WALKING = "Walking"
	MEDICATION = "Medication"
	GROOMING = "Grooming"
	PLAY = "Play"
	VET = "Vet"


class Frequency(Enum):
	"""Frequency options for recurring pet care tasks.
	
	Attributes:
		DAILY: Task occurs daily.
		WEEKLY: Task occurs weekly.
		CUSTOM: Task occurs on a custom schedule.
	"""
	DAILY = "Daily"
	WEEKLY = "Weekly"
	CUSTOM = "Custom"


class ConstraintType(Enum):
	"""Types of scheduling constraints for pet care tasks.
	
	Attributes:
		TIME_AVAILABILITY: Constraint on time windows when tasks can occur.
		PRIORITY: Constraint on task priority levels.
		PREFERENCE: Constraint on task flexibility or duration preferences.
		SPACING: Constraint on spacing between tasks.
		DEADLINE: Constraint on when tasks must be completed by.
	"""
	TIME_AVAILABILITY = "TimeAvailability"
	PRIORITY = "Priority"
	PREFERENCE = "Preference"
	SPACING = "Spacing"
	DEADLINE = "Deadline"


class ScheduleStatus(Enum):
	"""Status states for a daily pet care schedule.
	
	Attributes:
		DRAFT: Schedule is in draft state, not yet finalized.
		FINAL: Schedule has been finalized and locked.
		UPDATED: Schedule was previously final but has been updated.
	"""
	DRAFT = "Draft"
	FINAL = "Final"
	UPDATED = "Updated"


class AgentRole(Enum):
	"""Roles used by the multi-agent planning architecture."""
	SCHEDULER = "SchedulerAgent"
	EXPLANATION = "ExplanationAgent"
	TASK_MANAGEMENT = "TaskManagementAgent"


class ViolationSeverity(Enum):
	"""Severity levels for validation violations."""
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"


# Phase 0 architecture contract: each role has one clear boundary.
AGENT_ROLE_RESPONSIBILITIES: dict[AgentRole, tuple[str, ...]] = {
	AgentRole.SCHEDULER: (
		"Proposes a schedule candidate for the requested day.",
		"Does not mutate owner/task persistence state.",
	),
	AgentRole.EXPLANATION: (
		"Explains why the candidate is valid and preferred.",
		"References constraints, ordering, and tradeoffs used in planning.",
	),
	AgentRole.TASK_MANAGEMENT: (
		"Validates pet/task payloads before persistence.",
		"Repairs malformed payloads using deterministic repair hints.",
	),
}

# Non-negotiable guardrails for all planning outcomes.
HARD_CONSTRAINT_RULES: tuple[str, ...] = (
	"No overlap in final schedule.",
	"Non-flexible tasks must satisfy earliest_start/latest_end windows.",
	"Owner availability windows must be honored.",
	"Use bounded retries, then deterministic fallback.",
)

# Deterministic policy baseline for all agentized scheduling flows.
AGENT_RETRY_BUDGET = 2
DETERMINISTIC_FALLBACK_POLICY = (
	"Retry each agent invocation up to AGENT_RETRY_BUDGET times. "
	"If validation still fails, bypass advisory candidate and return the schedule "
	"from SchedulerService.generate_daily_schedule as the final authority."
)

# Source of truth contract: existing scheduler remains authoritative.
SCHEDULE_SOURCE_OF_TRUTH = "SchedulerService.generate_daily_schedule"
AGENT_OUTPUTS_ADVISORY_ONLY = True


@dataclass
class PlanExplanation:
	"""Explanation for a scheduling decision in the pet care plan.
	
	Provides reasoning and impact information for how tasks are scheduled.
	
	Attributes:
		explanation_id: Unique identifier for this explanation.
		message: Human-readable explanation of the scheduling decision.
		rule_applied: Name of the rule or constraint that was applied.
		impact_score: Score quantifying the impact of this decision (0.0 to 1.0).
	"""
	explanation_id: UUID = field(default_factory=uuid4)
	message: str = ""
	rule_applied: str = ""
	impact_score: float = 0.0


@dataclass
class CareTask:
	"""A pet care task that needs to be scheduled.
	
	Represents a specific activity that must be performed for a pet, with
	constraints on timing, duration, and flexibility.
	
	Attributes:
		task_id: Unique identifier for this task.
		title: Name/description of the task.
		category: Category of pet care (Feeding, Walking, etc.).
		duration_min: Expected duration of the task in minutes.
		priority: Priority level (higher values = higher priority).
		frequency: How often this task recurs (Daily, Weekly, Custom).
		earliest_start: Earliest time the task can start on a given day.
		latest_end: Latest time the task must be completed by.
		is_flexible: Whether the task can be moved/rescheduled (True) or is rigid.
		notes: Additional notes or instructions for this task.
	"""
	task_id: UUID = field(default_factory=uuid4)
	title: str = ""
	category: TaskCategory = TaskCategory.FEEDING
	duration_min: int = 0
	priority: int = 0
	frequency: Frequency = Frequency.DAILY
	created_on: date = field(default_factory=date.today)
	weekly_day_of_week: int | None = None
	custom_days_of_week: list[int] = field(default_factory=list)
	custom_interval_days: int | None = None
	custom_anchor_date: date | None = None
	earliest_start: time | None = None
	latest_end: time | None = None
	is_flexible: bool = True
	notes: str = ""


@dataclass
class Pet:
	"""A pet that requires care and scheduling.
	
	Stores information about a pet and tracks all care tasks associated with it.
	
	Attributes:
		pet_id: Unique identifier for this pet.
		name: The pet's name.
		species: Species of the pet (dog, cat, bird, etc.).
		age_years: Age of the pet in years.
		height_cm: Height of the pet in centimeters.
		weight_kg: Weight of the pet in kilograms.
		tasks: List of care tasks assigned to this pet.
	"""
	pet_id: UUID = field(default_factory=uuid4)
	name: str = ""
	species: str = ""
	age_years: int = 0
	height_cm: float = 0.0
	weight_kg: float = 0.0
	tasks: list[CareTask] = field(default_factory=list)


@dataclass
class OwnerPreference:
	"""Pet owner's preferences for task scheduling.
	
	Defines how an owner likes their pet care schedule organized and displayed.
	
	Attributes:
		preference_id: Unique identifier for this preference set.
		max_tasks_per_block: Maximum number of tasks to schedule in one time block.
		preferred_task_order: Preferred order for tasks (e.g., "feeding, play, medication").
		avoid_late_night: If True, don't schedule tasks after 10 PM.
		notification_lead_min: Minutes before a task to send a notification reminder.
	"""
	preference_id: UUID = field(default_factory=uuid4)
	max_tasks_per_block: int = 0
	preferred_task_order: str = ""
	avoid_late_night: bool = False
	notification_lead_min: int = 0


@dataclass
class AvailabilityWindow:
	"""A time window when the owner is available for pet care tasks.
	
	Defines recurring availability windows throughout the week.
	
	Attributes:
		window_id: Unique identifier for this availability window.
		day_of_week: Day of week (0=Monday, 6=Sunday).
		start_time: Time when availability starts on this day.
		end_time: Time when availability ends on this day.
	"""
	window_id: UUID = field(default_factory=uuid4)
	day_of_week: int = 0
	start_time: time | None = None
	end_time: time | None = None


@dataclass
class ScheduleItem:
	"""A single item in a daily schedule representing a scheduled task.
	
	Represents a specific time-boxed instance of a care task on a particular day.
	
	Attributes:
		item_id: Unique identifier for this schedule item.
		start_time: When this task is scheduled to start.
		end_time: When this task is scheduled to end.
		reason_code: Code indicating why this task was scheduled at this time.
		locked: If True, this item cannot be moved/rescheduled.
		task: Reference to the CareTask definition.
		pet_id: ID of the pet this task is for.
		completed: Whether this task has been completed.
		completed_at: Timestamp when this task was completed (if applicable).
	"""
	item_id: UUID = field(default_factory=uuid4)
	start_time: datetime | None = None
	end_time: datetime | None = None
	reason_code: str = ""
	locked: bool = False
	task: CareTask | None = None
	pet_id: UUID | None = None
	completed: bool = False
	completed_at: datetime | None = None

	def mark_completed(self, when: datetime | None = None) -> None:
		"""Mark this schedule item as completed.
		
		Args:
			when: Timestamp of completion. Defaults to current UTC time if not provided.
		"""
		self.completed = True
		self.completed_at = when or datetime.utcnow()

	def mark_incomplete(self) -> None:
		"""Mark this schedule item as not completed."""
		self.completed = False
		self.completed_at = None


@dataclass
class ScheduleCandidate:
	"""Advisory schedule output produced by the Scheduler Agent.

	This candidate is never considered final until it passes validation.
	"""
	candidate_id: UUID = field(default_factory=uuid4)
	proposed_items: list[ScheduleItem] = field(default_factory=list)
	objective_score: float = 0.0
	rationale_summary: str = ""
	rationale_metadata: dict[str, Any] = field(default_factory=dict)
	planning_summary_metadata: dict[str, Any] = field(default_factory=dict)
	reason_codes: tuple[str, ...] = ()
	generated_by: AgentRole = AgentRole.SCHEDULER
	advisory_only: bool = True


@dataclass
class ValidationViolation:
	"""Single guardrail violation discovered during validation."""
	code: str = ""
	message: str = ""
	severity: ViolationSeverity = ViolationSeverity.MEDIUM
	repair_hint: str = ""


@dataclass
class ValidationResult:
	"""Validation output for agent-produced payloads and schedule candidates."""
	status: Literal["pass", "fail"] = "pass"
	violations: list[ValidationViolation] = field(default_factory=list)
	repair_hints: list[str] = field(default_factory=list)

	def add_violation(self, violation: ValidationViolation) -> None:
		"""Append a violation and flip result status to fail."""
		self.violations.append(violation)
		if violation.repair_hint:
			self.repair_hints.append(violation.repair_hint)
		self.status = "fail"

	@property
	def passed(self) -> bool:
		"""Convenience pass/fail accessor for call sites."""
		return self.status == "pass"


class TaskValidationError(ValueError):
	"""Raised when task payload guardrails fail during add/edit persistence."""

	def __init__(self, result: ValidationResult):
		self.result = result
		messages = "; ".join(violation.message for violation in result.violations) or "Task validation failed."
		suggestions = " | ".join(result.repair_hints)
		combined = messages if not suggestions else f"{messages} Suggestions: {suggestions}"
		super().__init__(combined)


@dataclass
class AgentTelemetry:
	"""Execution telemetry for one agent run."""
	run_id: UUID = field(default_factory=uuid4)
	agent_role: AgentRole = AgentRole.SCHEDULER
	retries: int = 0
	fallback_reason: str = ""
	duration_ms: int = 0
	used_deterministic_fallback: bool = False


@dataclass
class OrchestrationRetryConfig:
	"""Retry policy and stop conditions for planning orchestration."""
	max_retries: int = AGENT_RETRY_BUDGET
	stop_on_severities: tuple[ViolationSeverity, ...] = (ViolationSeverity.CRITICAL,)
	fallback_on_validation_failure: bool = True


@dataclass
class PlanningLoopDiagnostic:
	"""Diagnostics captured for each phase-5 planning loop step."""
	attempt: int = 0
	stage: str = ""
	validation_status: Literal["pass", "fail"] = "pass"
	violation_codes: tuple[str, ...] = ()
	critique_summary: str = ""
	repair_strategy: str = ""
	repaired_validation_status: Literal["pass", "fail"] | None = None
	fallback_used: bool = False
	detail: str = ""


@dataclass
class PlanningContext:
	"""Context assembled once per planning request for agent orchestration."""
	owner_id: UUID
	owner: Owner
	schedule_date: date


@dataclass
class RetrievalSnippet:
	"""A short, attributed snippet returned by the local retrieval layer."""
	snippet_id: UUID = field(default_factory=uuid4)
	source_type: str = ""
	source_label: str = ""
	content: str = ""
	metadata: dict[str, Any] = field(default_factory=dict)
	score: float = 0.0

	@property
	def attribution(self) -> str:
		return f"{self.source_type}:{self.source_label}"


@dataclass
class RetrievalChunk:
	"""A queryable chunk produced from a larger retrieval snippet."""
	chunk_id: UUID = field(default_factory=uuid4)
	chunk_index: int = 0
	chunk_total: int = 0
	snippet: RetrievalSnippet = field(default_factory=RetrievalSnippet)
	content: str = ""

	@property
	def attribution(self) -> str:
		return f"{self.snippet.attribution}#chunk{self.chunk_index + 1}"


class LocalRetrievalCorpus:
	"""Small in-memory corpus used for explanation grounding and advisory hints."""

	TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
	CHUNK_SEPARATOR_PATTERN = re.compile(r"[.;\n]+")
	MIN_RETRIEVAL_SCORE = 1.0

	def __init__(self, snippets: list[RetrievalSnippet] | None = None) -> None:
		self._snippets = snippets or []

	def add(self, snippet: RetrievalSnippet) -> None:
		self._snippets.append(snippet)

	def extend(self, snippets: list[RetrievalSnippet]) -> None:
		self._snippets.extend(snippets)

	def chunk_snippet(self, snippet: RetrievalSnippet) -> list[RetrievalChunk]:
		parts = [part.strip() for part in self.CHUNK_SEPARATOR_PATTERN.split(snippet.content) if part.strip()]
		if not parts:
			parts = [snippet.content.strip()] if snippet.content.strip() else []
		chunk_total = len(parts)
		return [
			RetrievalChunk(
				chunk_index=index,
				chunk_total=chunk_total,
				snippet=snippet,
				content=part,
			)
			for index, part in enumerate(parts)
		]

	def _tokenize(self, text: str) -> set[str]:
		return {match.group(0) for match in self.TOKEN_PATTERN.finditer(text.lower())}

	def _score_chunk(self, query_tokens: set[str], chunk: RetrievalChunk) -> float:
		chunk_tokens = self._tokenize(f"{chunk.snippet.source_type} {chunk.snippet.source_label} {chunk.content}")
		if not chunk_tokens:
			return 0.0
		overlap = len(query_tokens & chunk_tokens)
		score = float(overlap)
		if chunk.snippet.metadata.get("is_recent"):
			score += 0.5
		if chunk.snippet.metadata.get("is_policy"):
			score += 0.25
		return score

	def retrieve(self, query: str, top_k: int = 3) -> list[RetrievalSnippet]:
		query_tokens = self._tokenize(query)
		if not query_tokens or top_k <= 0:
			return []

		scored_snippets: list[RetrievalSnippet] = []
		for snippet in self._snippets:
			for chunk in self.chunk_snippet(snippet):
				score = self._score_chunk(query_tokens, chunk)
				if score < self.MIN_RETRIEVAL_SCORE:
					continue
				scored_snippets.append(
					replace(
						snippet,
						source_label=chunk.attribution,
						content=chunk.content,
						score=score,
					)
				)

		scored_snippets.sort(key=lambda snippet: (-snippet.score, snippet.source_type, snippet.source_label, snippet.content))
		return scored_snippets[:top_k]

	def is_empty(self) -> bool:
		return not self._snippets


def _is_within_availability(item: ScheduleItem, day_windows: list[AvailabilityWindow]) -> bool:
	"""Return whether a scheduled item is fully inside at least one day window."""
	if item.start_time is None or item.end_time is None:
		return False

	for window in day_windows:
		start_t = window.start_time or time(hour=0, minute=0)
		end_t = window.end_time or time(hour=23, minute=59)
		window_start = datetime.combine(item.start_time.date(), start_t)
		window_end = datetime.combine(item.start_time.date(), end_t)
		if item.start_time >= window_start and item.end_time <= window_end:
			return True

	return False


def validate_schedule_candidate(
	candidate: ScheduleCandidate,
	owner: Owner,
	schedule_date: date,
) -> ValidationResult:
	"""Validate advisory schedule candidate against Phase 0 hard constraints."""
	result = ValidationResult()
	day_windows = [
		window
		for window in owner.availability_windows
		if window.day_of_week == schedule_date.weekday()
	]

	items = [
		item
		for item in candidate.proposed_items
		if item.start_time is not None and item.end_time is not None
	]
	items.sort(key=lambda scheduled_item: scheduled_item.start_time)

	for previous_item, current_item in zip(items, items[1:]):
		if previous_item.end_time > current_item.start_time:
			result.add_violation(
				ValidationViolation(
					code="NO_OVERLAP",
					message="Final schedule contains overlapping tasks.",
					severity=ViolationSeverity.CRITICAL,
					repair_hint="Shift or remove lower-priority flexible tasks to remove overlap.",
				)
			)

	for item in items:
		task = item.task
		if task is None:
			result.add_violation(
				ValidationViolation(
					code="MISSING_TASK",
					message="Schedule item is missing task metadata.",
					severity=ViolationSeverity.HIGH,
					repair_hint="Hydrate schedule items with full task references before validation.",
				)
			)
			continue

		if not task.is_flexible:
			if task.earliest_start is not None and item.start_time.time() < task.earliest_start:
				result.add_violation(
					ValidationViolation(
						code="RIGID_START_WINDOW",
						message=f"Non-flexible task '{task.title}' starts before earliest_start.",
						severity=ViolationSeverity.CRITICAL,
						repair_hint="Move rigid task to begin at or after earliest_start.",
					)
				)
			if task.latest_end is not None and item.end_time.time() > task.latest_end:
				result.add_violation(
					ValidationViolation(
						code="RIGID_END_WINDOW",
						message=f"Non-flexible task '{task.title}' ends after latest_end.",
						severity=ViolationSeverity.CRITICAL,
						repair_hint="Move rigid task to end by latest_end or remove conflicting tasks.",
					)
				)

		if not _is_within_availability(item, day_windows):
			result.add_violation(
				ValidationViolation(
					code="OUTSIDE_AVAILABILITY",
					message=f"Task '{task.title}' falls outside owner availability windows.",
					severity=ViolationSeverity.HIGH,
					repair_hint="Reslot task inside configured weekday availability windows.",
				)
			)

	return result


@dataclass
class DailySchedule:
	"""A complete daily schedule for pet care tasks.
	
	Contains all scheduled tasks for a specific date and tracks their
	completion status and scheduling explanations.
	
	Attributes:
		schedule_id: Unique identifier for this schedule.
		date: The date this schedule is for.
		status: Current status of the schedule (Draft, Final, or Updated).
		total_planned_min: Total planned time in minutes for all tasks.
		created_at: Timestamp when this schedule was created.
		items: List of scheduled task items for this day.
		explanations: List of explanations for scheduling decisions.
	"""
	schedule_id: UUID = field(default_factory=uuid4)
	date: date | None = None
	status: ScheduleStatus = ScheduleStatus.DRAFT
	total_planned_min: int = 0
	created_at: datetime = field(default_factory=datetime.utcnow)
	items: list[ScheduleItem] = field(default_factory=list)
	explanations: list[PlanExplanation] = field(default_factory=list)
	planning_metadata: dict[str, Any] = field(default_factory=dict)

	def regenerate(self) -> None:
		"""Rebuild this schedule from current tasks and constraints.
		
		Validates all schedule items, removes conflicts and invalid entries,
		and adjusts non-locked items as needed. Also updates the schedule status
		if it was previously final.
		
		Raises:
			ValueError: If the schedule date is not set.
		"""
		if self.date is None:
			raise ValueError("Schedule date is required to regenerate")

		valid_items: list[ScheduleItem] = []
		invalid_count = 0
		for item in self.items:
			if item.task is None or item.start_time is None or item.end_time is None:
				invalid_count += 1
				continue
			if item.end_time <= item.start_time:
				invalid_count += 1
				continue
			valid_items.append(item)

		valid_items.sort(key=lambda schedule_item: schedule_item.start_time)

		adjusted_count = 0
		for idx in range(1, len(valid_items)):
			previous_item = valid_items[idx - 1]
			current_item = valid_items[idx]
			if current_item.start_time >= previous_item.end_time:
				continue

			if current_item.locked:
				continue

			duration = current_item.end_time - current_item.start_time
			current_item.start_time = previous_item.end_time
			current_item.end_time = current_item.start_time + duration
			adjusted_count += 1

		self.items = valid_items
		self.total_planned_min = sum(
			int((item.end_time - item.start_time).total_seconds() // 60)
			for item in self.items
			if item.start_time is not None and item.end_time is not None
		)

		if self.status in (ScheduleStatus.FINAL, ScheduleStatus.DRAFT):
			self.status = ScheduleStatus.UPDATED

		summary = (
			f"Regenerated schedule: kept {len(self.items)} items, "
			f"removed {invalid_count} invalid items, adjusted {adjusted_count} overlaps"
		)
		self.explanations.append(
			PlanExplanation(
				message=summary,
				rule_applied="regenerate_schedule",
				impact_score=1.0 if adjusted_count or invalid_count else 0.3,
			)
		)

	def mark_item_completion(self, item_id: UUID, completed: bool = True, when: datetime | None = None) -> None:
		"""Mark a specific schedule item as completed or incomplete.
		
		Args:
			item_id: ID of the schedule item to update.
			completed: If True, mark as completed; if False, mark as incomplete.
			when: Timestamp of completion (used only if completed=True).
		
		Raises:
			ValueError: If the schedule item with the given ID is not found.
		"""
		for item in self.items:
			if item.item_id == item_id:
				if completed:
					item.mark_completed(when)
				else:
					item.mark_incomplete()
				return
		raise ValueError("Schedule item not found")


@dataclass
class SchedulingConstraint:
	"""A constraint that restricts how pet care tasks can be scheduled.
	
	Specifies rules and limits on task scheduling based on various factors
	such as time availability, priority levels, task flexibility, and deadlines.
	
	Attributes:
		constraint_id: Unique identifier for this constraint.
		name: Human-readable name of the constraint.
		constraint_type: Type of constraint (TimeAvailability, Priority, etc.).
		weight: Importance weight for soft constraints (higher = more important).
		is_hard_constraint: If True, must be satisfied; if False, is a preference.
		allowed_start: Earliest time a task can start (for TIME_AVAILABILITY).
		allowed_end: Latest time a task can end (for TIME_AVAILABILITY).
		min_priority: Minimum task priority required (for PRIORITY).
		max_priority: Maximum task priority allowed (for PRIORITY).
		max_duration_min: Maximum task duration allowed (for PREFERENCE/SPACING).
		require_flexible: Whether tasks must be flexible (for PREFERENCE).
		deadline_at: Latest time by which task must complete (for DEADLINE).
	"""
	constraint_id: UUID = field(default_factory=uuid4)
	name: str = ""
	constraint_type: ConstraintType = ConstraintType.TIME_AVAILABILITY
	weight: int = 0
	is_hard_constraint: bool = False
	allowed_start: time | None = None
	allowed_end: time | None = None
	min_priority: int | None = None
	max_priority: int | None = None
	max_duration_min: int | None = None
	require_flexible: bool | None = None
	deadline_at: datetime | None = None

	def validate(self, item: ScheduleItem) -> bool:
		"""Return True when the schedule item satisfies this constraint.
		
		Validates a specific schedule item against this constraint's rules,
		checking that the item's task and timing meet all constraint requirements.
		
		Args:
			item: The schedule item to validate.
		
		Returns:
			True if the item satisfies all constraint checks, False otherwise.
		"""
		if item.task is None:
			return False

		task = item.task

		if self.constraint_type == ConstraintType.TIME_AVAILABILITY:
			if item.start_time is None or item.end_time is None:
				return False
			if self.allowed_start is not None and item.start_time.time() < self.allowed_start:
				return False
			if self.allowed_end is not None and item.end_time.time() > self.allowed_end:
				return False
			return True

		if self.constraint_type == ConstraintType.PRIORITY:
			if self.min_priority is not None and task.priority < self.min_priority:
				return False
			if self.max_priority is not None and task.priority > self.max_priority:
				return False
			return True

		if self.constraint_type == ConstraintType.PREFERENCE:
			if self.require_flexible is not None and task.is_flexible != self.require_flexible:
				return False
			if self.max_duration_min is not None and task.duration_min > self.max_duration_min:
				return False
			return True

		if self.constraint_type == ConstraintType.SPACING:
			if self.max_duration_min is not None and task.duration_min > self.max_duration_min:
				return False
			return True

		if self.constraint_type == ConstraintType.DEADLINE:
			if item.end_time is None:
				return False
			if self.deadline_at is not None and item.end_time > self.deadline_at:
				return False
			if task.latest_end is not None and item.end_time.time() > task.latest_end:
				return False
			return True

		return True


class TaskManagementAgent:
	"""Validates task payloads before persistence and emits deterministic repair hints."""

	DEFAULT_REPAIR_DURATION_MIN = 15

	def validate_task_payload(
		self,
		owner: "Owner",
		pet_id: UUID,
		task: CareTask,
		existing_task_id: UUID | None = None,
	) -> ValidationResult:
		"""Validate a task payload for add/edit operations.

		Rules enforced in Phase 2:
		- Duration must be positive.
		- latest_end must be after earliest_start.
		- Recurrence schema must be coherent.
		- Duplicate/contradictory tasks are rejected.
		"""
		result = ValidationResult()

		self._validate_duration(task, result)
		self._validate_time_window(task, result)
		self._validate_recurrence(task, result)
		self._validate_duplicate_or_contradictory(owner, pet_id, task, existing_task_id, result)

		return result

	def _validate_duration(self, task: CareTask, result: ValidationResult) -> None:
		if task.duration_min > 0:
			return

		result.add_violation(
			ValidationViolation(
				code="INVALID_DURATION",
				message="Task duration must be a positive number of minutes.",
				severity=ViolationSeverity.HIGH,
				repair_hint=(
					f"Set duration_min to at least {self.DEFAULT_REPAIR_DURATION_MIN} minutes."
				),
			)
		)

	def _validate_time_window(self, task: CareTask, result: ValidationResult) -> None:
		if task.earliest_start is None or task.latest_end is None:
			return

		if task.latest_end > task.earliest_start:
			return

		suggested_end = self._suggest_nearest_valid_end(task.earliest_start, task.duration_min)
		result.add_violation(
			ValidationViolation(
				code="INVALID_TIME_WINDOW",
				message="Task latest_end must be after earliest_start.",
				severity=ViolationSeverity.HIGH,
				repair_hint=(
					f"Set latest_end to {suggested_end.strftime('%H:%M')} or later "
					f"for earliest_start {task.earliest_start.strftime('%H:%M')}."
				),
			)
		)

	def _validate_recurrence(self, task: CareTask, result: ValidationResult) -> None:
		if task.frequency == Frequency.DAILY:
			if (
				task.weekly_day_of_week is not None
				or task.custom_days_of_week
				or task.custom_interval_days is not None
				or task.custom_anchor_date is not None
			):
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_DAILY",
						message="Daily recurrence cannot include weekly/custom recurrence fields.",
						severity=ViolationSeverity.MEDIUM,
						repair_hint=(
							"Normalize recurrence by clearing weekly_day_of_week, custom_days_of_week, "
							"custom_interval_days, and custom_anchor_date."
						),
					)
				)
			return

		if task.frequency == Frequency.WEEKLY:
			if task.weekly_day_of_week is None or not 0 <= task.weekly_day_of_week <= 6:
				suggested_day = task.created_on.weekday()
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_WEEKLY_DAY",
						message="Weekly recurrence requires weekly_day_of_week in range 0..6.",
						severity=ViolationSeverity.HIGH,
						repair_hint=f"Set weekly_day_of_week to {suggested_day}.",
					)
				)

			if (
				task.custom_days_of_week
				or task.custom_interval_days is not None
				or task.custom_anchor_date is not None
			):
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_WEEKLY_EXTRA",
						message="Weekly recurrence cannot include custom recurrence fields.",
						severity=ViolationSeverity.MEDIUM,
						repair_hint=(
							"Normalize recurrence by clearing custom_days_of_week, "
							"custom_interval_days, and custom_anchor_date."
						),
					)
				)
			return

		if task.frequency == Frequency.CUSTOM:
			has_days_mode = bool(task.custom_days_of_week)
			has_interval_mode = task.custom_interval_days is not None or task.custom_anchor_date is not None

			if task.custom_days_of_week and any(day < 0 or day > 6 for day in task.custom_days_of_week):
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_DAY_RANGE",
						message="Custom weekday recurrence must use weekday values in range 0..6.",
						severity=ViolationSeverity.HIGH,
						repair_hint="Use weekday values Monday=0 through Sunday=6.",
					)
				)

			if task.custom_interval_days is not None and task.custom_interval_days <= 0:
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_INTERVAL",
						message="Custom interval recurrence must use a positive custom_interval_days value.",
						severity=ViolationSeverity.HIGH,
						repair_hint="Set custom_interval_days to at least 1.",
					)
				)

			if has_days_mode and has_interval_mode:
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_MODE",
						message="Custom recurrence cannot use both weekday and interval modes at the same time.",
						severity=ViolationSeverity.HIGH,
						repair_hint=(
							"Choose one mode: keep custom_days_of_week or keep "
							"custom_interval_days/custom_anchor_date, then clear the other mode."
						),
					)
				)
			elif not has_days_mode and not has_interval_mode:
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_MISSING",
						message="Custom recurrence requires either weekday mode or interval mode.",
						severity=ViolationSeverity.HIGH,
						repair_hint=(
							"Set custom_days_of_week (for selected weekdays) or set both "
							"custom_interval_days and custom_anchor_date (for every N days)."
						),
					)
				)

			if task.custom_interval_days is not None and task.custom_anchor_date is None:
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_ANCHOR",
						message="Custom interval recurrence requires a custom_anchor_date.",
						severity=ViolationSeverity.MEDIUM,
						repair_hint=(
							f"Set custom_anchor_date to task created_on ({task.created_on.isoformat()}) "
							"or another intended anchor date."
						),
					)
				)

			if task.custom_anchor_date is not None and task.custom_interval_days is None:
				result.add_violation(
					ValidationViolation(
						code="INCOHERENT_RECURRENCE_CUSTOM_INTERVAL_MISSING",
						message="Custom anchor_date requires custom_interval_days for interval mode.",
						severity=ViolationSeverity.MEDIUM,
						repair_hint="Set custom_interval_days to at least 1 when using custom_anchor_date.",
					)
				)
			return

	def _validate_duplicate_or_contradictory(
		self,
		owner: "Owner",
		pet_id: UUID,
		task: CareTask,
		existing_task_id: UUID | None,
		result: ValidationResult,
	) -> None:
		pet = owner._get_pet_by_id(pet_id)
		if pet is None:
			result.add_violation(
				ValidationViolation(
					code="PET_NOT_FOUND",
					message="Target pet not found while validating task payload.",
					severity=ViolationSeverity.CRITICAL,
					repair_hint="Retry with a valid pet_id owned by the current owner.",
				)
			)
			return

		normalized_title = task.title.strip().lower()
		for existing in pet.tasks:
			if existing_task_id is not None and existing.task_id == existing_task_id:
				continue

			is_same_title = existing.title.strip().lower() == normalized_title and normalized_title != ""
			is_same_signature = (
				is_same_title
				and existing.category == task.category
				and existing.duration_min == task.duration_min
				and existing.frequency == task.frequency
				and existing.earliest_start == task.earliest_start
				and existing.latest_end == task.latest_end
				and existing.weekly_day_of_week == task.weekly_day_of_week
				and existing.custom_days_of_week == task.custom_days_of_week
				and existing.custom_interval_days == task.custom_interval_days
				and existing.custom_anchor_date == task.custom_anchor_date
			)

			if is_same_signature:
				result.add_violation(
					ValidationViolation(
						code="DUPLICATE_TASK",
						message=(
							f"Task duplicates existing task '{existing.title}' for this pet."
						),
						severity=ViolationSeverity.HIGH,
						repair_hint=(
							f"Merge with existing task {existing.task_id} or edit that task instead of creating a duplicate."
						),
					)
				)
				continue

			if is_same_title and (
				existing.frequency != task.frequency
				or existing.category != task.category
				or existing.earliest_start != task.earliest_start
				or existing.latest_end != task.latest_end
			):
				result.add_violation(
					ValidationViolation(
						code="CONTRADICTORY_TASK",
						message=(
							f"Task may contradict existing task '{existing.title}' for this pet "
							"(same title, conflicting recurrence/category/time window)."
						),
						severity=ViolationSeverity.MEDIUM,
						repair_hint=(
							f"Normalize recurrence/time fields and merge with task {existing.task_id} if it is the same routine."
						),
					)
				)

	def _suggest_nearest_valid_end(self, earliest_start: time, duration_min: int) -> time:
		duration = duration_min if duration_min > 0 else self.DEFAULT_REPAIR_DURATION_MIN
		base_dt = datetime.combine(date.today(), earliest_start)
		suggested = base_dt + timedelta(minutes=duration)
		end_of_day = datetime.combine(date.today(), time(hour=23, minute=59))
		if suggested > end_of_day:
			suggested = end_of_day
		return suggested.time()


@dataclass
class Owner:
	"""A pet owner and their associated pets and scheduling information.
	
	Manages all information about a pet owner including their pets,
	tasks, scheduling preferences, and generated schedules.
	
	Attributes:
		owner_id: Unique identifier for this owner.
		name: The owner's name.
		timezone: Timezone for scheduling (e.g., 'UTC', 'US/Eastern').
		pets: List of pets owned by this person.
		preference: The owner's scheduling preferences.
		availability_windows: Time windows when owner is available for pet care.
		schedules_by_date: Dictionary mapping dates to generated daily schedules.
		task_to_pet: Dictionary mapping task IDs to their associated pet IDs.
	"""
	owner_id: UUID = field(default_factory=uuid4)
	name: str = ""
	timezone: str = "UTC"
	pets: list[Pet] = field(default_factory=list)
	preference: OwnerPreference | None = None
	availability_windows: list[AvailabilityWindow] = field(default_factory=list)
	schedules_by_date: dict[date, DailySchedule] = field(default_factory=dict)
	task_to_pet: dict[UUID, UUID] = field(default_factory=dict)

	def add_pet(self, pet: Pet) -> None:
		"""Add a new pet to this owner's collection.
		
		Also registers all of the pet's tasks in the task_to_pet mapping.
		
		Args:
			pet: The pet to add.
		
		Raises:
			ValueError: If a pet with the same ID already exists.
		"""
		if any(existing_pet.pet_id == pet.pet_id for existing_pet in self.pets):
			raise ValueError("Pet with this ID already exists")
		self.pets.append(pet)
		for task in pet.tasks:
			self.task_to_pet[task.task_id] = pet.pet_id

	def remove_pet(self, pet_id: UUID) -> None:
		"""Remove a pet and all its tasks from this owner's collection.
		
		Also removes all task-to-pet mappings for this pet's tasks.
		
		Args:
			pet_id: ID of the pet to remove.
		
		Raises:
			ValueError: If no pet with the given ID exists.
		"""
		for idx, pet in enumerate(self.pets):
			if pet.pet_id == pet_id:
				for task in pet.tasks:
					self.task_to_pet.pop(task.task_id, None)
				del self.pets[idx]
				return
		raise ValueError("Pet not found")

	def add_task(self, pet_id: UUID, task: CareTask) -> None:
		"""Add a care task to a specific pet.
		
		Args:
			pet_id: ID of the pet to add the task to.
			task: The care task to add.
		
		Raises:
			ValueError: If the pet is not found or task ID already exists.
		"""
		pet = self._get_pet_by_id(pet_id)
		if pet is None:
			raise ValueError("Pet not found")
		if task.task_id in self.task_to_pet:
			raise ValueError("Task with this ID already exists")

		validation_result = TaskManagementAgent().validate_task_payload(
			owner=self,
			pet_id=pet_id,
			task=task,
			existing_task_id=None,
		)
		if not validation_result.passed:
			raise TaskValidationError(validation_result)

		pet.tasks.append(task)
		self.task_to_pet[task.task_id] = pet_id

	def edit_task(self, task_id: UUID, **changes: Any) -> None:
		"""Edit one or more fields of an existing care task.
		
		Args:
			task_id: ID of the task to edit.
			**changes: Keyword arguments for fields to update (field_name=new_value).
		
		Raises:
			ValueError: If task is not found or task_id field is being edited.
			AttributeError: If an unknown field name is provided.
		"""
		pet_id = self.task_to_pet.get(task_id)
		if pet_id is None:
			raise ValueError("Task not found")

		pet = self._get_pet_by_id(pet_id)
		if pet is None:
			raise ValueError("Inconsistent task index: pet not found")

		for task in pet.tasks:
			if task.task_id == task_id:
				candidate_task = replace(task)
				for field_name, field_value in changes.items():
					if field_name == "task_id":
						raise ValueError("task_id cannot be edited")
					if not hasattr(candidate_task, field_name):
						raise AttributeError(f"Unknown task field: {field_name}")
					setattr(candidate_task, field_name, field_value)

				validation_result = TaskManagementAgent().validate_task_payload(
					owner=self,
					pet_id=pet_id,
					task=candidate_task,
					existing_task_id=task_id,
				)
				if not validation_result.passed:
					raise TaskValidationError(validation_result)

				for field_name, field_value in changes.items():
					setattr(task, field_name, field_value)
				return

		raise ValueError("Task not found")

	def remove_task(self, task_id: UUID) -> None:
		"""Remove a care task from one of the owner's pets.
		
		Args:
			task_id: ID of the task to remove.
		
		Raises:
			ValueError: If task is not found or pet index is inconsistent.
		"""
		pet_id = self.task_to_pet.get(task_id)
		if pet_id is None:
			raise ValueError("Task not found")

		pet = self._get_pet_by_id(pet_id)
		if pet is None:
			raise ValueError("Inconsistent task index: pet not found")

		for idx, task in enumerate(pet.tasks):
			if task.task_id == task_id:
				del pet.tasks[idx]
				self.task_to_pet.pop(task_id, None)
				return

		raise ValueError("Task not found")

	def view_schedule(self, schedule_date: date) -> DailySchedule | None:
		"""Retrieve the generated schedule for a specific date.
		
		Args:
			schedule_date: The date for which to retrieve the schedule.
		
		Returns:
			The DailySchedule for the given date, or None if not yet generated.
		"""
		return self.schedules_by_date.get(schedule_date)

	def _get_pet_by_id(self, pet_id: UUID) -> Pet | None:
		"""Internal helper to retrieve a pet by its ID.
		
		Args:
			pet_id: ID of the pet to retrieve.
		
		Returns:
			The Pet object if found, None otherwise.
		"""
		for pet in self.pets:
			if pet.pet_id == pet_id:
				return pet
		return None


class SchedulerService:
	"""Service for generating and managing pet care schedules.
	
	Handles the core scheduling logic including constraint application,
	task ordering, and schedule generation.
	
	Attributes:
		constraints: List of scheduling constraints to apply.
		explanations_by_schedule_id: Maps schedule IDs to their explanations.
	"""
	def __init__(self, constraints: list[SchedulingConstraint] | None = None) -> None:
		"""Initialize the scheduler service.
		
		Args:
			constraints: Optional list of scheduling constraints to enforce.
				Defaults to an empty list.
		"""
		self.constraints = constraints or []
		self.explanations_by_schedule_id: dict[UUID, list[PlanExplanation]] = {}

	def _build_item_reason_code(
		self,
		decision_reason: str,
		removed_tasks: list[ScheduleItem],
		deferred_tasks: list[ScheduleItem],
	) -> str:
		"""Return a machine-readable reason code for a placement decision."""
		if removed_tasks:
			return "PLACED_WITH_BACKTRACK_REMOVE"
		if deferred_tasks:
			return "PLACED_WITH_DEFERRAL"

		reason_lower = decision_reason.lower()
		if "after deadline" in reason_lower:
			return "PLACED_FLEX_AFTER_DEADLINE"
		if "first open gap" in reason_lower:
			return "PLACED_FIRST_OPEN_GAP"
		if "after" in reason_lower and "finished" in reason_lower:
			return "PLACED_AFTER_BLOCKING_TASK"
		return "PLACED_EARLIEST_FEASIBLE"

	def _should_include_task_for_date(self, task: CareTask, schedule_date: date) -> bool:
		"""Return whether this task recurs on the given schedule date."""
		weekday = schedule_date.weekday()

		if task.frequency == Frequency.DAILY:
			return True

		if task.frequency == Frequency.WEEKLY:
			target_weekday = task.weekly_day_of_week
			if target_weekday is None:
				target_weekday = task.created_on.weekday()
			return weekday == target_weekday

		if task.frequency == Frequency.CUSTOM:
			if task.custom_days_of_week:
				return weekday in task.custom_days_of_week

			if task.custom_interval_days is not None and task.custom_anchor_date is not None:
				if task.custom_interval_days <= 0:
					return False
				delta_days = (schedule_date - task.custom_anchor_date).days
				return delta_days >= 0 and delta_days % task.custom_interval_days == 0

			# Backward compatibility: CUSTOM tasks with no explicit rule still run daily.
			return True

		return True

	def _expand_recurring_tasks(
		self,
		task_pairs: list[tuple[UUID, CareTask]],
		schedule_date: date,
	) -> tuple[list[tuple[UUID, CareTask]], int]:
		"""Filter tasks to those that recur on schedule_date.

		Returns a tuple of (included_task_pairs, recurrence_skipped_count).
		"""
		included: list[tuple[UUID, CareTask]] = []
		skipped = 0
		for pet_id, task in task_pairs:
			if self._should_include_task_for_date(task, schedule_date):
				included.append((pet_id, task))
			else:
				skipped += 1
		return included, skipped

	def _resolve_day_windows(
		self,
		owner: Owner,
		schedule_date: date,
	) -> tuple[list[AvailabilityWindow], bool]:
		"""Return windows configured for the requested schedule weekday only."""
		matching = [
			window for window in owner.availability_windows
			if window.day_of_week == schedule_date.weekday()
		]
		if matching:
			matching.sort(key=lambda window: window.start_time or time(hour=0, minute=0))
			return matching, False
		return [], False

	def generate_daily_schedule(self, owner: Owner, schedule_date: date) -> DailySchedule:
		"""Generate a daily schedule for all of an owner's pets' tasks.
		
		Collects all tasks from the owner's pets, applies constraints and
		preferences, and creates a schedule with tasks ordered by priority.
		
		Args:
			owner: The owner whose schedule to generate.
			schedule_date: The date to generate the schedule for.
		
		Returns:
			A DailySchedule with all scheduled tasks for the given date.
		"""
		all_tasks: list[tuple[UUID, CareTask]] = []
		for pet in owner.pets:
			for task in pet.tasks:
				all_tasks.append((pet.pet_id, task))

		day_windows, _ = self._resolve_day_windows(owner, schedule_date)

		schedule = DailySchedule(
			date=schedule_date,
			status=ScheduleStatus.DRAFT,
		)

		if not day_windows:
			schedule.explanations = [
				PlanExplanation(
					message="No availability windows found for this day",
					rule_applied="availability_required",
					impact_score=1.0,
				)
			]
			schedule.planning_metadata = {
				"scheduled_count": 0,
				"recurrence_skipped_count": 0,
				"unscheduled_count": 0,
				"ordering_policy": "non_flexible_then_priority_then_deadline",
				"strategy": "defer_flexible_then_remove_lower_priority_rigid",
				"reason_codes": ["NO_AVAILABILITY_WINDOWS"],
			}
			self.explanations_by_schedule_id[schedule.schedule_id] = schedule.explanations
			return schedule

		expanded_pairs, recurrence_skipped = self._expand_recurring_tasks(all_tasks, schedule_date)
		explanations: list[PlanExplanation] = []
		reason_codes_used: set[str] = set()
		skipped_count = 0
		invalid_duration_pairs = [
			(pair)
			for pair in expanded_pairs
			if pair[1].duration_min <= 0
		]

		for _, task in invalid_duration_pairs:
			explanations.append(
				PlanExplanation(
					message=(f"Skipped '{task.title}' because duration_min must be positive, got {task.duration_min}."),
					rule_applied="task_skipped_invalid_duration",
					impact_score=1.0,
				)
			)
			skipped_count += 1
			reason_codes_used.add("TASK_SKIPPED_INVALID_DURATION")

		expanded_pairs = [pair for pair in expanded_pairs if pair[1].duration_min > 0]

		filtered_tasks = self.apply_constraints(
			[t for _, t in expanded_pairs],
			owner,
			schedule_date,
		)
		filtered_task_ids = {task.task_id for task in filtered_tasks}

		def ordering_key(pair: tuple[UUID, CareTask]) -> tuple[bool, int, time, time]:
			task = pair[1]
			latest_end = task.latest_end or time(hour=23, minute=59)
			earliest_start = task.earliest_start or time(hour=0, minute=0)
			return (task.is_flexible, -task.priority, latest_end, earliest_start)

		candidate_pairs = [
			(pet_id, task)
			for pet_id, task in expanded_pairs
			if task.task_id in filtered_task_ids
		]
		candidate_pairs.sort(key=ordering_key)

		for pet_id, task in candidate_pairs:
			slot, decision_reason, removed_tasks, deferred_tasks = self._try_schedule_with_backtracking(
				task, pet_id, schedule_date, day_windows, schedule.items
			)
			if slot is None:
				skipped_count += 1
				reason_codes_used.add("TASK_SKIPPED_NO_FEASIBLE_SLOT")
				explanations.append(
					PlanExplanation(
						message=(
							f"Skipped '{task.title}' (priority {task.priority}, duration {task.duration_min} min, "
							f"flexible={task.is_flexible}): {decision_reason}"
						),
						rule_applied="task_skipped_no_feasible_slot",
						impact_score=0.9,
					)
				)
				continue

			start_dt, end_dt = slot
			reason_code = self._build_item_reason_code(
				decision_reason=decision_reason,
				removed_tasks=removed_tasks,
				deferred_tasks=deferred_tasks,
			)
			reason_codes_used.add(reason_code)
			schedule.items.append(
				ScheduleItem(
					start_time=start_dt,
					end_time=end_dt,
					reason_code=reason_code,
					task=task,
					pet_id=pet_id,
				)
			)
			schedule.items.sort(key=lambda item: item.start_time or datetime.combine(schedule_date, time(hour=0)))
			schedule.total_planned_min += max(task.duration_min, 0)
			
			if removed_tasks:
				removed_titles = ", ".join([rt.task.title if rt.task else "unknown" for rt in removed_tasks])
				explanations.append(
					PlanExplanation(
						message=(
							f"Placed '{task.title}' from {start_dt.strftime('%H:%M')} to {end_dt.strftime('%H:%M')} "
							f"(priority {task.priority}, flexible={task.is_flexible}) by removing lower-priority tasks: {removed_titles}"
						),
						rule_applied="task_placed_with_backtracking",
						impact_score=0.75,
					)
				)
			elif deferred_tasks:
				deferred_titles = ", ".join([dt.task.title if dt.task else "unknown" for dt in deferred_tasks])
				explanations.append(
					PlanExplanation(
						message=(
							f"Placed '{task.title}' from {start_dt.strftime('%H:%M')} to {end_dt.strftime('%H:%M')} "
							f"(priority {task.priority}, flexible={task.is_flexible}) by deferring flexible tasks: {deferred_titles}"
						),
						rule_applied="task_placed_with_deferral",
						impact_score=0.7,
					)
				)
			else:
				explanations.append(
					PlanExplanation(
						message=(
							f"Placed '{task.title}' from {start_dt.strftime('%H:%M')} to {end_dt.strftime('%H:%M')} "
							f"(priority {task.priority}, flexible={task.is_flexible}): {decision_reason}"
						),
						rule_applied="task_placed_with_reason",
						impact_score=0.6,
					)
				)

		explanations.insert(
			0,
			PlanExplanation(
				message=(
					f"Planning summary for {schedule_date.isoformat()}: scheduled {len(schedule.items)} task(s), "
					f"skipped {recurrence_skipped} task(s) by recurrence rules, "
					f"skipped {skipped_count} task(s). Ordering: non-flexible first (rigid scheduling), then higher priority, "
					"then earlier deadline. Strategy: defer flexible tasks to later slots, remove only as last resort."
				),
				rule_applied="planning_summary",
				impact_score=1.0,
			),
		)
		if recurrence_skipped > 0:
			reason_codes_used.add("RECURRENCE_FILTERED_OUT")

		schedule.planning_metadata = {
			"scheduled_count": len(schedule.items),
			"recurrence_skipped_count": recurrence_skipped,
			"unscheduled_count": skipped_count,
			"ordering_policy": "non_flexible_then_priority_then_deadline",
			"strategy": "defer_flexible_then_remove_lower_priority_rigid",
			"reason_codes": sorted(reason_codes_used),
		}
		schedule.explanations = explanations
		self.explanations_by_schedule_id[schedule.schedule_id] = explanations
		return schedule

	def _find_earliest_slot(
		self,
		task: CareTask,
		schedule_date: date,
		day_windows: list[AvailabilityWindow],
		existing_items: list[ScheduleItem],
	) -> tuple[tuple[datetime, datetime] | None, str]:
		"""Find the earliest non-overlapping slot and explain the scheduling decision.
		
		For flexible tasks: tries to fit within deadline first, then allows overflow past deadline.
		For non-flexible tasks: must fit within deadline.
		"""
		duration = timedelta(minutes=max(task.duration_min, 0))
		deadline_text = task.latest_end.strftime("%H:%M") if task.latest_end is not None else "end of day"
		earliest_text = task.earliest_start.strftime("%H:%M") if task.earliest_start is not None else "window start"

		if duration <= timedelta(minutes=0):
			return None, "task duration is 0 minutes, so there is nothing to schedule"

		failure_reasons: list[str] = []

		for window in day_windows:
			window_start_time = window.start_time or time(hour=0, minute=0)
			window_end_time = window.end_time or time(hour=23, minute=59)
			window_start = datetime.combine(schedule_date, window_start_time)
			window_end = datetime.combine(schedule_date, window_end_time)
			if window_end <= window_start:
				failure_reasons.append(
					f"availability window {window_start_time.strftime('%H:%M')}-{window_end_time.strftime('%H:%M')} is invalid"
				)
				continue

			task_start_bound = window_start
			if task.earliest_start is not None:
				task_start_bound = max(task_start_bound, datetime.combine(schedule_date, task.earliest_start))

			# For flexible tasks, allow overflow past deadline; for rigid tasks, enforce deadline
			task_end_bound = window_end
			if task.latest_end is not None:
				task_end_bound = min(task_end_bound, datetime.combine(schedule_date, task.latest_end))
			
			deadline_bound = task_end_bound  # Store original deadline bound

			# Try to fit within deadline first
			if task_end_bound <= task_start_bound or task_start_bound + duration > task_end_bound:
				within_deadline_failed = (
					f"no {task.duration_min}-minute gap available between "
					f"{task_start_bound.strftime('%H:%M')} and {task_end_bound.strftime('%H:%M')}"
				)
				
				# For flexible tasks, try to fit after deadline but within availability window
				if task.is_flexible and window_end > deadline_bound:
					task_end_bound = window_end  # Extend search to end of availability window
					# Continue to try below with extended bound
				else:
					failure_reasons.append(within_deadline_failed)
					continue
			else:
				# Slot fits within deadline, try to find it
				cursor = task_start_bound
				last_blocking_item: ScheduleItem | None = None
				relevant_items = sorted(
					[
						item
						for item in existing_items
						if item.start_time is not None
						and item.end_time is not None
						and item.end_time > task_start_bound
						and item.start_time < task_end_bound
					],
					key=lambda item: item.start_time,
				)

				for item in relevant_items:
					if cursor + duration <= item.start_time:
						reason = (
							f"scheduled in first open gap before deadline {deadline_text}; "
							f"starts at {cursor.strftime('%H:%M')} after earliest bound {earliest_text}"
						)
						return (cursor, cursor + duration), reason
					if item.end_time > cursor:
						cursor = item.end_time
						last_blocking_item = item
					if cursor + duration > deadline_bound:  # Use original deadline bound for rigid check
						break

				if cursor + duration <= deadline_bound:  # Check against original deadline
					if last_blocking_item and last_blocking_item.end_time is not None:
						blocking_title = (
							last_blocking_item.task.title
							if last_blocking_item.task is not None and last_blocking_item.task.title
							else "an earlier task"
						)
						reason = (
							f"scheduled after {blocking_title} finished at {last_blocking_item.end_time.strftime('%H:%M')}; "
							f"still fits before deadline {deadline_text}"
						)
					else:
						reason = (
							f"scheduled at earliest feasible time {cursor.strftime('%H:%M')} "
							f"within availability and before deadline {deadline_text}"
						)
					return (cursor, cursor + duration), reason

				# Doesn't fit within deadline, try extending for flexible tasks
				if not task.is_flexible:
					failure_reasons.append(
						f"no {task.duration_min}-minute gap available between "
						f"{task_start_bound.strftime('%H:%M')} and {deadline_bound.strftime('%H:%M')}"
					)
					continue
				
				task_end_bound = window_end  # Extend to window end for flexible task

			# Attempt to place flexible task after deadline
			if task.is_flexible:
				cursor = task_start_bound
				relevant_items = sorted(
					[
						item
						for item in existing_items
						if item.start_time is not None
						and item.end_time is not None
						and item.end_time > task_start_bound
						and item.start_time < task_end_bound
					],
					key=lambda item: item.start_time,
				)

				last_blocking_item_extended: ScheduleItem | None = None
				for item in relevant_items:
					if cursor + duration <= item.start_time:
						if cursor >= deadline_bound:
							reason = (
								f"flexible task scheduled after deadline {deadline_text} at {cursor.strftime('%H:%M')} "
								f"(no room before deadline, placed in available gap)"
							)
						else:
							reason = (
								f"scheduled in first open gap before deadline {deadline_text}; "
								f"starts at {cursor.strftime('%H:%M')} after earliest bound {earliest_text}"
							)
						return (cursor, cursor + duration), reason
					if item.end_time > cursor:
						cursor = item.end_time
						last_blocking_item_extended = item
					if cursor + duration > task_end_bound:
						break

				if cursor + duration <= task_end_bound:
					if cursor >= deadline_bound:
						reason = (
							f"flexible task scheduled after deadline {deadline_text} at {cursor.strftime('%H:%M')} "
							f"(no room before deadline)"
						)
					elif last_blocking_item_extended and last_blocking_item_extended.end_time is not None:
						blocking_title = (
							last_blocking_item_extended.task.title
							if last_blocking_item_extended.task is not None and last_blocking_item_extended.task.title
							else "an earlier task"
						)
						reason = (
							f"scheduled after {blocking_title} finished at {last_blocking_item_extended.end_time.strftime('%H:%M')}; "
							f"fits within availability window"
						)
					else:
						reason = (
							f"flexible task scheduled at {cursor.strftime('%H:%M')}; "
							f"fits within availability window"
						)
					return (cursor, cursor + duration), reason

				failure_reasons.append(
					f"no {task.duration_min}-minute gap available even after deadline {deadline_text}"
				)

		if not failure_reasons:
			return None, "no feasible slot found"

		return None, "; ".join(failure_reasons)

	def _try_schedule_with_backtracking(
		self,
		task: CareTask,
		pet_id: UUID,
		schedule_date: date,
		day_windows: list[AvailabilityWindow],
		existing_items: list[ScheduleItem],
	) -> tuple[tuple[datetime, datetime] | None, str, list[ScheduleItem], list[ScheduleItem]]:
		"""Try to schedule a task; defer flexible tasks first, then remove lower-priority tasks if needed.
		
		Returns:
			(slot, reason, removed_tasks, deferred_tasks)
		"""
		slot, reason = self._find_earliest_slot(task, schedule_date, day_windows, existing_items)
		if slot is not None:
			return slot, reason, [], []

		flexible_candidates = sorted(
			[item for item in existing_items if item.task and item.task.is_flexible and item.task.priority < task.priority],
			key=lambda item: (item.task.priority if item.task else 0, item.start_time or datetime.min),
		)

		deferred_items: list[ScheduleItem] = []
		temp_items = existing_items.copy()

		for candidate in flexible_candidates:
			temp_items.remove(candidate)
			deferred_items.append(candidate)

			slot, reason = self._find_earliest_slot(task, schedule_date, day_windows, temp_items)
			if slot is not None:
				for deferred in deferred_items:
					later_slot, _ = self._find_earliest_slot(deferred.task, schedule_date, day_windows, temp_items)
					if later_slot is not None:
						d_start, d_end = later_slot
						deferred.start_time = d_start
						deferred.end_time = d_end
						temp_items.append(deferred)

				existing_items.clear()
				existing_items.extend(temp_items)
				return slot, reason, [], deferred_items

			temp_items.append(candidate)
			deferred_items.pop()

		rigid_candidates = sorted(
			[item for item in existing_items if item.task and not item.task.is_flexible and item.task.priority < task.priority],
			key=lambda item: (item.task.priority if item.task else 0, item.start_time or datetime.min),
		)

		removed_items: list[ScheduleItem] = []
		temp_items = existing_items.copy()

		for candidate in rigid_candidates:
			temp_items.remove(candidate)
			removed_items.append(candidate)

			slot, reason = self._find_earliest_slot(task, schedule_date, day_windows, temp_items)
			if slot is not None:
				existing_items.clear()
				existing_items.extend(temp_items)
				return slot, reason, removed_items, []

			temp_items.append(candidate)
			removed_items.pop()

		return None, reason, [], []

	def score_task(self, task: CareTask) -> float:
		"""Calculate a priority score for a task to determine scheduling order.
		
		Args:
			task: The task to score.
		
		Returns:
			A float score (higher scores indicate higher priority).
		"""
		return float(task.priority)

	def apply_constraints(self, tasks: list[CareTask], owner: Owner, schedule_date: date) -> list[CareTask]:
		"""Filter and sort tasks based on owner availability and constraints.
		
		Removes tasks that don't fit the owner's availability windows or
		constraints, then sorts remaining tasks by priority score.
		
		Args:
			tasks: List of tasks to filter.
			owner: The owner whose preferences and availability to apply.
			schedule_date: The date being scheduled for.
		
		Returns:
			A list of filtered and sorted tasks ready for scheduling.
		"""
		day_windows, _ = self._resolve_day_windows(owner, schedule_date)

		if not day_windows:
			return []

		filtered: list[CareTask] = []
		for task in tasks:
			if task.duration_min <= 0:
				continue
			if owner.preference and owner.preference.avoid_late_night:
				if task.latest_end is not None and task.latest_end >= time(hour=22, minute=0):
					continue
			filtered.append(task)

		# Constraints are optional hooks for future expansion.
		for constraint in self.constraints:
			if constraint.is_hard_constraint:
				filtered = [
					task
					for task in filtered
					if constraint.validate(
						ScheduleItem(
							start_time=datetime.combine(schedule_date, task.earliest_start or time(hour=8, minute=0)),
							end_time=datetime.combine(schedule_date, task.latest_end or time(hour=20, minute=0)),
							task=task,
						)
					)
				]

		return sorted(filtered, key=self.score_task, reverse=True)

	def explain_plan(self, schedule_id: UUID) -> list[PlanExplanation]:
		"""Retrieve the explanations for a schedule's planning decisions.
		
		Args:
			schedule_id: ID of the schedule to explain.
		
		Returns:
			List of PlanExplanation objects for the schedule,
			or empty list if not found.
		"""
		return self.explanations_by_schedule_id.get(schedule_id, [])

	def filter_task_pairs_for_display(
		self,
		task_pairs: list[tuple[Pet, CareTask]],
		pet_id: UUID | None = None,
		flexible_only: bool | None = None,
	) -> list[tuple[Pet, CareTask]]:
		"""Filter task pairs for UI display without mutating source data.

		Args:
			task_pairs: List of (pet, task) tuples to filter.
			pet_id: Optional pet ID to include only one pet's tasks.
			flexible_only: None for all tasks, True for flexible tasks,
				False for non-flexible tasks only.

		Returns:
			Filtered list of (pet, task) tuples.
		"""
		filtered = task_pairs
		if pet_id is not None:
			filtered = [(pet, task) for pet, task in filtered if pet.pet_id == pet_id]

		if flexible_only is None:
			return filtered

		return [(pet, task) for pet, task in filtered if task.is_flexible == flexible_only]

	def sort_task_pairs_for_display(self, task_pairs: list[tuple[Pet, CareTask]]) -> list[tuple[Pet, CareTask]]:
		"""Return task pairs sorted for readable table display.

		Ordering: tasks with explicit start time first, then start time,
		higher priority first, then title alphabetically.
		"""
		def sort_key(pair: tuple[Pet, CareTask]) -> tuple[int, time, int, str]:
			task = pair[1]
			start = task.earliest_start if task.earliest_start is not None else time(hour=23, minute=59)
			has_no_start = 1 if task.earliest_start is None else 0
			return (has_no_start, start, -task.priority, task.title.lower())

		return sorted(task_pairs, key=sort_key)

	def sort_schedule_items_for_display(self, items: list[ScheduleItem]) -> list[ScheduleItem]:
		"""Sort scheduled items by start time for stable display order."""
		return sorted(items, key=lambda item: item.start_time or datetime.min)

	def get_schedule_conflicts(self, schedule: DailySchedule) -> list[tuple[ScheduleItem, ScheduleItem]]:
		"""Return overlapping schedule item pairs for warning display."""
		sorted_items = [
			item
			for item in self.sort_schedule_items_for_display(schedule.items)
			if item.start_time is not None and item.end_time is not None
		]
		conflicts: list[tuple[ScheduleItem, ScheduleItem]] = []
		for previous_item, current_item in zip(sorted_items, sorted_items[1:]):
			if previous_item.end_time > current_item.start_time:
				conflicts.append((previous_item, current_item))
		return conflicts


@dataclass
class SchedulerAgentOutput:
	"""Output contract for scheduler agent invocations."""
	candidate: ScheduleCandidate
	baseline_schedule: DailySchedule
	duration_ms: int


class SchedulerAgent(Protocol):
	"""Scheduler Agent interface for proposing schedule candidates."""

	def propose_candidate(self, context: PlanningContext) -> SchedulerAgentOutput:
		"""Return advisory candidate plus deterministic baseline schedule."""


class ExplanationAgent(Protocol):
	"""Explanation Agent interface for grounded explanation expansion."""

	def expand_explanations(
		self,
		context: PlanningContext,
		candidate: ScheduleCandidate,
		schedule: DailySchedule,
		retrieved_snippets: list[RetrievalSnippet] | None = None,
	) -> list[PlanExplanation]:
		"""Return grounded explanations for the chosen schedule."""


class DeterministicSchedulerAgent:
	"""Engine-first Scheduler Agent backed by deterministic planning logic."""

	def __init__(self, scheduler_service: SchedulerService) -> None:
		self.scheduler_service = scheduler_service

	def propose_candidate(self, context: PlanningContext) -> SchedulerAgentOutput:
		started_at = datetime.utcnow()
		baseline_schedule = self.scheduler_service.generate_daily_schedule(context.owner, context.schedule_date)
		duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)

		reason_codes = tuple(
			baseline_schedule.planning_metadata.get("reason_codes", [])
		)
		candidate = ScheduleCandidate(
			proposed_items=list(baseline_schedule.items),
			objective_score=float(len(baseline_schedule.items)),
			rationale_summary="Delegated to SchedulerService for deterministic baseline candidate.",
			rationale_metadata={
				"source_of_truth": SCHEDULE_SOURCE_OF_TRUTH,
				"fallback_policy": DETERMINISTIC_FALLBACK_POLICY,
				"hard_constraint_rules": list(HARD_CONSTRAINT_RULES),
			},
			planning_summary_metadata=dict(baseline_schedule.planning_metadata),
			reason_codes=reason_codes,
			generated_by=AgentRole.SCHEDULER,
			advisory_only=AGENT_OUTPUTS_ADVISORY_ONLY,
		)
		return SchedulerAgentOutput(
			candidate=candidate,
			baseline_schedule=baseline_schedule,
			duration_ms=duration_ms,
		)


class DeterministicExplanationAgent:
	"""Build rich, fact-grounded explanations from concrete schedule state only."""

	UNSUPPORTED_CLAIM_MARKERS = ("best", "optimal", "guaranteed", "always", "never", "certainly")

	def _build_retrieval_source_text(self, snippet: RetrievalSnippet) -> str:
		return f"[{snippet.attribution}] {snippet.content}"

	def _contains_obvious_unsupported_claim(self, message: str, retrieved_snippets: list[RetrievalSnippet] | None) -> bool:
		lower_message = message.lower()
		if not any(marker in lower_message for marker in self.UNSUPPORTED_CLAIM_MARKERS):
			return False

		retrieved_text = " ".join(snippet.content.lower() for snippet in retrieved_snippets or [])
		return not any(marker in retrieved_text for marker in self.UNSUPPORTED_CLAIM_MARKERS)

	def _get_day_windows(self, context: PlanningContext) -> list[AvailabilityWindow]:
		day_windows = [
			window
			for window in context.owner.availability_windows
			if window.day_of_week == context.schedule_date.weekday()
		]
		day_windows.sort(key=lambda window: window.start_time or time(hour=0, minute=0))
		return day_windows

	def _window_for_item(
		self,
		item: ScheduleItem,
		day_windows: list[AvailabilityWindow],
	) -> tuple[time, time] | None:
		if item.start_time is None or item.end_time is None:
			return None

		for window in day_windows:
			start_t = window.start_time or time(hour=0, minute=0)
			end_t = window.end_time or time(hour=23, minute=59)
			window_start = datetime.combine(item.start_time.date(), start_t)
			window_end = datetime.combine(item.start_time.date(), end_t)
			if item.start_time >= window_start and item.end_time <= window_end:
				return (start_t, end_t)

		return None

	def _count_overlaps(self, items: list[ScheduleItem]) -> int:
		sorted_items = [
			item
			for item in sorted(items, key=lambda scheduled_item: scheduled_item.start_time or datetime.min)
			if item.start_time is not None and item.end_time is not None
		]
		overlaps = 0
		for previous_item, current_item in zip(sorted_items, sorted_items[1:]):
			if previous_item.end_time > current_item.start_time:
				overlaps += 1
		return overlaps

	def _build_item_explanation(
		self,
		item: ScheduleItem,
		day_windows: list[AvailabilityWindow],
	) -> PlanExplanation | None:
		if item.task is None or item.start_time is None or item.end_time is None:
			return None

		task = item.task
		early_text = task.earliest_start.strftime("%H:%M") if task.earliest_start is not None else "none"
		latest_text = task.latest_end.strftime("%H:%M") if task.latest_end is not None else "none"
		window = self._window_for_item(item, day_windows)

		feasible_facts: list[str] = []
		if window is not None:
			feasible_facts.append(
				f"inside owner availability {window[0].strftime('%H:%M')}-{window[1].strftime('%H:%M')}"
			)
		else:
			feasible_facts.append("inside known availability windows could not be confirmed")

		if task.earliest_start is not None and item.start_time.time() >= task.earliest_start:
			feasible_facts.append(f"starts after earliest_start {early_text}")

		if task.latest_end is not None:
			if item.end_time.time() <= task.latest_end:
				feasible_facts.append(f"ends by latest_end {latest_text}")
			elif task.is_flexible:
				feasible_facts.append(
					f"ends after latest_end {latest_text} but task is flexible"
				)

		return PlanExplanation(
			message=(
				f"Grounded decision for '{task.title}': scheduled {item.start_time.strftime('%H:%M')}-"
				f"{item.end_time.strftime('%H:%M')} (priority={task.priority}, flexible={task.is_flexible}, "
				f"reason_code={item.reason_code}). Feasible because "
				f"{'; '.join(feasible_facts)}."
			),
			rule_applied="phase4_grounded_item",
			impact_score=0.8,
		)

	def _passes_groundedness_guardrails(
		self,
		explanation: PlanExplanation,
		schedule: DailySchedule,
		context: PlanningContext,
		retrieved_snippets: list[RetrievalSnippet] | None = None,
	) -> bool:
		message = explanation.message
		if not message:
			return False

		if explanation.rule_applied == "phase4_grounded_summary":
			if self._contains_obvious_unsupported_claim(message, retrieved_snippets):
				return False
			return (
				context.schedule_date.isoformat() in message
				and str(len(schedule.items)) in message
			)

		if explanation.rule_applied == "phase4_conflict_and_deferral_facts":
			if self._contains_obvious_unsupported_claim(message, retrieved_snippets):
				return False
			return "overlap(s) detected" in message and "deferral" in message

		if explanation.rule_applied == "phase4_grounded_item":
			if self._contains_obvious_unsupported_claim(message, retrieved_snippets):
				return False
			if "Feasible because" not in message:
				return False
			if not any(item.reason_code in message for item in schedule.items if item.reason_code):
				return False
			return any(
				item.task is not None
				and item.task.title
				and item.task.title in message
				for item in schedule.items
			)

		if explanation.rule_applied == "phase6_retrieved_context":
			if self._contains_obvious_unsupported_claim(message, retrieved_snippets):
				return False
			if "Sources:" not in message:
				return False
			if context.schedule_date.isoformat() not in message:
				return False
			if retrieved_snippets is None or not retrieved_snippets:
				return False
			return all(snippet.attribution in message for snippet in retrieved_snippets)

		return False

	def expand_explanations(
		self,
		context: PlanningContext,
		candidate: ScheduleCandidate,
		schedule: DailySchedule,
		retrieved_snippets: list[RetrievalSnippet] | None = None,
	) -> list[PlanExplanation]:
		"""Enrich schedule explanations using grounded schedule facts only."""
		base_explanations = list(schedule.explanations)
		day_windows = self._get_day_windows(context)
		window_text = (
			", ".join(
				f"{(window.start_time or time(hour=0, minute=0)).strftime('%H:%M')}-"
				f"{(window.end_time or time(hour=23, minute=59)).strftime('%H:%M')}"
				for window in day_windows
			)
			if day_windows
			else "none"
		)

		planning_metadata = schedule.planning_metadata
		recurrence_skipped = int(planning_metadata.get("recurrence_skipped_count", 0))
		unscheduled_count = int(planning_metadata.get("unscheduled_count", 0))
		ordering_policy = str(planning_metadata.get("ordering_policy", "unknown"))
		strategy = str(planning_metadata.get("strategy", "unknown"))

		overlap_count = self._count_overlaps(schedule.items)
		deferral_count = sum(1 for item in schedule.items if item.reason_code == "PLACED_WITH_DEFERRAL")
		backtrack_remove_count = sum(
			1 for item in schedule.items if item.reason_code == "PLACED_WITH_BACKTRACK_REMOVE"
		)

		phase4_explanations: list[PlanExplanation] = [
			PlanExplanation(
				message=(
					f"Grounded planning summary for {context.schedule_date.isoformat()}: "
					f"scheduled {len(schedule.items)} task(s). Constraints used: owner availability windows [{window_text}], "
					"no-overlap guardrail, rigid earliest_start/latest_end windows for non-flexible tasks. "
					f"Policy: {ordering_policy}. Strategy: {strategy}. "
					f"Recurrence skipped {recurrence_skipped}, unscheduled {unscheduled_count}."
				),
				rule_applied="phase4_grounded_summary",
				impact_score=1.0,
			),
			PlanExplanation(
				message=(
					f"Conflict and deferral facts: {overlap_count} overlap(s) detected in final schedule state, "
					f"deferral placements={deferral_count}, backtrack removals={backtrack_remove_count}, "
					f"candidate reason codes={', '.join(candidate.reason_codes) if candidate.reason_codes else 'none'}."
				),
				rule_applied="phase4_conflict_and_deferral_facts",
				impact_score=0.9,
			),
		]

		for item in sorted(schedule.items, key=lambda scheduled_item: scheduled_item.start_time or datetime.min):
			item_explanation = self._build_item_explanation(item=item, day_windows=day_windows)
			if item_explanation is not None:
				phase4_explanations.append(item_explanation)

		phase6_explanations: list[PlanExplanation] = []
		if retrieved_snippets:
			source_text = "; ".join(self._build_retrieval_source_text(snippet) for snippet in retrieved_snippets)
			phase6_explanations.append(
				PlanExplanation(
					message=(
						f"Retrieved context for {context.schedule_date.isoformat()} supports the plan. "
						f"Sources: {source_text}."
					),
					rule_applied="phase6_retrieved_context",
					impact_score=0.95,
				)
			)

		grounded_phase4 = [
			explanation
			for explanation in phase4_explanations
			if self._passes_groundedness_guardrails(explanation, schedule=schedule, context=context)
		]
		grounded_phase6 = [
			explanation
			for explanation in phase6_explanations
			if self._passes_groundedness_guardrails(
				explanation,
				schedule=schedule,
				context=context,
				retrieved_snippets=retrieved_snippets,
			)
		]

		return base_explanations + grounded_phase4 + grounded_phase6


class PetCareApp:
	"""Main application for managing pet care and scheduling.
	
	Coordinates owner profiles, pet management, task scheduling,
	and schedule tracking.
	
	Attributes:
		scheduler_service: Service used to generate daily schedules.
		owners_by_id: Dictionary mapping owner IDs to owner profiles.
		schedules_by_owner_date: Dictionary mapping (owner_id, date) tuples
			to generated daily schedules.
	"""
	def __init__(self) -> None:
		"""Initialize the pet care application with empty data structures."""
		self.scheduler_service = SchedulerService()
		self.scheduler_agent: SchedulerAgent = DeterministicSchedulerAgent(self.scheduler_service)
		self.explanation_agent: ExplanationAgent = DeterministicExplanationAgent()
		self.retrieval_corpus = LocalRetrievalCorpus()
		self.owners_by_id: dict[UUID, Owner] = {}
		self.schedules_by_owner_date: dict[tuple[UUID, date], DailySchedule] = {}
		self.task_completion_by_owner_date: dict[tuple[UUID, date, UUID], datetime | None] = {}
		self.planning_retry_config = OrchestrationRetryConfig()
		self.planning_telemetry_by_owner_date: dict[tuple[UUID, date], list[AgentTelemetry]] = {}
		self.planning_logs_by_owner_date: dict[tuple[UUID, date], list[str]] = {}
		self.planning_loop_diagnostics_by_owner_date: dict[tuple[UUID, date], list[PlanningLoopDiagnostic]] = {}

	def _build_planning_context(self, owner_id: UUID, owner: Owner, schedule_date: date) -> PlanningContext:
		"""Build deterministic planning context for the orchestration loop."""
		return PlanningContext(owner_id=owner_id, owner=owner, schedule_date=schedule_date)

	def _build_retrieval_corpus(self, owner: Owner, schedule_date: date) -> LocalRetrievalCorpus:
		"""Create a small local corpus from preferences, routines, outcomes, and policies."""
		corpus = LocalRetrievalCorpus()

		corpus.extend(
			[
				RetrievalSnippet(
					source_type="policy",
					source_label="hard_constraints",
					content="; ".join(HARD_CONSTRAINT_RULES),
					metadata={"is_policy": True},
				),
				RetrievalSnippet(
					source_type="policy",
					source_label="fallback_policy",
					content=DETERMINISTIC_FALLBACK_POLICY,
					metadata={"is_policy": True},
				),
				RetrievalSnippet(
					source_type="policy",
					source_label="source_of_truth",
					content=SCHEDULE_SOURCE_OF_TRUTH,
					metadata={"is_policy": True},
				),
			]
		)

		if owner.preference is not None:
			corpus.add(
				RetrievalSnippet(
					source_type="owner_preference",
					source_label=str(owner.owner_id),
					content=(
						f"avoid_late_night={owner.preference.avoid_late_night}; "
						f"max_tasks_per_block={owner.preference.max_tasks_per_block}; "
						f"preferred_task_order={owner.preference.preferred_task_order}; "
						f"notification_lead_min={owner.preference.notification_lead_min}"
					),
				)
			)

		routine_snippets: list[RetrievalSnippet] = []
		for pet in owner.pets:
			for task in pet.tasks:
				routine_snippets.append(
					RetrievalSnippet(
						source_type="routine",
						source_label=f"{pet.name}:{task.title}",
						content=(
							f"{task.title} for {pet.name} ({task.category.value}), duration={task.duration_min}m, "
							f"priority={task.priority}, flexible={task.is_flexible}, frequency={task.frequency.value}"
						),
						metadata={"pet_id": str(pet.pet_id), "task_id": str(task.task_id)},
					)
				)
		corpus.extend(routine_snippets)

		recent_schedules = [
			(schedule_date_key, schedule)
			for schedule_date_key, schedule in sorted(owner.schedules_by_date.items(), key=lambda entry: entry[0], reverse=True)
			if schedule_date_key < schedule_date
		][:3]
		for recent_date, schedule in recent_schedules:
			corpus.add(
				RetrievalSnippet(
					source_type="recent_outcome",
					source_label=recent_date.isoformat(),
					content=(
						f"scheduled_count={len(schedule.items)}; unscheduled_count={schedule.planning_metadata.get('unscheduled_count', 0)}; "
						f"strategy={schedule.planning_metadata.get('strategy', 'unknown')}"
					),
					metadata={"is_recent": True, "schedule_id": str(schedule.schedule_id)},
				)
			)

		return corpus

	def _retrieve_context_snippets(self, owner: Owner, schedule_date: date, query: str, top_k: int = 3) -> list[RetrievalSnippet]:
		corpus = self._build_retrieval_corpus(owner, schedule_date)
		return corpus.retrieve(query=query, top_k=top_k)

	def _augment_task_validation_result(
		self,
		owner: Owner,
		pet_id: UUID,
		task: CareTask,
		validation_result: ValidationResult,
	) -> ValidationResult:
		if validation_result.passed:
			return validation_result

		retrieved_snippets = self._retrieve_context_snippets(
			owner=owner,
			schedule_date=date.today(),
			query=f"{task.title} {task.category.value} {task.frequency.value} {' '.join(validation_result.repair_hints)}",
			top_k=2,
		)
		routine_snippets = [snippet for snippet in retrieved_snippets if snippet.source_type == "routine"]
		if routine_snippets:
			validation_result.repair_hints.append(
				f"Normalization suggestion from retrieval: align this task with {routine_snippets[0].attribution} -> {routine_snippets[0].content}."
			)
		for snippet in retrieved_snippets:
			hint = f"Retrieved correction hint from {snippet.attribution}: {snippet.content}"
			if hint not in validation_result.repair_hints:
				validation_result.repair_hints.append(hint)
		return validation_result

	def _run_scheduler_agent_wrapper(
		self,
		context: PlanningContext,
	) -> tuple[ScheduleCandidate, DailySchedule, int]:
		"""Scheduler Agent wrapper that currently delegates to scheduler service."""
		agent_output = self.scheduler_agent.propose_candidate(context)
		retrieved_snippets = self._retrieve_context_snippets(
			owner=context.owner,
			schedule_date=context.schedule_date,
			query=f"{agent_output.candidate.rationale_summary} {' '.join(agent_output.candidate.reason_codes)} {' '.join(HARD_CONSTRAINT_RULES)}",
			top_k=2,
		)
		if retrieved_snippets:
			agent_output.candidate.rationale_metadata = dict(agent_output.candidate.rationale_metadata)
			agent_output.candidate.rationale_metadata["retrieval_hints"] = [
				{
					"attribution": snippet.attribution,
					"content": snippet.content,
					"score": snippet.score,
				}
				for snippet in retrieved_snippets
			]
			agent_output.baseline_schedule.planning_metadata = dict(agent_output.baseline_schedule.planning_metadata)
			agent_output.baseline_schedule.planning_metadata["retrieval_hint_count"] = len(retrieved_snippets)
		return (
			agent_output.candidate,
			agent_output.baseline_schedule,
			agent_output.duration_ms,
		)

	def _build_candidate_from_schedule(self, schedule: DailySchedule) -> ScheduleCandidate:
		"""Build a minimal candidate view from a concrete schedule for explanation grounding."""
		reason_codes = tuple(schedule.planning_metadata.get("reason_codes", []))
		return ScheduleCandidate(
			proposed_items=list(schedule.items),
			objective_score=float(len(schedule.items)),
			rationale_summary="Derived from deterministic schedule state.",
			planning_summary_metadata=dict(schedule.planning_metadata),
			reason_codes=reason_codes,
			generated_by=AgentRole.SCHEDULER,
			advisory_only=AGENT_OUTPUTS_ADVISORY_ONLY,
		)

	def _annotate_repair_strategy(self, schedule: DailySchedule, strategy: str, detail: str = "") -> DailySchedule:
		"""Tag repaired schedules with phase-5 metadata for observability and tests."""
		schedule.planning_metadata = dict(schedule.planning_metadata)
		schedule.planning_metadata["phase5_repair_strategy"] = strategy
		if detail:
			schedule.planning_metadata["phase5_repair_detail"] = detail
		return schedule

	def _build_validation_critique(self, validation_result: ValidationResult) -> str:
		"""Summarize failed validation results for the repair loop."""
		violation_codes = ", ".join(violation.code for violation in validation_result.violations) or "UNKNOWN"
		messages = "; ".join(violation.message for violation in validation_result.violations) or "Validation failed without messages."
		hints = " | ".join(validation_result.repair_hints) if validation_result.repair_hints else "No repair hints available."
		return f"Violations [{violation_codes}]: {messages}. Repair hints: {hints}"

	def _refresh_schedule_totals(self, schedule: DailySchedule) -> DailySchedule:
		"""Recompute schedule totals after repairs mutate the item list."""
		schedule.total_planned_min = sum(
			int((item.end_time - item.start_time).total_seconds() // 60)
			for item in schedule.items
			if item.start_time is not None and item.end_time is not None
		)
		return schedule

	def _apply_lightweight_repair(self, schedule: DailySchedule) -> DailySchedule:
		"""Lightweight repair: regenerate invalid or overlapping items in place."""
		schedule.regenerate()
		return self._annotate_repair_strategy(schedule, "lightweight", "regenerate_invalid_and_overlapping_items")

	def _apply_targeted_repair(
		self,
		schedule: DailySchedule,
		owner: Owner,
		schedule_date: date,
	) -> DailySchedule:
		"""Targeted repair: move flexible tasks into the earliest feasible open slots."""
		day_windows, _ = self.scheduler_service._resolve_day_windows(owner, schedule_date)
		if not day_windows:
			return self._annotate_repair_strategy(schedule, "targeted", "no_day_windows_available")

		ordered_items = [
			item
			for item in sorted(schedule.items, key=lambda scheduled_item: scheduled_item.start_time or datetime.min)
			if item.task is not None and item.start_time is not None and item.end_time is not None
		]
		fixed_items = [item for item in ordered_items if not item.task.is_flexible]
		flexible_items = [item for item in ordered_items if item.task.is_flexible]

		repaired_items: list[ScheduleItem] = list(fixed_items)
		flexible_items.sort(
			key=lambda item: (
				-(item.task.priority if item.task is not None else 0),
				item.task.latest_end or time(hour=23, minute=59) if item.task is not None else time(hour=23, minute=59),
				item.task.earliest_start or time(hour=0, minute=0) if item.task is not None else time(hour=0, minute=0),
			)
		)

		for item in flexible_items:
			if item.task is None:
				continue
			slot, _ = self.scheduler_service._find_earliest_slot(
				item.task,
				schedule_date,
				day_windows,
				repaired_items,
			)
			if slot is None:
				repaired_items.append(item)
				continue

			start_dt, end_dt = slot
			repaired_items.append(
				replace(
					item,
					start_time=start_dt,
					end_time=end_dt,
					reason_code="REPAIRED_TARGETED_FLEX_MOVE",
				)
			)

		schedule.items = sorted(repaired_items, key=lambda item: item.start_time or datetime.min)
		self._refresh_schedule_totals(schedule)
		return self._annotate_repair_strategy(schedule, "targeted", "rescheduled_flexible_items")

	def _apply_structural_repair(self, owner: Owner, schedule_date: date) -> DailySchedule:
		"""Structural repair: reschedule blocked segments using the deterministic baseline scheduler."""
		repaired_schedule = self.scheduler_service.generate_daily_schedule(owner, schedule_date)
		return self._annotate_repair_strategy(repaired_schedule, "structural", "recomputed_deterministic_schedule")

	def _should_attempt_phase5_repair(self, candidate: ScheduleCandidate, validation_result: ValidationResult) -> bool:
		"""Return True when the self-check loop should try repair strategies before retrying."""
		if candidate.planning_summary_metadata.get("phase5_force_repair"):
			return True

		repairable_codes = {"NO_OVERLAP", "OUTSIDE_AVAILABILITY", "RIGID_START_WINDOW", "RIGID_END_WINDOW"}
		return any(violation.code in repairable_codes for violation in validation_result.violations)

	def _repair_schedule_candidate(
		self,
		owner: Owner,
		schedule_date: date,
		validation_result: ValidationResult,
		baseline_schedule: DailySchedule,
		loop_logs: list[str],
		diagnostics: list[PlanningLoopDiagnostic],
		attempt_number: int,
	) -> tuple[ScheduleCandidate, DailySchedule, ValidationResult, str | None]:
		"""Apply the phase-5 repair ladder until a repaired candidate validates or the ladder is exhausted."""
		critique = self._build_validation_critique(validation_result)
		current_schedule = baseline_schedule
		for strategy_name in ("lightweight", "targeted", "structural"):
			if strategy_name == "lightweight":
				current_schedule = self._apply_lightweight_repair(current_schedule)
			elif strategy_name == "targeted":
				current_schedule = self._apply_targeted_repair(current_schedule, owner, schedule_date)
			else:
				current_schedule = self._apply_structural_repair(owner, schedule_date)

			repaired_schedule = current_schedule
			repaired_candidate = self._build_candidate_from_schedule(repaired_schedule)
			repaired_result = validate_schedule_candidate(repaired_candidate, owner, schedule_date)
			diagnostics.append(
				PlanningLoopDiagnostic(
					attempt=attempt_number,
					stage="repair",
					validation_status="pass" if repaired_result.passed else "fail",
					violation_codes=tuple(violation.code for violation in repaired_result.violations),
					critique_summary=critique,
					repair_strategy=strategy_name,
					repaired_validation_status="pass" if repaired_result.passed else "fail",
					detail=f"{strategy_name} repair {'succeeded' if repaired_result.passed else 'did not satisfy validation'}.",
				)
			)
			loop_logs.append(
				f"Iteration {attempt_number}: repair strategy {strategy_name} {'passed' if repaired_result.passed else 'failed'} validation."
			)
			if repaired_result.passed:
				return repaired_candidate, repaired_schedule, repaired_result, strategy_name

		return self._build_candidate_from_schedule(baseline_schedule), baseline_schedule, validation_result, None

	def _apply_explanation_agent(
		self,
		context: PlanningContext,
		candidate: ScheduleCandidate,
		schedule: DailySchedule,
	) -> DailySchedule:
		"""Expand explanations after scheduling while preserving PlanExplanation list compatibility."""
		retrieved_snippets = self._retrieve_context_snippets(
			owner=context.owner,
			schedule_date=context.schedule_date,
			query=f"{candidate.rationale_summary} {' '.join(candidate.reason_codes)} {schedule.planning_metadata.get('strategy', '')} {schedule.planning_metadata.get('ordering_policy', '')}",
			top_k=3,
		)
		schedule.explanations = self.explanation_agent.expand_explanations(
			context=context,
			candidate=candidate,
			schedule=schedule,
			retrieved_snippets=retrieved_snippets,
		)
		self.scheduler_service.explanations_by_schedule_id[schedule.schedule_id] = schedule.explanations
		return schedule

	def _should_stop_retry(self, result: ValidationResult) -> bool:
		"""Return True when retry loop should stop after a failed validation."""
		if not result.repair_hints:
			return True

		repairable_critical_codes = {"NO_OVERLAP", "OUTSIDE_AVAILABILITY", "RIGID_START_WINDOW", "RIGID_END_WINDOW"}
		critical_violations = [
			violation
			for violation in result.violations
			if violation.severity in self.planning_retry_config.stop_on_severities
		]
		if not critical_violations:
			return False
		if any(violation.code not in repairable_critical_codes for violation in critical_violations):
			return True

		return False

	def _orchestrate_daily_planning(self, owner_id: UUID, owner: Owner, schedule_date: date) -> DailySchedule:
		"""Run the phase-5 self-check loop around existing scheduler behavior."""
		context = self._build_planning_context(owner_id=owner_id, owner=owner, schedule_date=schedule_date)
		telemetry_entries: list[AgentTelemetry] = []
		loop_logs: list[str] = []
		diagnostics: list[PlanningLoopDiagnostic] = []

		for attempt in range(self.planning_retry_config.max_retries + 1):
			candidate, baseline_schedule, duration_ms = self._run_scheduler_agent_wrapper(context)
			validation_result = validate_schedule_candidate(candidate, owner, schedule_date)
			attempt_number = attempt + 1
			critique = self._build_validation_critique(validation_result) if not validation_result.passed else "Candidate passed validation."
			diagnostics.append(
				PlanningLoopDiagnostic(
					attempt=attempt_number,
					stage="validate",
					validation_status="pass" if validation_result.passed else "fail",
					violation_codes=tuple(violation.code for violation in validation_result.violations),
					critique_summary=critique,
					detail="Initial candidate validation.",
				)
			)

			if validation_result.passed:
				loop_logs.append(
					f"Iteration {attempt_number}: candidate passed validation and was accepted."
				)
				telemetry_entries.append(
					AgentTelemetry(
						agent_role=AgentRole.SCHEDULER,
						retries=attempt,
						duration_ms=duration_ms,
					)
				)
				self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
				self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
				self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
				return self._apply_explanation_agent(
					context=context,
					candidate=candidate,
					schedule=baseline_schedule,
				)

			violation_codes = ", ".join(v.code for v in validation_result.violations) or "UNKNOWN"
			loop_logs.append(
				f"Iteration {attempt_number}: candidate failed validation with violations [{violation_codes}]."
			)
			loop_logs.append(f"Iteration {attempt_number}: critique summary -> {critique}")

			exhausted_retries = attempt >= self.planning_retry_config.max_retries
			stop_retry = self._should_stop_retry(validation_result)
			use_fallback = self.planning_retry_config.fallback_on_validation_failure and stop_retry

			if not use_fallback and self._should_attempt_phase5_repair(candidate, validation_result):
				repaired_candidate, repaired_schedule, repaired_result, repair_strategy = self._repair_schedule_candidate(
					owner=owner,
					schedule_date=schedule_date,
					validation_result=validation_result,
					baseline_schedule=baseline_schedule,
					loop_logs=loop_logs,
					diagnostics=diagnostics,
					attempt_number=attempt_number,
				)
				if repaired_result.passed:
					loop_logs.append(
						f"Iteration {attempt_number}: repair strategy {repair_strategy} produced a valid schedule."
					)
					telemetry_entries.append(
						AgentTelemetry(
							agent_role=AgentRole.SCHEDULER,
							retries=attempt,
							duration_ms=duration_ms,
						)
					)
					self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
					self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
					self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
					return self._apply_explanation_agent(
						context=context,
						candidate=repaired_candidate,
						schedule=repaired_schedule,
					)

				loop_logs.append(f"Iteration {attempt_number}: all repair strategies failed; retry scheduled.")
				if exhausted_retries:
					use_fallback = True
					fallback_reason = "max_retries_exhausted"
					diagnostics.append(
						PlanningLoopDiagnostic(
							attempt=attempt_number,
							stage="fallback",
							validation_status="fail",
							violation_codes=tuple(violation.code for violation in validation_result.violations),
							critique_summary=critique,
							repair_strategy="fallback",
							repaired_validation_status="fail",
							fallback_used=True,
							detail="Retry budget exhausted after repair ladder failure.",
						)
					)
				else:
					telemetry_entries.append(
						AgentTelemetry(
							agent_role=AgentRole.SCHEDULER,
							retries=attempt,
							duration_ms=duration_ms,
						)
					)
					self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
					self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
					self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
					continue

			if not use_fallback and not exhausted_retries:
				telemetry_entries.append(
					AgentTelemetry(
						agent_role=AgentRole.SCHEDULER,
						retries=attempt,
						duration_ms=duration_ms,
					)
				)
				self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
				self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
				self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
				loop_logs.append(f"Iteration {attempt_number}: retry scheduled.")
				continue

			fallback_reason = ""
			if use_fallback:
				fallback_reason = "stop_condition_triggered"
				loop_logs.append(
					f"Iteration {attempt_number}: deterministic fallback triggered ({fallback_reason})."
				)
				diagnostics.append(
					PlanningLoopDiagnostic(
						attempt=attempt_number,
						stage="fallback",
						validation_status="fail",
						violation_codes=tuple(violation.code for violation in validation_result.violations),
						critique_summary=critique,
						repair_strategy="fallback",
						repaired_validation_status="fail",
						fallback_used=True,
						detail="Validation failure triggered deterministic fallback before exhausting retries.",
					)
				)

			telemetry_entries.append(
				AgentTelemetry(
					agent_role=AgentRole.SCHEDULER,
					retries=attempt,
					fallback_reason=fallback_reason,
					duration_ms=duration_ms,
					used_deterministic_fallback=use_fallback,
				)
			)

			if use_fallback:
				fallback_schedule = self.scheduler_service.generate_daily_schedule(owner, schedule_date)
				self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
				self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
				self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
				fallback_candidate = self._build_candidate_from_schedule(fallback_schedule)
				return self._apply_explanation_agent(
					context=context,
					candidate=fallback_candidate,
					schedule=fallback_schedule,
				)

			loop_logs.append(f"Iteration {attempt_number}: retry scheduled.")

		# Defensive fallback; loop should always return before this line.
		fallback_schedule = self.scheduler_service.generate_daily_schedule(owner, schedule_date)
		telemetry_entries.append(
			AgentTelemetry(
				agent_role=AgentRole.SCHEDULER,
				retries=self.planning_retry_config.max_retries,
				fallback_reason="defensive_fallback_after_loop",
				used_deterministic_fallback=True,
			)
		)
		loop_logs.append("Deterministic fallback triggered after loop completion.")
		self.planning_telemetry_by_owner_date[(owner_id, schedule_date)] = telemetry_entries
		self.planning_logs_by_owner_date[(owner_id, schedule_date)] = loop_logs
		self.planning_loop_diagnostics_by_owner_date[(owner_id, schedule_date)] = diagnostics
		fallback_candidate = self._build_candidate_from_schedule(fallback_schedule)
		return self._apply_explanation_agent(
			context=context,
			candidate=fallback_candidate,
			schedule=fallback_schedule,
		)

	def create_owner_profile(self) -> Owner:
		"""Create a new owner profile and register it with the application.
		
		Returns:
			A new Owner object with auto-generated ID.
		"""
		owner = Owner()
		self.owners_by_id[owner.owner_id] = owner
		return owner

	def save_owner_info(self, owner: Owner) -> None:
		"""Save or update owner information in the application.
		
		Args:
			owner: The owner object to save.
		"""
		self.owners_by_id[owner.owner_id] = owner

	def save_pet_info(self, owner_id: UUID, pet: Pet) -> None:
		"""Add a new pet to an owner's profile.
		
		Args:
			owner_id: ID of the owner.
			pet: The pet to add.
		
		Raises:
			ValueError: If the owner is not found.
		"""
		owner = self.owners_by_id.get(owner_id)
		if owner is None:
			raise ValueError("Owner not found")
		owner.add_pet(pet)

	def add_task(self, owner_id: UUID, pet_id: UUID, task: CareTask) -> ValidationResult:
		"""Add task through app API with guardrail result surfaced to callers."""
		owner = self.owners_by_id.get(owner_id)
		if owner is None:
			raise ValueError("Owner not found")

		try:
			owner.add_task(pet_id, task)
		except TaskValidationError as exc:
			self._augment_task_validation_result(owner, pet_id, task, exc.result)
			raise TaskValidationError(exc.result) from None
		return ValidationResult(status="pass")

	def edit_task(self, owner_id: UUID, task_id: UUID, **changes: Any) -> ValidationResult:
		"""Edit task through app API with guardrail result surfaced to callers."""
		owner = self.owners_by_id.get(owner_id)
		if owner is None:
			raise ValueError("Owner not found")

		try:
			owner.edit_task(task_id, **changes)
		except TaskValidationError as exc:
			pet_id = owner.task_to_pet.get(task_id)
			original_pet = owner._get_pet_by_id(pet_id) if pet_id is not None else None
			candidate_task = None
			if original_pet is not None:
				for existing_task in original_pet.tasks:
					if existing_task.task_id == task_id:
						candidate_task = replace(existing_task)
						for field_name, field_value in changes.items():
							setattr(candidate_task, field_name, field_value)
						break
			if candidate_task is not None and pet_id is not None:
				self._augment_task_validation_result(owner, pet_id, candidate_task, exc.result)
			raise TaskValidationError(exc.result) from None
		return ValidationResult(status="pass")

	def run_daily_planning(self, owner_id: UUID, schedule_date: date) -> DailySchedule:
		"""Generate and save a daily schedule for an owner.
		
		Args:
			owner_id: ID of the owner to generate schedule for.
			schedule_date: The date to schedule.
		
		Returns:
			The generated DailySchedule.
		
		Raises:
			ValueError: If the owner is not found.
		"""
		owner = self.owners_by_id.get(owner_id)
		if owner is None:
			raise ValueError("Owner not found")

		# Preserve completion state for tasks that remain after regeneration.
		previous_schedule = self.schedules_by_owner_date.get((owner_id, schedule_date))

		schedule = self._orchestrate_daily_planning(owner_id=owner_id, owner=owner, schedule_date=schedule_date)

		if previous_schedule is not None:
			for previous_item in previous_schedule.items:
				if previous_item.task is None:
					continue
				completion_key = (owner_id, schedule_date, previous_item.task.task_id)
				if previous_item.completed:
					self.task_completion_by_owner_date[completion_key] = previous_item.completed_at
				else:
					self.task_completion_by_owner_date.pop(completion_key, None)

		for item in schedule.items:
			if item.task is None:
				continue
			completion_key = (owner_id, schedule_date, item.task.task_id)
			completed_at = self.task_completion_by_owner_date.get(completion_key)
			if completion_key in self.task_completion_by_owner_date:
				item.completed = True
				item.completed_at = completed_at

		self.schedules_by_owner_date[(owner_id, schedule_date)] = schedule
		owner.schedules_by_date[schedule_date] = schedule
		return schedule

	def mark_task_completion(
		self,
		owner_id: UUID,
		schedule_date: date,
		item_id: UUID,
		completed: bool = True,
		when: datetime | None = None,
	) -> None:
		"""Mark a scheduled task item as completed or incomplete.
		
		Args:
			owner_id: ID of the owner.
			schedule_date: Date of the schedule containing the item.
			item_id: ID of the schedule item to update.
			completed: If True, mark as completed; if False, mark as incomplete.
			when: Timestamp of completion (used only if completed=True).
		
		Raises:
			ValueError: If the schedule or item is not found.
		"""
		schedule = self.schedules_by_owner_date.get((owner_id, schedule_date))
		if schedule is None:
			raise ValueError("Schedule not found")
		schedule.mark_item_completion(item_id=item_id, completed=completed, when=when)

		for item in schedule.items:
			if item.item_id != item_id or item.task is None:
				continue
			completion_key = (owner_id, schedule_date, item.task.task_id)
			if completed:
				self.task_completion_by_owner_date[completion_key] = item.completed_at
			else:
				self.task_completion_by_owner_date.pop(completion_key, None)
			break
