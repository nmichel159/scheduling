"""
Service layer for competence scenarios.

A scenario is a named parameter set over the competences a workplace already
has. Every scenario of a workplace covers the same competences -- creating a
competence adds it to all of them -- and differs only in the per-weekday
required counts and recovery days.

Business rules:
- Scenarios belong to a specific ambulance (ownership is enforced by the
  router dependency, as for competences).
- At most one scenario per ambulance is selected; the selected one is what
  the rest of the application (matrix, statistics, solver) reads.
- A workplace always keeps at least one scenario, so the last one cannot be
  deleted.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.competence import Competence
from app.models.competence_scenario import CompetenceScenario
from app.models.competence_weekday_requirement import (
    DEFAULT_RECOVERY_DAYS,
    DEFAULT_REQUIRED_COUNT,
    DEFAULT_SHIFT_HOURS,
    CompetenceWeekdayRequirement,
)
from app.schemas.competence_scenario import (
    CompetenceScenarioCreate,
    CompetenceScenarioResponse,
    CompetenceScenarioUpdate,
)
from app.services.database_conflict import commit_or_conflict

#: Name given to the scenario a workplace is healed into when it has none.
#: It matches the name the migration assigns, so a database that skipped the
#: migration and one that ran it end up describing the same thing.
DEFAULT_SCENARIO_NAME = "Scenár 1"

DUPLICATE_NAME_DETAIL = "An active scenario with this name already exists in this workplace."


def list_scenarios(db: Session, ambulance_id: int) -> list[CompetenceScenario]:
    """List a workplace's active scenarios, oldest first."""
    return (
        db.query(CompetenceScenario)
        .filter(
            CompetenceScenario.ambulance_id == ambulance_id,
            CompetenceScenario.is_active.is_(True),
        )
        .order_by(CompetenceScenario.id)
        .all()
    )


def get_scenario(db: Session, scenario_id: int, ambulance_id: int) -> CompetenceScenario:
    """Retrieve one active scenario, scoped to its ambulance.

    Raises:
        HTTPException 404: If the scenario does not exist in this ambulance.
    """
    scenario = (
        db.query(CompetenceScenario)
        .filter(
            CompetenceScenario.id == scenario_id,
            CompetenceScenario.ambulance_id == ambulance_id,
            CompetenceScenario.is_active.is_(True),
        )
        .first()
    )
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario with id {scenario_id} not found in ambulance {ambulance_id}.",
        )
    return scenario


def get_selected_scenario(db: Session, ambulance_id: int) -> CompetenceScenario | None:
    """Return the scenario the application reads, or ``None`` if there is none.

    Read paths call this rather than :func:`ensure_selected_scenario` so that
    merely looking at a workplace never writes. A workplace without scenarios
    still answers every query -- its competences simply fall back to their
    legacy all-days count.
    """
    scenarios = list_scenarios(db, ambulance_id)
    if not scenarios:
        return None
    for scenario in scenarios:
        if scenario.is_selected:
            return scenario
    return scenarios[0]


def selected_scenario_ids(
    db: Session, ambulance_ids: list[int]
) -> dict[int, int]:
    """Map several workplaces to their selected scenario in one query.

    Listings that span workplaces use this instead of calling
    :func:`get_selected_scenario` per row, which would be a query each.
    Workplaces without a scenario are simply absent from the result.
    """
    if not ambulance_ids:
        return {}
    rows = (
        db.query(CompetenceScenario)
        .filter(
            CompetenceScenario.ambulance_id.in_(ambulance_ids),
            CompetenceScenario.is_active.is_(True),
        )
        .order_by(CompetenceScenario.id)
        .all()
    )
    selected: dict[int, int] = {}
    for row in rows:
        # Oldest wins unless a later one is explicitly selected, which is
        # the same tie-break get_selected_scenario applies to one workplace.
        if row.ambulance_id not in selected or row.is_selected:
            selected[row.ambulance_id] = row.id
    return selected


def ensure_selected_scenario(db: Session, ambulance_id: int) -> CompetenceScenario:
    """Return the selected scenario, creating a default one if none exists.

    This is the entry point of the scenario screen: a workplace that has
    never been opened there (or predates the feature) gets its first
    scenario here, seeded from whatever weekday rows it already carries.
    """
    scenario = get_selected_scenario(db, ambulance_id)
    if scenario is not None:
        if not scenario.is_selected:
            scenario.is_selected = True
            db.commit()
        return scenario

    scenario = CompetenceScenario(
        name=DEFAULT_SCENARIO_NAME,
        ambulance_id=ambulance_id,
        is_selected=True,
        is_active=True,
    )
    db.add(scenario)
    commit_or_conflict(db, DUPLICATE_NAME_DETAIL)
    db.refresh(scenario)
    materialize_scenario(db, scenario)
    return scenario


