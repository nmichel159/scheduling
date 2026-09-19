"""
FastAPI router for competence scenarios.

A scenario is one model case of a workplace's staffing parameters. The
competence list is shared by every scenario of the workplace, so the
competence endpoints below are the same codebook writes as in
``competence.py`` -- they merely say which scenario's numbers the payload
carries and the response reflects.

All routes require the caller to manage the ambulance in the path, which
``get_manager_ambulance`` enforces.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.competence import (
    CompetenceCreate,
    CompetenceResponse,
    CompetenceUpdate,
)
from app.schemas.competence_scenario import (
    CompetenceScenarioCreate,
    CompetenceScenarioResponse,
    CompetenceScenarioUpdate,
)
from app.services.competence_scenario_service import (
    create_scenario,
    delete_scenario,
    ensure_selected_scenario,
    get_scenario,
    list_scenarios,
    to_response,
    update_scenario,
)
from app.services.competence_service import (
    create_competence,
    delete_competence,
    list_competence_responses,
    list_competences,
    update_competence,
)

router = APIRouter()


@router.get(
    "/{ambulance_id}/competence-scenarios",
    response_model=list[CompetenceScenarioResponse],
    summary="List the competence scenarios of a workplace",
)
def list_scenarios_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[CompetenceScenarioResponse]:
    """List every scenario, guaranteeing at least one selected scenario.

    Opening the screen is what gives a workplace its first scenario, so the
    list is never empty and the UI never has to handle that case.
    """
    ensure_selected_scenario(db, ambulance.id)
    competence_count = len(list_competences(db, ambulance.id))
    return [
        to_response(db, scenario, competence_count)
        for scenario in list_scenarios(db, ambulance.id)
    ]


@router.post(
    "/{ambulance_id}/competence-scenarios",
    response_model=CompetenceScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a competence scenario",
)
def create_scenario_endpoint(
    data: CompetenceScenarioCreate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceScenarioResponse:
    """Add a scenario, optionally starting from another one's parameters."""
    ensure_selected_scenario(db, ambulance.id)
    scenario = create_scenario(db, ambulance.id, data)
    return to_response(db, scenario, len(list_competences(db, ambulance.id)))


@router.put(
    "/{ambulance_id}/competence-scenarios/{scenario_id}",
    response_model=CompetenceScenarioResponse,
    summary="Rename a scenario or make it the selected one",
)
def update_scenario_endpoint(
    scenario_id: int,
    data: CompetenceScenarioUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceScenarioResponse:
    """Update a scenario's name and/or selection."""
    scenario = update_scenario(db, scenario_id, ambulance.id, data)
    return to_response(db, scenario, len(list_competences(db, ambulance.id)))


@router.delete(
    "/{ambulance_id}/competence-scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scenario",
)
def delete_scenario_endpoint(
    scenario_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    """Remove a scenario; the workplace always keeps at least one."""
    delete_scenario(db, scenario_id, ambulance.id)


@router.get(
    "/{ambulance_id}/competence-scenarios/{scenario_id}/competences",
    response_model=list[CompetenceResponse],
    summary="List the workplace's competences with one scenario's parameters",
)
def list_scenario_competences_endpoint(
    scenario_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[CompetenceResponse]:
    """Retrieve every competence, valued through this scenario."""
    scenario = get_scenario(db, scenario_id, ambulance.id)
    return list_competence_responses(db, ambulance.id, scenario.id)


@router.post(
    "/{ambulance_id}/competence-scenarios/{scenario_id}/competences",
    response_model=CompetenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a competence from inside a scenario",
)
def create_scenario_competence_endpoint(
    scenario_id: int,
    data: CompetenceCreate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceResponse:
    """Add a competence to the workplace, valued here through this scenario."""
    scenario = get_scenario(db, scenario_id, ambulance.id)
    return create_competence(db, ambulance.id, data, scenario_id=scenario.id)


@router.put(
    "/{ambulance_id}/competence-scenarios/{scenario_id}/competences/{competence_id}",
    response_model=CompetenceResponse,
    summary="Update a competence's shared fields and this scenario's parameters",
)
def update_scenario_competence_endpoint(
    scenario_id: int,
    competence_id: int,
    data: CompetenceUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> CompetenceResponse:
    """Save the competence editor: name and description are workplace-wide,
    the weekly counts and recovery days belong to this scenario only."""
    scenario = get_scenario(db, scenario_id, ambulance.id)
    return update_competence(
        db, competence_id, ambulance.id, data, scenario_id=scenario.id
    )


@router.delete(
    "/{ambulance_id}/competence-scenarios/{scenario_id}/competences/{competence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a competence from the workplace",
)
def delete_scenario_competence_endpoint(
    scenario_id: int,
    competence_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    """Remove the competence from every scenario, as it is workplace-wide."""
    get_scenario(db, scenario_id, ambulance.id)
    delete_competence(db, competence_id, ambulance.id)
