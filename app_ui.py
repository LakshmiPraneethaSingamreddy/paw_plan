from __future__ import annotations

from datetime import date, time

import streamlit as st

from app_agents import render_ai_explanation_section
from app_helpers import (
	build_plan_explanation_lines,
	build_schedule_warning_messages,
	filter_task_pairs_for_display,
	get_schedule_conflicts,
	show_task_guardrail_feedback,
	sort_schedule_items_for_display,
	sort_task_pairs_for_display,
)
from pawpal_system import CareTask, Frequency, TaskCategory, TaskValidationError


def render_task_management_section(
	*,
	owner,
	selected_pet_id,
	pet_by_id,
	priority_to_score,
	weekday_labels,
) -> None:
	st.divider()

	st.markdown("### Tasks")
	st.caption("Add a few tasks. In your final version, these should feed into your scheduler.")

	col1, col2, col3 = st.columns(3)
	with col1:
		task_title = st.text_input("Task title", value="Morning walk")
	with col2:
		duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
	with col3:
		priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)

	task_col1, task_col2, task_col3 = st.columns(3)
	with task_col1:
		task_category = st.selectbox("Category", options=[category.name for category in TaskCategory], index=1)
	with task_col2:
		task_frequency = st.selectbox("Frequency", options=[freq.name for freq in Frequency], index=0)
	with task_col3:
		is_flexible = st.checkbox("Flexible task", value=True)

	weekly_day_of_week: int | None = None
	custom_days_of_week: list[int] = []
	custom_interval_days: int | None = None
	custom_anchor_date = None

	if task_frequency == Frequency.WEEKLY.name:
		weekly_day_label = st.selectbox(
			"Weekly day",
			options=weekday_labels,
			index=date.today().weekday(),
		)
		weekly_day_of_week = weekday_labels.index(weekly_day_label)
	elif task_frequency == Frequency.CUSTOM.name:
		custom_mode = st.selectbox(
			"Custom recurrence mode",
			options=["Selected weekdays", "Every N days"],
		)
		if custom_mode == "Selected weekdays":
			selected_custom_days = st.multiselect(
				"Custom weekdays",
				options=weekday_labels,
				default=[weekday_labels[date.today().weekday()]],
			)
			custom_days_of_week = [weekday_labels.index(day) for day in selected_custom_days]
		else:
			custom_interval_days = st.number_input(
				"Repeat every N days",
				min_value=1,
				max_value=90,
				value=2,
			)
			custom_anchor_date = st.date_input("Custom recurrence anchor date", value=date.today())

	time_col1, time_col2 = st.columns(2)
	with time_col1:
		earliest_start = st.time_input("Earliest start", value=time(hour=8, minute=0))
	with time_col2:
		latest_end = st.time_input("Latest end", value=time(hour=20, minute=0))

	task_notes = st.text_area("Task notes", value="")

	selected_task_category = TaskCategory[task_category]
	selected_task_frequency = Frequency[task_frequency]
	priority_to_label = {1: "low", 2: "medium", 3: "high"}
	label_to_priority = {"low": 1, "medium": 2, "high": 3}

	if st.button("Add task"):
		target_pet_id = selected_pet_id or st.session_state.pet_id
		if target_pet_id is None:
			st.error("Add a pet first, then add tasks.")
		else:
			task = CareTask(
				title=task_title,
				category=selected_task_category,
				duration_min=int(duration),
				priority=priority_to_score[priority],
				frequency=selected_task_frequency,
				weekly_day_of_week=weekly_day_of_week,
				custom_days_of_week=custom_days_of_week,
				custom_interval_days=int(custom_interval_days) if custom_interval_days is not None else None,
				custom_anchor_date=custom_anchor_date,
				earliest_start=earliest_start,
				latest_end=latest_end,
				is_flexible=is_flexible,
				notes=task_notes,
			)
			try:
				st.session_state.petcare_app.add_task(st.session_state.owner_id, target_pet_id, task)
				st.session_state.pet_id = target_pet_id
				st.session_state.petcare_app.save_owner_info(owner)
				st.success("Task added.")
			except TaskValidationError as validation_error:
				show_task_guardrail_feedback(validation_error)
			except ValueError as value_error:
				st.error(str(value_error))

	st.divider()

	st.markdown("### View and Filter Tasks")
	scheduler_service = st.session_state.petcare_app.scheduler_service

	# Gather all tasks from all pets with pet name metadata
	all_tasks_with_pets = []
	for pet in owner.pets:
		for task in pet.tasks:
			all_tasks_with_pets.append((pet, task))

	if all_tasks_with_pets:
		# Filter controls
		filter_col1, filter_col2 = st.columns(2)
		with filter_col1:
			pet_filter_options = ["All Pets"] + [pet.name or f"Pet {idx}" for idx, pet in enumerate(owner.pets)]

			# Initialize filter in session state if not present
			if "task_view_pet_filter" not in st.session_state:
				st.session_state.task_view_pet_filter = "All Pets"

			selected_pet_filter = st.selectbox(
				"Filter by pet",
				options=pet_filter_options,
				key="task_view_pet_filter",
			)

		with filter_col2:
			# Initialize flexibility filter in session state if not present
			if "task_view_flexibility_filter" not in st.session_state:
				st.session_state.task_view_flexibility_filter = "All Tasks"

			flexibility_filter = st.selectbox(
				"Filter by flexibility",
				options=["All Tasks", "Flexible Only", "Non-flexible Only"],
				key="task_view_flexibility_filter",
			)

		selected_pet_id_filter = None
		if selected_pet_filter != "All Pets":
			selected_pet_idx = pet_filter_options.index(selected_pet_filter) - 1
			selected_pet_id_filter = owner.pets[selected_pet_idx].pet_id

		flexibility_map = {
			"All Tasks": None,
			"Flexible Only": True,
			"Non-flexible Only": False,
		}
		filtered_tasks_with_pets = filter_task_pairs_for_display(
			all_tasks_with_pets,
			scheduler_service=scheduler_service,
			pet_id=selected_pet_id_filter,
			flexible_only=flexibility_map[flexibility_filter],
		)
		sorted_filtered = sort_task_pairs_for_display(filtered_tasks_with_pets, scheduler_service)

		st.success(f"Showing {len(sorted_filtered)} task(s) after applying filters.")

		if "editing_task_id" not in st.session_state:
			st.session_state.editing_task_id = None

		priority_to_label = {1: "low", 2: "medium", 3: "high"}
		label_to_priority = {"low": 1, "medium": 2, "high": 3}

		header_cols = st.columns([1.2, 1.8, 1.0, 0.8, 0.9, 0.9, 1.6, 0.9, 0.8, 0.9, 1.1, 1.3])
		header_labels = [
			"Pet",
			"Title",
			"Category",
			"Mins",
			"Priority",
			"Freq",
			"Recurrence",
			"Start",
			"End",
			"Flexible",
			"Edit",
			"Remove",
		]
		for col, label in zip(header_cols, header_labels):
			with col:
				st.caption(f"**{label}**")

		for pet, task in sorted_filtered:
			recurrence_text = (
				f"weekly:{weekday_labels[task.weekly_day_of_week]}"
				if task.frequency == Frequency.WEEKLY and task.weekly_day_of_week is not None
				else (
					f"{','.join(weekday_labels[day] for day in task.custom_days_of_week)}"
					if task.frequency == Frequency.CUSTOM and task.custom_days_of_week
					else (
						f"every {task.custom_interval_days} day(s)"
						if task.frequency == Frequency.CUSTOM and task.custom_interval_days is not None
						else ""
					)
				)
			)

			row_cols = st.columns([1.2, 1.8, 1.0, 0.8, 0.9, 0.9, 1.6, 0.9, 0.8, 0.9, 1.1, 1.3])
			with row_cols[0]:
				st.write(pet.name or "Unknown")
			with row_cols[1]:
				st.write(task.title)
			with row_cols[2]:
				st.write(task.category.value)
			with row_cols[3]:
				st.write(str(task.duration_min))
			with row_cols[4]:
				st.write(str(task.priority))
			with row_cols[5]:
				st.write(task.frequency.value)
			with row_cols[6]:
				st.write(recurrence_text or "-")
			with row_cols[7]:
				st.write(task.earliest_start.strftime("%H:%M") if task.earliest_start else "-")
			with row_cols[8]:
				st.write(task.latest_end.strftime("%H:%M") if task.latest_end else "-")
			with row_cols[9]:
				st.write("Yes" if task.is_flexible else "No")
			with row_cols[10]:
				if st.button("Edit", key=f"task_row_edit_{task.task_id}"):
					st.session_state.editing_task_id = str(task.task_id)
					st.rerun()
			with row_cols[11]:
				if st.button("Remove", key=f"task_row_remove_{task.task_id}"):
					owner.remove_task(task.task_id)
					st.session_state.petcare_app.save_owner_info(owner)
					if st.session_state.editing_task_id == str(task.task_id):
						st.session_state.editing_task_id = None
					st.success(f"Removed task '{task.title}'.")
					st.rerun()

			if st.session_state.editing_task_id == str(task.task_id):
				st.markdown(f"Edit task: **{task.title}**")

				edit_col1, edit_col2, edit_col3 = st.columns(3)
				with edit_col1:
					edit_task_title = st.text_input("Task title", value=task.title, key=f"edit_task_title_{task.task_id}")
				with edit_col2:
					edit_duration = st.number_input(
						"Duration (minutes)",
						min_value=1,
						max_value=240,
						value=int(task.duration_min),
						key=f"edit_duration_{task.task_id}",
					)
				with edit_col3:
					edit_priority = st.selectbox(
						"Priority",
						["low", "medium", "high"],
						index=["low", "medium", "high"].index(priority_to_label.get(task.priority, "medium")),
						key=f"edit_priority_{task.task_id}",
					)

				edit_meta_col1, edit_meta_col2, edit_meta_col3 = st.columns(3)
				with edit_meta_col1:
					edit_task_category = st.selectbox(
						"Category",
						options=[category.name for category in TaskCategory],
						index=[category.name for category in TaskCategory].index(task.category.name),
						key=f"edit_category_{task.task_id}",
					)
				with edit_meta_col2:
					edit_task_frequency = st.selectbox(
						"Frequency",
						options=[freq.name for freq in Frequency],
						index=[freq.name for freq in Frequency].index(task.frequency.name),
						key=f"edit_frequency_{task.task_id}",
					)
				with edit_meta_col3:
					edit_is_flexible = st.checkbox(
						"Flexible task",
						value=task.is_flexible,
						key=f"edit_is_flexible_{task.task_id}",
					)

				edit_weekly_day_of_week: int | None = None
				edit_custom_days_of_week: list[int] = []
				edit_custom_interval_days: int | None = None
				edit_custom_anchor_date = None

				if edit_task_frequency == Frequency.WEEKLY.name:
					edit_weekly_day_label = st.selectbox(
						"Weekly day",
						options=weekday_labels,
						index=task.weekly_day_of_week if task.weekly_day_of_week is not None else date.today().weekday(),
						key=f"edit_weekly_day_of_week_{task.task_id}",
					)
					edit_weekly_day_of_week = weekday_labels.index(edit_weekly_day_label)
				elif edit_task_frequency == Frequency.CUSTOM.name:
					default_custom_mode = "Every N days" if task.custom_interval_days is not None else "Selected weekdays"
					edit_custom_mode = st.selectbox(
						"Custom recurrence mode",
						options=["Selected weekdays", "Every N days"],
						index=["Selected weekdays", "Every N days"].index(default_custom_mode),
						key=f"edit_custom_mode_{task.task_id}",
					)
					if edit_custom_mode == "Selected weekdays":
						default_custom_days = (
							[weekday_labels[day] for day in task.custom_days_of_week]
							if task.custom_days_of_week
							else [weekday_labels[date.today().weekday()]]
						)
						selected_custom_days = st.multiselect(
							"Custom weekdays",
							options=weekday_labels,
							default=default_custom_days,
							key=f"edit_custom_days_of_week_{task.task_id}",
						)
						edit_custom_days_of_week = [weekday_labels.index(day) for day in selected_custom_days]
					else:
						edit_custom_interval_days = st.number_input(
							"Repeat every N days",
							min_value=1,
							max_value=90,
							value=int(task.custom_interval_days or 2),
							key=f"edit_custom_interval_days_{task.task_id}",
						)
						edit_custom_anchor_date = st.date_input(
							"Custom recurrence anchor date",
							value=task.custom_anchor_date or date.today(),
							key=f"edit_custom_anchor_date_{task.task_id}",
						)

				edit_time_col1, edit_time_col2 = st.columns(2)
				with edit_time_col1:
					edit_earliest_start = st.time_input(
						"Earliest start",
						value=task.earliest_start or time(hour=8, minute=0),
						key=f"edit_earliest_start_{task.task_id}",
					)
				with edit_time_col2:
					edit_latest_end = st.time_input(
						"Latest end",
						value=task.latest_end or time(hour=20, minute=0),
						key=f"edit_latest_end_{task.task_id}",
					)

				edit_task_notes = st.text_area("Task notes", value=task.notes, key=f"edit_task_notes_{task.task_id}")

				action_col1, action_col2 = st.columns(2)
				with action_col1:
					save_edit_clicked = st.button("Save changes", key=f"save_task_edit_{task.task_id}")
				with action_col2:
					cancel_edit_clicked = st.button("Cancel", key=f"cancel_task_edit_{task.task_id}")

				if cancel_edit_clicked:
					st.session_state.editing_task_id = None
					st.rerun()

				if save_edit_clicked:
					try:
						st.session_state.petcare_app.edit_task(
							st.session_state.owner_id,
							task.task_id,
							title=edit_task_title,
							category=TaskCategory[edit_task_category],
							duration_min=int(edit_duration),
							priority=label_to_priority[edit_priority],
							frequency=Frequency[edit_task_frequency],
							weekly_day_of_week=edit_weekly_day_of_week,
							custom_days_of_week=edit_custom_days_of_week,
							custom_interval_days=int(edit_custom_interval_days) if edit_custom_interval_days is not None else None,
							custom_anchor_date=edit_custom_anchor_date,
							earliest_start=edit_earliest_start,
							latest_end=edit_latest_end,
							is_flexible=edit_is_flexible,
							notes=edit_task_notes,
						)
						st.session_state.petcare_app.save_owner_info(owner)
						st.session_state.editing_task_id = None
						st.success(f"Updated task '{edit_task_title}'.")
						st.rerun()
					except TaskValidationError as validation_error:
						show_task_guardrail_feedback(validation_error)
					except (ValueError, AttributeError) as edit_error:
						st.error(str(edit_error))

			st.divider()
	else:
		st.info("No tasks yet. Add one above.")


