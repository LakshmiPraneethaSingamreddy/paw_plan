"""PawPal+ Streamlit UI for owner/pet setup, task management, and daily scheduling.

This app now supports filtered and time-sorted task views, inline task edit/remove actions,
and recurrence-aware task creation (daily, weekly, and custom patterns).
It also persists generated schedules in session state, lets owners mark tasks complete,
and shows read-only conflict warnings when scheduled items overlap.
"""

import streamlit as st
from datetime import time

from app_helpers import (
    build_plan_explanation_lines,
    build_task_guardrail_feedback_lines,
    build_schedule_warning_messages,
    filter_task_pairs_for_display,
    get_schedule_conflicts,
    pet_option_label,
    show_task_guardrail_feedback,
    sort_schedule_items_for_display,
    sort_task_pairs_for_display,
)
from app_ui import render_schedule_section, render_task_management_section
from pawpal_system import AvailabilityWindow, OwnerPreference, Pet, PetCareApp, TaskValidationError


def _show_task_guardrail_feedback(error: TaskValidationError) -> None:
    """Compatibility wrapper: render task validation feedback using helpers."""
    show_task_guardrail_feedback(error)


def _build_task_guardrail_feedback_lines(error: TaskValidationError) -> list[str]:
    """Compatibility wrapper: return task guardrail violation lines."""
    return build_task_guardrail_feedback_lines(error)


def _build_schedule_warning_messages(schedule, conflicts=None) -> list[str]:
    """Compatibility wrapper: return schedule warning messages for display."""
    return build_schedule_warning_messages(schedule, conflicts=conflicts)


def _build_plan_explanation_lines(schedule) -> list[str]:
    """Compatibility wrapper: return plan explanation lines for UI."""
    return build_plan_explanation_lines(schedule)


def _filter_task_pairs_for_display(task_pairs, pet_id=None, flexible_only=None):
    """Compatibility wrapper: filter task pairs using scheduler helper if available."""
    return filter_task_pairs_for_display(
        task_pairs,
        scheduler_service=st.session_state.petcare_app.scheduler_service,
        pet_id=pet_id,
        flexible_only=flexible_only,
    )


def _sort_task_pairs_for_display(task_pairs):
    """Compatibility wrapper: sort task pairs for display using scheduler helper."""
    return sort_task_pairs_for_display(task_pairs, st.session_state.petcare_app.scheduler_service)


def _sort_schedule_items_for_display(items):
    """Compatibility wrapper: sort schedule items for display using scheduler helper."""
    return sort_schedule_items_for_display(items, st.session_state.petcare_app.scheduler_service)


def _get_schedule_conflicts(schedule):
    """Compatibility wrapper: detect schedule conflicts using scheduler helper."""
    return get_schedule_conflicts(schedule, st.session_state.petcare_app.scheduler_service)


st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

st.markdown("<h1 style='text-align: center;'>🐾 PawPal+</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center; font-style: italic; color: #666; margin-top: -10px;'>Where pet care meets perfect planning 🐾</p>",
    unsafe_allow_html=True,
)

st.divider()

st.subheader("Owner and Pet Setup")
owner_name = st.text_input("Owner name", value="Jordan")
timezone = st.text_input("Timezone", value="UTC")

if "petcare_app" not in st.session_state:
    st.session_state.petcare_app = PetCareApp()

if "owner_id" not in st.session_state:
    owner = st.session_state.petcare_app.create_owner_profile()
    owner.preference = OwnerPreference(
        max_tasks_per_block=4,
        preferred_task_order="high_to_low_priority",
        avoid_late_night=False,
        notification_lead_min=15,
    )
    owner.availability_windows = []
    st.session_state.petcare_app.save_owner_info(owner)
    st.session_state.owner_id = owner.owner_id

if "pet_id" not in st.session_state:
    st.session_state.pet_id = None

owner = st.session_state.petcare_app.owners_by_id[st.session_state.owner_id]
owner.name = owner_name
owner.timezone = timezone
st.session_state.petcare_app.save_owner_info(owner)

pref_col1, pref_col2 = st.columns(2)
with pref_col1:
    max_tasks_per_block = st.number_input("Max tasks per block", min_value=1, max_value=12, value=4)
    preferred_task_order = st.text_input("Preferred task order", value="high_to_low_priority")
with pref_col2:
    st.write("")
    st.write("")
    late_night_available = st.checkbox("Late-night tasks allowed (after 10 PM)", value=True)
    st.write("")
    notification_lead_min = st.number_input("Notification lead (minutes)", min_value=0, max_value=180, value=15)

st.markdown("### Availability Window")
available_days = st.multiselect(
    "Available days",
    options=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    default=["Mon", "Tue", "Wed", "Thu", "Fri"],
)
avail_col1, avail_col2 = st.columns(2)
with avail_col1:
    availability_start = st.time_input("Available from", value=time(hour=8, minute=0))
with avail_col2:
    availability_end = st.time_input("Available until", value=time(hour=20, minute=0))

day_to_index = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

if st.button("Save owner settings"):
    owner.preference = OwnerPreference(
        max_tasks_per_block=int(max_tasks_per_block),
        preferred_task_order=preferred_task_order,
        avoid_late_night=not late_night_available,
        notification_lead_min=int(notification_lead_min),
    )
    if availability_end <= availability_start:
        st.error("Availability end time must be after start time.")
    else:
        owner.availability_windows = [
            AvailabilityWindow(
                day_of_week=day_to_index[day_label],
                start_time=availability_start,
                end_time=availability_end,
            )
            for day_label in available_days
        ]
        st.session_state.petcare_app.save_owner_info(owner)
        st.success("Owner preferences and availability saved.")

