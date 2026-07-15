from app.db.seed_configs.base import AMBULANCE_ASSIGNMENTS, AMBULANCES, COMPETENCES, USERS


SEED_CONFIG = {
    "users": USERS,
    "ambulances": AMBULANCES,
    "competences": COMPETENCES,
    "role_assignments": {
        "alexthesecond0000@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel159@gmail.com": ["EMPLOYEE", "LEADER"],
        "a14325999@gmail.com": ["EMPLOYEE", "LEADER"],
        "noro.michel@gmail.com": ["HOSPITAL_ADMIN", "LEADER"],
    },
    "ambulance_assignments": AMBULANCE_ASSIGNMENTS,
}
