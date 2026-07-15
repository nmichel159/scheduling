import os
import sys
from copy import deepcopy

from sqlalchemy import text
from sqlalchemy.orm import Session

# Add the project root to python path to allow absolute imports.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.session import Base, SessionLocal, engine
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance, UserRole
from app.models.competence import Competence
from app.models.role import Role
from app.models.user import User
from app.db.seed_configs import SEED_CONFIGS

ROLES_DATA = [
    {"id": 1, "code": "EMPLOYEE", "name": "Zamestnanec", "level": 1},
    {"id": 2, "code": "LEADER", "name": "Veduci", "level": 2},
    {"id": 3, "code": "AMBULANCE_OVERSEER", "name": "Dohlad nad ambulanciou", "level": 3},
    {"id": 4, "code": "HOSPITAL_ADMIN", "name": "Cela nemocnica", "level": 4},
]

def _get_seed_config(config_name: str) -> dict:
    try:
        return deepcopy(SEED_CONFIGS[config_name])
    except KeyError as exc:
        available_configs = ", ".join(sorted(SEED_CONFIGS))
        raise ValueError(
            f"Unknown seed config '{config_name}'. Available configs: {available_configs}"
        ) from exc


def _validate_seed_config(seed_config: dict) -> None:
    """Fail early when a profile violates the deterministic seed contract."""
    users = seed_config["users"]
    emails = [user["email"] for user in users]
    if len(emails) != len(set(emails)):
        raise ValueError("Seed profile contains duplicate email addresses")
    configured_emails = set(emails)
    for assignment_group in ("role_assignments", "ambulance_assignments"):
        unknown = set(seed_config[assignment_group]) - configured_emails
        if unknown:
            raise ValueError(
                f"Seed profile {assignment_group} contains unknown users: {sorted(unknown)}"
            )


def _seed_roles(db: Session) -> dict[str, Role]:
    roles_by_code = {}
    for role_info in ROLES_DATA:
        role = db.query(Role).filter(Role.code == role_info["code"]).first()
        if not role:
            role_by_id = db.query(Role).filter(Role.id == role_info["id"]).first()
            if role_by_id:
                role = role_by_id
                role.code = role_info["code"]
            else:
                role = Role(id=role_info["id"], code=role_info["code"])
                db.add(role)

        role.name = role_info["name"]
        role.level = role_info["level"]
        roles_by_code[role_info["code"]] = role

    db.commit()

    if engine.dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('roles', 'id'), "
                "coalesce(max(id), 1)) FROM roles;"
            )
        )
        db.commit()

    return roles_by_code


def _seed_users(db: Session, users_data: list[dict]) -> dict[str, User]:
    users_by_email = {}
    for user_info in users_data:
        user = db.query(User).filter(User.email == user_info["email"]).first()
        if not user:
            user = User(
                email=user_info["email"],
                full_name=user_info["full_name"],
                login_count=0,
            )
            db.add(user)
            print(f"Created User: {user_info['email']}")
        else:
            user.full_name = user_info["full_name"]
        users_by_email[user_info["email"]] = user

    db.commit()
    return users_by_email


def _seed_ambulances(
    db: Session, ambulances_data: list[dict], users_by_email: dict[str, User]
) -> dict[str, Ambulance]:
    ambulances_by_name = {}
    for ambulance_info in ambulances_data:
        manager = users_by_email.get(ambulance_info["manager_email"])
        manager_id = manager.id if manager else None

        ambulance = (
            db.query(Ambulance).filter(Ambulance.name == ambulance_info["name"]).first()
        )
        if not ambulance:
            ambulance = Ambulance(
                name=ambulance_info["name"],
                description=ambulance_info["description"],
                managed_by_user_id=manager_id,
                isurgent=ambulance_info.get("isurgent", False),
            )
            db.add(ambulance)
            print(
                f"Created Ambulance: {ambulance_info['name']} "
                f"managed by {ambulance_info['manager_email']}"
            )
        else:
            ambulance.description = ambulance_info["description"]
            ambulance.managed_by_user_id = manager_id
            ambulance.isurgent = ambulance_info.get("isurgent", False)
        ambulances_by_name[ambulance_info["name"]] = ambulance

    db.commit()
    return ambulances_by_name


def _seed_competences(
    db: Session,
    competences_data: dict[str, list[str]],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    for ambulance_name, competence_names in competences_data.items():
        ambulance = ambulances_by_name.get(ambulance_name)
        if not ambulance:
            continue

        for competence_name in competence_names:
            competence = (
                db.query(Competence)
                .filter(
                    Competence.name == competence_name,
                    Competence.ambulance_id == ambulance.id,
                )
                .first()
            )
            if not competence:
                db.add(Competence(name=competence_name, ambulance_id=ambulance.id))
                print(f"Created Competence: {competence_name} under {ambulance_name}")

    db.commit()


def _sync_user_roles(
    db: Session,
    role_assignments: dict[str, list[str]],
    users_by_email: dict[str, User],
    roles_by_code: dict[str, Role],
) -> None:
    for email, role_codes in role_assignments.items():
        user = users_by_email.get(email)
        if not user:
            continue

        desired_role_ids = {
            roles_by_code[role_code].id
            for role_code in role_codes
            if role_code in roles_by_code
        }
        for user_role in list(user.user_roles):
            if user_role.role_id not in desired_role_ids:
                db.delete(user_role)

        existing_role_ids = {user_role.role_id for user_role in user.user_roles}
        for role_id in desired_role_ids - existing_role_ids:
            db.add(UserRole(user_id=user.id, role_id=role_id))

    db.commit()


def _sync_user_ambulances(
    db: Session,
    ambulance_assignments: dict[str, list[str]],
    users_by_email: dict[str, User],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    for email, ambulance_names in ambulance_assignments.items():
        user = users_by_email.get(email)
        if not user:
            continue

        desired_ambulance_ids = {
            ambulances_by_name[ambulance_name].id
            for ambulance_name in ambulance_names
            if ambulance_name in ambulances_by_name
        }
        for user_ambulance in list(user.user_ambulances):
            if user_ambulance.ambulance_id not in desired_ambulance_ids:
                db.delete(user_ambulance)

        existing_ambulance_ids = {
            user_ambulance.ambulance_id for user_ambulance in user.user_ambulances
        }
        for ambulance_id in desired_ambulance_ids - existing_ambulance_ids:
            db.add(UserAmbulance(user_id=user.id, ambulance_id=ambulance_id))

    db.commit()


def seed_db(config_name: str | None = None):
    selected_config_name = config_name or os.getenv("SEED_CONFIG", "config_1")
    seed_config = _get_seed_config(selected_config_name)
    _validate_seed_config(seed_config)
    print(f"Starting database seeding with {selected_config_name}...")

    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        roles_by_code = _seed_roles(db)
        users_by_email = _seed_users(db, seed_config["users"])
        ambulances_by_name = _seed_ambulances(
            db, seed_config["ambulances"], users_by_email
        )
        _seed_competences(db, seed_config["competences"], ambulances_by_name)
        _sync_user_roles(
            db, seed_config["role_assignments"], users_by_email, roles_by_code
        )
        _sync_user_ambulances(
            db,
            seed_config["ambulance_assignments"],
            users_by_email,
            ambulances_by_name,
        )
        print("Database seeding completed successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_db(sys.argv[1] if len(sys.argv) > 1 else None)