def render_schedule_section(*, owner, weekday_labels) -> None:
	st.divider()

	st.subheader("Build Schedule")

	schedule_date = st.date_input("Schedule date", value=date.today())

	if st.button("Generate schedule"):
		if not owner.pets:
			st.error("Add a pet before generating a schedule.")
		elif not owner.availability_windows:
			st.error("Set at least one availability window before generating a schedule.")
		elif not any(window.day_of_week == schedule_date.weekday() for window in owner.availability_windows):
			st.session_state.last_schedule = None
			st.session_state.last_schedule_date = schedule_date
			st.warning(
				"No availability is configured for the selected weekday. Add an availability window for that day and try again."
			)
		else:
			schedule = st.session_state.petcare_app.run_daily_planning(
				owner_id=st.session_state.owner_id,
				schedule_date=schedule_date,
			)

			# Persist latest generated result (including empty schedules) to avoid stale UI.
			st.session_state.last_schedule = schedule
			st.session_state.last_schedule_date = schedule_date

			# Clear any cached AI explanation when a new schedule is generated.
			enhance_key = f"llm_expl_{st.session_state.owner_id}_{schedule_date.isoformat()}"
			if enhance_key in st.session_state:
				del st.session_state[enhance_key]

			if schedule.items:
				conflicts = get_schedule_conflicts(schedule, st.session_state.petcare_app.scheduler_service)
				st.success(
					f"Schedule generated for {schedule_date.isoformat()}: "
					f"{len(schedule.items)} task(s) planned."
				)
				for warning_message in build_schedule_warning_messages(schedule, conflicts=conflicts):
					st.warning(warning_message)
			else:
				for warning_message in build_schedule_warning_messages(schedule):
					st.warning(warning_message)

	# Display persisted schedule (either from fresh generation or from session state across reruns)
	if hasattr(st.session_state, 'last_schedule') and st.session_state.last_schedule is not None:
		if st.session_state.last_schedule_date == schedule_date:
			schedule = st.session_state.last_schedule

			st.markdown("### Daily Schedule - Mark tasks as complete")

			pet_name_by_id = {pet.pet_id: pet.name or "Unnamed" for pet in owner.pets}
			sorted_schedule_items = sort_schedule_items_for_display(schedule.items, st.session_state.petcare_app.scheduler_service)

			header_cols = st.columns([0.7, 2.3, 1.5, 1.6, 1.0, 1.0, 1.2])
			header_labels = ["Done", "Task", "Pet", "Time", "Priority", "Flexible", "Status"]
			for col, label in zip(header_cols, header_labels):
				with col:
					st.caption(f"**{label}**")

			# Display each task with interactive completion checkbox
			for item in sorted_schedule_items:
				col1, col2, col3, col4, col5, col6, col7 = st.columns([0.7, 2.3, 1.5, 1.6, 1.0, 1.0, 1.2])

				with col1:
					# Completion checkbox
					task_key_part = str(item.task.task_id) if item.task is not None else str(item.item_id)
					completed_state_key = (
						f"complete_{st.session_state.owner_id}_{schedule_date.isoformat()}_{task_key_part}"
					)
					is_completed = st.checkbox(
						"",
						value=item.completed,
						key=completed_state_key,
						label_visibility="collapsed",
					)

					# Update backend if completion status changed
					if is_completed != item.completed:
						st.session_state.petcare_app.mark_task_completion(
							owner_id=st.session_state.owner_id,
							schedule_date=schedule_date,
							item_id=item.item_id,
							completed=is_completed,
						)
						item.completed = is_completed

				with col2:
					# Task title with strikethrough styling if completed
					task_title = item.task.title if item.task else "Unknown task"
					if item.completed:
						st.markdown(f"~~{task_title}~~")
					else:
						st.write(task_title)

				with col3:
					st.write(f"**{pet_name_by_id.get(item.pet_id, 'Unknown Pet')}**")

				with col4:
					time_str = ""
					if item.start_time and item.end_time:
						time_str = f"{item.start_time.strftime('%H:%M')} - {item.end_time.strftime('%H:%M')}"
					st.write(time_str)

				with col5:
					st.write(str(item.task.priority) if item.task else "-")

				with col6:
					st.write("Yes" if item.task and item.task.is_flexible else "No")

				with col7:
					if item.completed and item.completed_at:
						st.caption(f"Done at {item.completed_at.strftime('%H:%M')}")
					elif item.completed:
						st.caption("Done")
					else:
						st.caption("Pending")

			# Read-only conflict detection via scheduler service helper.
			conflicts = get_schedule_conflicts(schedule, st.session_state.petcare_app.scheduler_service)
			for warning_message in build_schedule_warning_messages(schedule, conflicts=conflicts):
				st.warning(warning_message)
			if conflicts:
				st.markdown("### Conflict details")
				conflict_rows = []
				for previous_item, current_item in conflicts:
					previous_task = previous_item.task.title if previous_item.task else "Unknown task"
					current_task = current_item.task.title if current_item.task else "Unknown task"
					previous_pet = pet_name_by_id.get(previous_item.pet_id, "Unknown Pet")
					current_pet = pet_name_by_id.get(current_item.pet_id, "Unknown Pet")
					overlap_minutes = int((previous_item.end_time - current_item.start_time).total_seconds() // 60)
					suggested_fix = "Move flexible task later"
					if previous_item.task and current_item.task:
						if not previous_item.task.is_flexible and current_item.task.is_flexible:
							suggested_fix = f"Move '{current_task}' later"
						elif previous_item.task.is_flexible and not current_item.task.is_flexible:
							suggested_fix = f"Move '{previous_task}' later"
						elif previous_item.task.priority > current_item.task.priority:
							suggested_fix = f"Keep '{previous_task}' fixed first"
						elif current_item.task.priority > previous_item.task.priority:
							suggested_fix = f"Keep '{current_task}' fixed first"

					conflict_rows.append(
						{
							"Task": f"{previous_pet}: {previous_task}",
							"Time": f"{previous_item.start_time.strftime('%H:%M')} - {previous_item.end_time.strftime('%H:%M')}",
							"Conflicts With": f"{current_pet}: {current_task}",
							"Conflict Time": f"{current_item.start_time.strftime('%H:%M')} - {current_item.end_time.strftime('%H:%M')}",
							"Overlap Minutes": overlap_minutes,
							"Suggested Fix": suggested_fix,
						}
					)

				st.table(conflict_rows)
				st.info(
					"Suggested approach: keep medication/feeding fixed, and shift flexible play or grooming tasks to the next open slot."
				)

			if schedule.explanations:
				render_ai_explanation_section(schedule, st.session_state.owner_id, schedule_date)

			# --- Orchestration diagnostics ---
			telemetry_key = (st.session_state.owner_id, schedule_date)
			app = st.session_state.petcare_app
			telemetry_entries = app.planning_telemetry_by_owner_date.get(telemetry_key, [])
			loop_logs = app.planning_logs_by_owner_date.get(telemetry_key, [])
			diagnostics = app.planning_loop_diagnostics_by_owner_date.get(telemetry_key, [])

			with st.expander("Scheduler diagnostics", expanded=False):
				st.caption(
					"Shows what the scheduling engine did internally: how many attempts it made, "
					"whether any repair strategies ran, and whether it fell back to the rule-based scheduler."
				)

				if not telemetry_entries:
					st.info("No orchestration data for this schedule yet. Generate a schedule first.")
				else:
					# Summary row
					total_attempts = len(telemetry_entries)
					any_fallback = any(t.used_deterministic_fallback for t in telemetry_entries)
					total_retries = sum(t.retries for t in telemetry_entries)
					total_ms = sum(t.duration_ms for t in telemetry_entries)

					summary_cols = st.columns(4)
					summary_cols[0].metric("Attempts", total_attempts)
					summary_cols[1].metric("Retries", total_retries)
					summary_cols[2].metric("Total time (ms)", total_ms)
					summary_cols[3].metric("Fallback used", "Yes" if any_fallback else "No")

					if any_fallback:
						st.warning(
							"The AI scheduler could not produce a valid schedule within the retry budget. "
							"The final schedule was built by the rule-based fallback scheduler."
						)
					else:
						st.success("The AI scheduler produced a valid schedule without needing the fallback.")

					# Per-attempt diagnostics table
					if diagnostics:
						st.markdown("#### Per-attempt detail")
						diag_rows = []
						for d in diagnostics:
							diag_rows.append(
								{
									"Attempt": d.attempt,
									"Stage": d.stage,
									"Validation": d.validation_status,
									"Violations": ", ".join(d.violation_codes) if d.violation_codes else "none",
									"Repair strategy": d.repair_strategy or "—",
									"After repair": d.repaired_validation_status or "—",
									"Fallback": "Yes" if d.fallback_used else "No",
									"Detail": d.detail,
								}
							)
						st.dataframe(diag_rows, use_container_width=True)

					# Step-by-step loop log
					if loop_logs:
						st.markdown("#### Step-by-step loop log")
						st.code("\n".join(loop_logs), language=None)