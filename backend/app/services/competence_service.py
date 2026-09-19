"""
Service layer for Competence Codebook CRUD.

Business rules:
- Competences belong to a specific ambulance (scoped by ambulance_id) and
  are shared by all of its scenarios: creating one adds it everywhere,
  deleting one removes it everywhere.
- What differs between scenarios is a competence's parameters -- the
  per-weekday required counts and recovery days -- which live in
  ``competence_weekday_requirements`` keyed by scenario.
- Only the ambulance manager may create, update, or delete competences
  (ownership is enforced at the dependency level).
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models.competence import Competence
from app.models.competence_scenario import CompetenceScenario
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    CompetenceWeekdayRequirement,
)
from app.schemas.competence import (
    CompetenceCreate,
    CompetenceResponse,
    CompetenceUpdate,
    CompetenceWeekdayRequirementData,
)
from app.services.competence_scenario_service import (
    ensure_selected_scenario,
    get_scenario,
)
from app.services.database_conflict import commit_or_conflict

DUPLICATE_NAME_DETAIL = "An active competence with this name already exists in this ambulance."


def resolve_scenario(
    db: Session, ambulance_id: int, scenario_id: int | None
) -> CompetenceScenario:
    """Return the scenario a codebook call operates on.

    Passing ``None`` means "whatever this workplace is currently scheduled
    from", which is how the scenario-unaware endpoints keep working.
    """
    if scenario_id is None:
        return ensure_selected_scenario(db, ambulance_id)
    return get_scenario(db, scenario_id, ambulance_id)


def weekly_parameters(
    competence: Competence, scenario_id: int
) -> list[CompetenceWeekdayRequirementData]:
    """Return this scenario's complete Monday-to-Sunday parameters.

    Weekdays the scenario has no row for fall back to the competence's
    legacy all-days count and the default recovery, so a competence created
    before scenarios existed still reads as a full week.
    """
    configured = {
        row.weekday: row
        for row in competence.weekday_requirements
        if row.scenario_id == scenario_id
    }
    fallback_count = max(0, competence.required_count or 0)
    return [
        CompetenceWeekdayRequirementData(
            weekday=weekday,
            required_count=(
                configured[weekday].required_count
                if weekday in configured
                else fallback_count
            ),
            recovery_days=(
                configured[weekday].recovery_days
                if weekday in configured
                else DEFAULT_RECOVERY_DAYS
            ),
        )
        for weekday in range(7)
    ]


def to_response(competence: Competence, scenario_id: int) -> CompetenceResponse:
    """Serialize a competence through one scenario's parameters."""
    return CompetenceResponse(
        id=competence.id,
        ambulance_id=competence.ambulance_id,
        scenario_id=scenario_id,
        name=competence.name,
        description=competence.description,
        required_count=competence.required_count,
        count=competence.required_count,
        weekday_requirements=weekly_parameters(competence, scenario_id),
        created_at=competence.created_at,
        updated_at=competence.updated_at,
        is_active=competence.is_active,
    )


def _replace_weekday_requirements(
    competence: Competence, scenario_id: int, requirements
) -> None:
    """Replace one scenario's weekly parameters, leaving the others alone."""
    existing_by_weekday = {
        row.weekday: row
        for row in competence.weekday_requirements
        if row.scenario_id == scenario_id
    }
    for item in requirements:
        row = existing_by_weekday.pop(item.weekday, None)
        if row is None:
            row = CompetenceWeekdayRequirement(
                weekday=item.weekday, scenario_id=scenario_id
            )
            competence.weekday_requirements.append(row)
        row.required_count = item.required_count
        row.recovery_days = item.recovery_days
    # Weekdays the payload omitted would leave a partial week behind; a
    # complete definition is validated at the schema, so this only fires
    # when the caller deliberately cleared the week.
    for row in existing_by_weekday.values():
        competence.weekday_requirements.remove(row)


def list_competences(db: Session, ambulance_id: int) -> list[Competence]:
    """List all active competences belonging to an ambulance.

    Args:
        db: Active database session.
        ambulance_id: The ambulance whose competences to list.

    Returns:
        A list of :class:`Competence` instances.
    """
    return (
        db.query(Competence)
        .options(selectinload(Competence.weekday_requirements))
        .filter(
            Competence.ambulance_id == ambulance_id,
            Competence.is_active == True,
        )
        .order_by(Competence.name)
        .all()
    )


