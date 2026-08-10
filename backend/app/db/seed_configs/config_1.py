from app.db.seed_configs.base import AMBULANCE_ASSIGNMENTS, AMBULANCES, COMPETENCES, USERS, SCHEDULES
from app.db.seed_configs.ikaim import (
    AMBULANCE as IKAIM_AMBULANCE,
    AMBULANCE_ASSIGNMENTS as IKAIM_AMBULANCE_ASSIGNMENTS,
    COMPETENCES as IKAIM_COMPETENCES,
    GENERATED_SCHEDULES as IKAIM_GENERATED_SCHEDULES,
    ROLE_ASSIGNMENTS as IKAIM_ROLE_ASSIGNMENTS,
    UNAVAILABILITIES as IKAIM_UNAVAILABILITIES,
    USER_COMPETENCE_ASSIGNMENTS as IKAIM_USER_COMPETENCE_ASSIGNMENTS,
    USERS as IKAIM_USERS,
)


SEED_CONFIG = {
    "version": "2",
    "users": USERS + IKAIM_USERS,
    "ambulances": AMBULANCES + [IKAIM_AMBULANCE],
    "competences": {**COMPETENCES, "I.KAIM": IKAIM_COMPETENCES},
    "role_assignments": {
        "alexthesecond0000@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel159@gmail.com": ["EMPLOYEE", "LEADER", "AMBULANCE_OVERSEER"],
        "a14325999@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel@gmail.com": ["HOSPITAL_ADMIN", "LEADER", "AMBULANCE_OVERSEER"],
        "gsemanisin@gmail.com": ["EMPLOYEE", "LEADER", "AMBULANCE_OVERSEER", "HOSPITAL_ADMIN"],
        **IKAIM_ROLE_ASSIGNMENTS,
    },
    "ambulance_assignments": {
        **AMBULANCE_ASSIGNMENTS,
        **IKAIM_AMBULANCE_ASSIGNMENTS,
    },
    "user_competence_assignments": IKAIM_USER_COMPETENCE_ASSIGNMENTS,
    "unavailabilities": IKAIM_UNAVAILABILITIES,
    "generated_schedules": IKAIM_GENERATED_SCHEDULES,
    "schedules": SCHEDULES,
}
