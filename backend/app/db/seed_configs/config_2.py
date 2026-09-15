from app.db.seed_configs.base import AMBULANCE_ASSIGNMENTS, AMBULANCES, COMPETENCES, USERS, SCHEDULES


SEED_CONFIG = {
    "version": "2",
    "users": USERS,
    "ambulances": AMBULANCES,
    "competences": COMPETENCES,
    "role_assignments": {
        "alexthesecond0000@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel159@gmail.com": ["EMPLOYEE", "LEADER", "AMBULANCE_OVERSEER"],
        "a14325999@gmail.com": ["EMPLOYEE", "LEADER", "ANALYST"],
        "noro.michel@gmail.com": ["EMPLOYEE", "LEADER", "AMBULANCE_OVERSEER"],
        "gsemanisin@gmail.com": ["EMPLOYEE", "LEADER", "AMBULANCE_OVERSEER", "ANALYST"],
    },
    "ambulance_assignments": AMBULANCE_ASSIGNMENTS,
    "schedules": SCHEDULES,
}