def list_competence_responses(
    db: Session, ambulance_id: int, scenario_id: int | None = None
) -> list[CompetenceResponse]:
    """List an ambulance's competences with one scenario's parameters."""
    scenario = resolve_scenario(db, ambulance_id, scenario_id)
    return [
        to_response(competence, scenario.id)
        for competence in list_competences(db, ambulance_id)
    ]


def get_competence(db: Session, competence_id: int, ambulance_id: int) -> Competence:
    """Retrieve a single competence by ID, scoped to an ambulance.

    Args:
        db: Active database session.
        competence_id: The competence to retrieve.
        ambulance_id: The ambulance scope.

    Returns:
        The :class:`Competence` instance.

    Raises:
        HTTPException 404: If the competence does not exist or does not belong
            to the given ambulance.
    """
    competence = (
        db.query(Competence)
        .options(selectinload(Competence.weekday_requirements))
        .filter(
            Competence.id == competence_id,
            Competence.ambulance_id == ambulance_id,
            Competence.is_active == True,
        )
        .first()
    )
    if not competence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Competence with id {competence_id} not found in ambulance {ambulance_id}.",
        )
    return competence


def create_competence(
    db: Session,
    ambulance_id: int,
    data: CompetenceCreate,
    scenario_id: int | None = None,
) -> CompetenceResponse:
    """Create a competence and give every scenario parameters for it.

    The submitted weekly definition lands in ``scenario_id`` (the selected
    scenario when none is given); the workplace's other scenarios get the
    same numbers as their starting point, which they are then free to
    diverge from.
    """
    scenario = resolve_scenario(db, ambulance_id, scenario_id)
    duplicate = db.query(Competence).filter(
        Competence.ambulance_id == ambulance_id,
        Competence.name == data.name,
        Competence.is_active.is_(True),
    ).first()
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_NAME_DETAIL)

    requirements = data.weekday_requirements or [
        CompetenceWeekdayRequirementData(
            weekday=weekday,
            required_count=data.required_count,
            recovery_days=DEFAULT_RECOVERY_DAYS,
        )
        for weekday in range(7)
    ]
    competence = Competence(
        name=data.name,
        description=data.description,
        required_count=data.required_count,
        ambulance_id=ambulance_id,
        is_active=True,
    )
    scenario_ids = {
        row_id
        for (row_id,) in db.query(CompetenceScenario.id).filter(
            CompetenceScenario.ambulance_id == ambulance_id,
            CompetenceScenario.is_active.is_(True),
        )
    }
    scenario_ids.add(scenario.id)
    for target_id in sorted(scenario_ids):
        _replace_weekday_requirements(competence, target_id, requirements)
    db.add(competence)
    commit_or_conflict(db, DUPLICATE_NAME_DETAIL)
    db.refresh(competence)
    return to_response(competence, scenario.id)


def update_competence(
    db: Session,
    competence_id: int,
    ambulance_id: int,
    data: CompetenceUpdate,
    scenario_id: int | None = None,
) -> CompetenceResponse:
    """Update a competence with partial data.

    The name and description are workplace-wide, so editing them is visible
    in every scenario. The weekly parameters only touch ``scenario_id``.
    """
    scenario = resolve_scenario(db, ambulance_id, scenario_id)
    competence = get_competence(db, competence_id, ambulance_id)

    update_data = data.model_dump(exclude_unset=True, exclude={"weekday_requirements"})
    if "name" in update_data:
        duplicate = db.query(Competence).filter(
            Competence.ambulance_id == ambulance_id,
            Competence.name == update_data["name"],
            Competence.id != competence_id,
            Competence.is_active.is_(True),
        ).first()
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_NAME_DETAIL)
    for field, value in update_data.items():
        setattr(competence, field, value)

    if "weekday_requirements" in data.model_fields_set:
        _replace_weekday_requirements(
            competence, scenario.id, data.weekday_requirements or []
        )
    elif "required_count" in update_data:
        # Preserve the old API contract: updating only required_count applies
        # the same value to every day of the scenario being edited.
        for row in competence.weekday_requirements:
            if row.scenario_id == scenario.id:
                row.required_count = update_data["required_count"]

    commit_or_conflict(db, DUPLICATE_NAME_DETAIL)
    db.refresh(competence)
    return to_response(competence, scenario.id)


def delete_competence(db: Session, competence_id: int, ambulance_id: int) -> None:
    """Delete a competence from an ambulance, in every scenario at once.

    Args:
        db: Active database session.
        competence_id: The competence to delete.
        ambulance_id: The ambulance scope.

    Raises:
        HTTPException 404: If the competence does not exist in the ambulance.
    """
    competence = get_competence(db, competence_id, ambulance_id)
    competence.is_active = False
    db.commit()
