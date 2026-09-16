"""The demo profile: I.KAIM plus the three mock workplaces around it.

Everything the application can show is already populated here -- rosters,
qualifications, a year of absences and day requests, and an approved schedule
for every month of 2026 -- so a freshly reset database opens on real content
instead of empty calendars.
"""

from app.db.seed_configs.accounts import (
    ROLE_ASSIGNMENTS as ACCOUNT_ROLE_ASSIGNMENTS,
    USERS as ACCOUNT_USERS,
)
from app.db.seed_configs.extra_clinics import (
    AMBULANCE_ASSIGNMENTS as EXTRA_AMBULANCE_ASSIGNMENTS,
    AMBULANCES as EXTRA_AMBULANCES,
    COMPETENCES as EXTRA_COMPETENCES,
    GENERATED_SCHEDULES as EXTRA_GENERATED_SCHEDULES,
    ROLE_ASSIGNMENTS as EXTRA_ROLE_ASSIGNMENTS,
    UNAVAILABILITIES as EXTRA_UNAVAILABILITIES,
    USER_COMPETENCE_ASSIGNMENTS as EXTRA_USER_COMPETENCE_ASSIGNMENTS,
    USERS as EXTRA_USERS,
)
from app.db.seed_configs.ikaim import (
    AMBULANCE as IKAIM_AMBULANCE,
    AMBULANCE_ASSIGNMENTS as IKAIM_AMBULANCE_ASSIGNMENTS,
    AMBULANCE_NAME as IKAIM_NAME,
    COMPETENCES as IKAIM_COMPETENCES,
    GENERATED_SCHEDULES as IKAIM_GENERATED_SCHEDULES,
    ROLE_ASSIGNMENTS as IKAIM_ROLE_ASSIGNMENTS,
    UNAVAILABILITIES as IKAIM_UNAVAILABILITIES,
    USER_COMPETENCE_ASSIGNMENTS as IKAIM_USER_COMPETENCE_ASSIGNMENTS,
    USERS as IKAIM_USERS,
)

def _merge_assignments(*sources: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union the workplace lists of people who appear in more than one source."""
    merged: dict[str, list[str]] = {}
    for source in sources:
        for email, names in source.items():
            target = merged.setdefault(email, [])
            target.extend(name for name in names if name not in target)
    return merged


def _merge_competence_assignments(
    *sources: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """Union the per-workplace qualifications of people in several sources."""
    merged: dict[str, dict[str, list[str]]] = {}
    for source in sources:
        for email, by_workplace in source.items():
            merged.setdefault(email, {}).update(by_workplace)
    return merged


SEED_CONFIG = {
    "version": "7",
    "users": ACCOUNT_USERS + IKAIM_USERS + EXTRA_USERS,
    "ambulances": [IKAIM_AMBULANCE] + EXTRA_AMBULANCES,
    "competences": {IKAIM_NAME: IKAIM_COMPETENCES, **EXTRA_COMPETENCES},
    # Mock staff first, so that a sign-in account that also works a rota keeps
    # the roles its account entry gives it rather than a bare EMPLOYEE.
    "role_assignments": {
        **IKAIM_ROLE_ASSIGNMENTS,
        **EXTRA_ROLE_ASSIGNMENTS,
        **ACCOUNT_ROLE_ASSIGNMENTS,
    },
    "ambulance_assignments": _merge_assignments(
        IKAIM_AMBULANCE_ASSIGNMENTS,
        EXTRA_AMBULANCE_ASSIGNMENTS,
    ),
    "user_competence_assignments": _merge_competence_assignments(
        IKAIM_USER_COMPETENCE_ASSIGNMENTS,
        EXTRA_USER_COMPETENCE_ASSIGNMENTS,
    ),
    "unavailabilities": IKAIM_UNAVAILABILITIES + EXTRA_UNAVAILABILITIES,
    # I.KAIM is solved first: it is the largest roster and the one the urgent
    # workplace borrows from, so every later schedule is built around it.
    "generated_schedules": IKAIM_GENERATED_SCHEDULES + EXTRA_GENERATED_SCHEDULES,
}