st.divider()

st.subheader("Pets")

existing_pets = owner.pets
pet_by_id = {pet.pet_id: pet for pet in existing_pets}
if "pet_form_mode" not in st.session_state:
    st.session_state.pet_form_mode = "add"
if "selected_pet_option_id" not in st.session_state:
    st.session_state.selected_pet_option_id = st.session_state.pet_id

pet_choice_ids = [None] + [pet.pet_id for pet in existing_pets]
if st.session_state.selected_pet_option_id not in pet_choice_ids:
    st.session_state.selected_pet_option_id = st.session_state.pet_id if st.session_state.pet_id in pet_choice_ids else None


def _pet_option_label(pet_id):
    """Format a readable label for the pet select dropdown."""
    return pet_option_label(pet_id, pet_by_id)


selected_pet_id = st.selectbox(
    "Pets",
    options=pet_choice_ids,
    format_func=_pet_option_label,
    key="selected_pet_option_id",
)

if selected_pet_id != st.session_state.pet_id:
    st.session_state.pet_id = selected_pet_id

selected_pet = pet_by_id.get(selected_pet_id)

pet_action_col1, pet_action_col2 = st.columns(2)
with pet_action_col1:
    if st.button("Add new pet"):
        st.session_state.pet_form_mode = "add"
with pet_action_col2:
    if st.button("Edit selected pet"):
        if selected_pet is None:
            st.error("Select a pet from the dropdown before editing.")
        else:
            st.session_state.pet_form_mode = "edit"

if st.session_state.pet_form_mode == "add":
    st.markdown("### Add Pet")
    add_col1, add_col2 = st.columns(2)
    with add_col1:
        add_pet_name = st.text_input("Pet name", value="Mochi")
        add_species = st.selectbox("Species", ["dog", "cat", "other"], index=0)
        add_pet_age = st.number_input("Age (years)", min_value=0, max_value=50, value=2)
    with add_col2:
        add_pet_height = st.number_input("Height (cm)", min_value=0.0, max_value=300.0, value=35.0)
        add_pet_weight = st.number_input("Weight (kg)", min_value=0.0, max_value=250.0, value=6.5)

    if st.button("Save new pet"):
        new_pet = Pet(
            name=add_pet_name,
            species=add_species,
            age_years=int(add_pet_age),
            height_cm=float(add_pet_height),
            weight_kg=float(add_pet_weight),
        )
        st.session_state.petcare_app.save_pet_info(st.session_state.owner_id, new_pet)
        st.session_state.pet_id = new_pet.pet_id
        st.session_state.selected_pet_for_filter = new_pet.pet_id
        st.session_state.pet_form_mode = "edit"
        st.session_state.petcare_app.save_owner_info(owner)
        st.success("New pet added.")
        st.rerun()
else:
    st.markdown("### Edit Pet")
    if selected_pet is None:
        st.info("Select a pet in the dropdown, then click 'Edit selected pet'.")
    else:
        key_suffix = str(selected_pet.pet_id)
        selected_species = selected_pet.species if selected_pet.species in ["dog", "cat", "other"] else "other"
        edit_col1, edit_col2 = st.columns(2)
        with edit_col1:
            edit_pet_name = st.text_input("Pet name", value=selected_pet.name, key=f"edit_pet_name_{key_suffix}")
            edit_species = st.selectbox(
                "Species",
                ["dog", "cat", "other"],
                index=["dog", "cat", "other"].index(selected_species),
                key=f"edit_species_{key_suffix}",
            )
            edit_pet_age = st.number_input(
                "Age (years)",
                min_value=0,
                max_value=50,
                value=int(selected_pet.age_years),
                key=f"edit_pet_age_{key_suffix}",
            )
        with edit_col2:
            edit_pet_height = st.number_input(
                "Height (cm)",
                min_value=0.0,
                max_value=300.0,
                value=float(selected_pet.height_cm),
                key=f"edit_pet_height_{key_suffix}",
            )
            edit_pet_weight = st.number_input(
                "Weight (kg)",
                min_value=0.0,
                max_value=250.0,
                value=float(selected_pet.weight_kg),
                key=f"edit_pet_weight_{key_suffix}",
            )

        edit_save_col, edit_delete_col = st.columns(2)
        with edit_save_col:
            update_pet_clicked = st.button("Save pet changes")
        with edit_delete_col:
            delete_pet_clicked = st.button("Delete pet")

        if update_pet_clicked:
            selected_pet.name = edit_pet_name
            selected_pet.species = edit_species
            selected_pet.age_years = int(edit_pet_age)
            selected_pet.height_cm = float(edit_pet_height)
            selected_pet.weight_kg = float(edit_pet_weight)
            st.session_state.pet_id = selected_pet.pet_id
            st.session_state.petcare_app.save_owner_info(owner)
            st.success("Pet profile updated.")
            st.rerun()

        if delete_pet_clicked:
            owner.remove_pet(selected_pet.pet_id)
            if st.session_state.pet_id == selected_pet.pet_id:
                st.session_state.pet_id = None
            st.session_state.selected_pet_option_id = None
            st.session_state.petcare_app.save_owner_info(owner)
            st.success("Pet deleted.")
            st.rerun()

priority_to_score = {"low": 1, "medium": 2, "high": 3}
weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

render_task_management_section(
    owner=owner,
    selected_pet_id=selected_pet_id,
    pet_by_id=pet_by_id,
    priority_to_score=priority_to_score,
    weekday_labels=weekday_labels,
)

render_schedule_section(
    owner=owner,
    weekday_labels=weekday_labels,
)