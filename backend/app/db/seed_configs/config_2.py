from app.db.seed_configs.base import AMBULANCE_ASSIGNMENTS, AMBULANCES, COMPETENCES, USERS


SEED_CONFIG = {
    "users": USERS,
    "ambulances": AMBULANCES,
    "competences": COMPETENCES,
    "role_assignments": {
        "alexthesecond0000@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel159@gmail.com": ["EMPLOYEE", "AMBULANCE_OVERSEER"],
        "a14325999@gmail.com": ["EMPLOYEE", "HOSPITAL_ADMIN"],
        "noro.michel@gmail.com": ["EMPLOYEE"],
    },
    "ambulance_assignments": AMBULANCE_ASSIGNMENTS,
}