def materialize_scenario(
    db: Session,
    scenario: CompetenceScenario,
    source_scenario_id: int | None = None,
    use_defaults: bool = False,
) -> None:
    """Give the scenario a complete weekly row for every active competence.

    Missing rows are filled from ``source_scenario_id`` when one is given and
    has them. Otherwise they start from the defaults -- one person, four
    hours, one recovery day -- when ``use_defaults`` says this is a fresh
    model case, and from the competence's legacy all-days count when it is a
    workplace being healed into its first scenario, whose numbers predate
    scenarios and must not be thrown away. Rows the scenario already has are
    left alone, so this is safe to re-run after a competence is added.
    """
    competences = (
        db.query(Competence)
        .filter(
            Competence.ambulance_id == scenario.ambulance_id,
            Competence.is_active.is_(True),
        )
        .all()
    )
    if not competences:
        return

    competence_ids = [competence.id for competence in competences]
    existing = {
        (row.competence_id, row.weekday)
        for row in db.query(
            CompetenceWeekdayRequirement.competence_id,
            CompetenceWeekdayRequirement.weekday,
        ).filter(CompetenceWeekdayRequirement.scenario_id == scenario.id)
    }
    source = _requirement_map(db, source_scenario_id, competence_ids)

    created = False
    for competence in competences:
        fallback_count = (
            DEFAULT_REQUIRED_COUNT
            if use_defaults
            else max(0, competence.required_count or 0)
        )
        for weekday in range(7):
            if (competence.id, weekday) in existing:
                continue
            template = source.get((competence.id, weekday))
            db.add(
                CompetenceWeekdayRequirement(
                    competence_id=competence.id,
                    scenario_id=scenario.id,
                    weekday=weekday,
                    required_count=(
                        template.required_count if template else fallback_count
                    ),
                    recovery_days=(
                        template.recovery_days if template else DEFAULT_RECOVERY_DAYS
                    ),
                    shift_hours=(
                        template.shift_hours if template else DEFAULT_SHIFT_HOURS
                    ),
                )
            )
            created = True
    if created:
        db.commit()


def _requirement_map(
    db: Session, scenario_id: int | None, competence_ids: list[int]
) -> dict[tuple[int, int], CompetenceWeekdayRequirement]:
    """Index one scenario's weekday rows by ``(competence_id, weekday)``."""
    if scenario_id is None or not competence_ids:
        return {}
    rows = (
        db.query(CompetenceWeekdayRequirement)
        .filter(
            CompetenceWeekdayRequirement.scenario_id == scenario_id,
            CompetenceWeekdayRequirement.competence_id.in_(competence_ids),
        )
        .all()
    )
    return {(row.competence_id, row.weekday): row for row in rows}


def create_scenario(
    db: Session, ambulance_id: int, data: CompetenceScenarioCreate
) -> CompetenceScenario:
    """Create a scenario and fill in a complete parameter set for it.

    The new scenario is not selected: adding a model case must not silently
    change the numbers the workplace is currently scheduled from.
    """
    duplicate = (
        db.query(CompetenceScenario)
        .filter(
            CompetenceScenario.ambulance_id == ambulance_id,
            CompetenceScenario.name == data.name,
            CompetenceScenario.is_active.is_(True),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_NAME_DETAIL
        )

    source_id = None
    if data.copy_from_scenario_id is not None:
        source_id = get_scenario(db, data.copy_from_scenario_id, ambulance_id).id

    is_first = not list_scenarios(db, ambulance_id)
    scenario = CompetenceScenario(
        name=data.name,
        ambulance_id=ambulance_id,
        is_selected=is_first,
        is_active=True,
    )
    db.add(scenario)
    commit_or_conflict(db, DUPLICATE_NAME_DETAIL)
    db.refresh(scenario)
    materialize_scenario(
        db,
        scenario,
        source_scenario_id=source_id,
        use_defaults=source_id is None,
    )
    return scenario


def update_scenario(
    db: Session, scenario_id: int, ambulance_id: int, data: CompetenceScenarioUpdate
) -> CompetenceScenario:
    """Rename a scenario and/or make it the selected one."""
    scenario = get_scenario(db, scenario_id, ambulance_id)

    if data.name is not None and data.name != scenario.name:
        duplicate = (
            db.query(CompetenceScenario)
            .filter(
                CompetenceScenario.ambulance_id == ambulance_id,
                CompetenceScenario.name == data.name,
                CompetenceScenario.id != scenario_id,
                CompetenceScenario.is_active.is_(True),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_NAME_DETAIL
            )
        scenario.name = data.name

    if data.is_selected is True:
        _select(db, scenario)
    elif data.is_selected is False and scenario.is_selected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A workplace must always have a selected scenario; select another one instead.",
        )

    commit_or_conflict(db, DUPLICATE_NAME_DETAIL)
    db.refresh(scenario)
    return scenario


def _select(db: Session, scenario: CompetenceScenario) -> None:
    """Make ``scenario`` the only selected one in its workplace.

    The deselect runs as one statement rather than a loop so a workplace
    with several scenarios cannot momentarily show two selected ones. It
    bypasses the identity map, which the commit that follows resolves by
    expiring every instance.
    """
    db.query(CompetenceScenario).filter(
        CompetenceScenario.ambulance_id == scenario.ambulance_id,
        CompetenceScenario.id != scenario.id,
        CompetenceScenario.is_selected.is_(True),
    ).update({CompetenceScenario.is_selected: False}, synchronize_session=False)
    scenario.is_selected = True
    db.add(scenario)


def delete_scenario(db: Session, scenario_id: int, ambulance_id: int) -> None:
    """Soft-delete a scenario, keeping the workplace with at least one.

    Deleting the selected scenario hands the selection to the oldest
    remaining one rather than leaving the workplace without parameters.
    """
    scenario = get_scenario(db, scenario_id, ambulance_id)
    remaining = [item for item in list_scenarios(db, ambulance_id) if item.id != scenario_id]
    if not remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The last scenario of a workplace cannot be deleted.",
        )

    was_selected = scenario.is_selected
    scenario.is_active = False
    scenario.is_selected = False
    if was_selected:
        _select(db, remaining[0])
    db.commit()


def to_response(
    db: Session, scenario: CompetenceScenario, competence_count: int
) -> CompetenceScenarioResponse:
    """Serialize a scenario together with the competence count it covers."""
    return CompetenceScenarioResponse(
        id=scenario.id,
        ambulance_id=scenario.ambulance_id,
        name=scenario.name,
        is_selected=bool(scenario.is_selected),
        competence_count=competence_count,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
        is_active=scenario.is_active,
    )
