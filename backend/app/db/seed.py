import os
import sys
import json
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

# Add the project root to python path to allow absolute imports.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.session import SessionLocal, engine
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.models.competence import Competence
from app.models.role import Role
from app.models.user import User
from app.models.schedule import Schedule
from app.models.seed_version import SeedVersion
from app.models.unavailability import Unavailability
from app.db.seed_configs import SEED_CONFIGS
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    generate_ambulance_monthly_schedule,
)

ROLES_DATA = [
    {"id": 1, "code": "EMPLOYEE", "name": "Zamestnanec", "level": 1},
    {"id": 2, "code": "LEADER", "name": "Veduci", "level": 2},
    {"id": 3, "code": "AMBULANCE_OVERSEER", "name": "Dohlad nad ambulanciou", "level": 3},
    {"id": 4, "code": "HOSPITAL_ADMIN", "name": "Cela nemocnica", "level": 4},
]


class SeedScheduleGenerationError(RuntimeError):
    """Exposes a structured reason when a requested mock schedule is infeasible."""

    def __init__(
        self,
        ambulance_name: str,
        month: int,
        year: int,
        cause: ScheduleGenerationError,
    ) -> None:
        self.detail = {
            "code": "seed_schedule_generation_failed",
            "ambulance_name": ambulance_name,
            "month": month,
            "year": year,
            **cause.as_detail(),
        }
        super().__init__(json.dumps(self.detail, ensure_ascii=False))

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
    if not str(seed_config.get("version", "")).strip():
        raise ValueError("Seed profile must declare a non-empty version")

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

    ambulance_names = [ambulance["name"] for ambulance in seed_config["ambulances"]]
    if len(ambulance_names) != len(set(ambulance_names)):
        raise ValueError("Seed profile contains duplicate ambulance names")
    configured_ambulances = set(ambulance_names)
    for ambulance in seed_config["ambulances"]:
        if ambulance["manager_email"] not in configured_emails:
            raise ValueError(
                f"Ambulance {ambulance['name']} references unknown manager "
                f"{ambulance['manager_email']}"
            )

    competence_names_by_ambulance = {
        ambulance_name: {
            entry if isinstance(entry, str) else entry["name"]
            for entry in entries
        }
        for ambulance_name, entries in seed_config["competences"].items()
    }
    for email, assignments in seed_config.get(
        "user_competence_assignments", {}
    ).items():
        if email not in configured_emails:
            raise ValueError(f"Competence assignments contain unknown user: {email}")
        for ambulance_name, competence_names in assignments.items():
            if ambulance_name not in configured_ambulances:
                raise ValueError(
                    f"Competence assignments reference unknown ambulance: {ambulance_name}"
                )
            unknown_competences = set(competence_names) - competence_names_by_ambulance.get(
                ambulance_name, set()
            )
            if unknown_competences:
                raise ValueError(
                    f"Competence assignments for {email} contain unknown competences: "
                    f"{sorted(unknown_competences)}"
                )

    unknown_unavailability_users = {
        entry["user_email"]
        for entry in seed_config.get("unavailabilities", [])
        if entry["user_email"] not in configured_emails
    }
    if unknown_unavailability_users:
        raise ValueError(
            "Unavailabilities contain unknown users: "
            f"{sorted(unknown_unavailability_users)}"
        )

    for request in seed_config.get("generated_schedules", []):
        if request["ambulance_name"] not in configured_ambulances:
            raise ValueError(
                "Generated schedule references unknown ambulance: "
                f"{request['ambulance_name']}"
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

    db.flush()

    if engine.dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('roles', 'id'), "
                "coalesce(max(id), 1)) FROM roles;"
            )
        )
        db.flush()

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

    db.flush()
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

    db.flush()
    return ambulances_by_name


def _seed_competences(
    db: Session,
    competences_data: dict[str, list[str | dict]],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    for ambulance_name, competence_entries in competences_data.items():
        ambulance = ambulances_by_name.get(ambulance_name)
        if not ambulance:
            continue

        for competence_entry in competence_entries:
            if isinstance(competence_entry, str):
                competence_name = competence_entry
                required_count = 1
                description = None
            else:
                competence_name = competence_entry["name"]
                required_count = competence_entry.get("required_count", 1)
                description = competence_entry.get("description")
            competence = (
                db.query(Competence)
                .filter(
                    Competence.name == competence_name,
                    Competence.ambulance_id == ambulance.id,
                )
                .first()
            )
            if not competence:
                competence = Competence(name=competence_name, ambulance_id=ambulance.id)
                db.add(competence)
                print(f"Created Competence: {competence_name} under {ambulance_name}")
            competence.required_count = required_count
            competence.description = description
            competence.is_active = True

    db.flush()


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

    db.flush()


def _seed_schedules(
    db: Session,
    schedules_data: list[dict],
    users_by_email: dict[str, User],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    for entry in schedules_data:
        user = users_by_email.get(entry["user_email"])
        ambulance = ambulances_by_name.get(entry["ambulance_name"])
        if not user or not ambulance:
            continue

        competence = (
            db.query(Competence)
            .filter(
                Competence.name == entry["competence_name"],
                Competence.ambulance_id == ambulance.id,
            )
            .first()
        )
        if not competence:
            continue

        work_date = entry["work_date"]
        existing = (
            db.query(Schedule)
            .filter(
                Schedule.user_id == user.id,
                Schedule.ambulance_id == ambulance.id,
                Schedule.competence_id == competence.id,
                Schedule.work_date == work_date,
            )
            .first()
        )
        if not existing:
            db.add(
                Schedule(
                    user_id=user.id,
                    ambulance_id=ambulance.id,
                    competence_id=competence.id,
                    work_date=work_date,
                    is_active=True,
                )
            )
    db.flush()
    print("Schedules seeding completed.")


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

    db.flush()


def _sync_user_competences(
    db: Session,
    assignments: dict[str, dict[str, list[str]]],
    users_by_email: dict[str, User],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    """Synchronize qualifications only inside explicitly configured ambulances."""
    for email, ambulance_assignments in assignments.items():
        user = users_by_email.get(email)
        if not user:
            continue
        for ambulance_name, competence_names in ambulance_assignments.items():
            ambulance = ambulances_by_name.get(ambulance_name)
            if not ambulance:
                continue
            competence_rows = (
                db.query(Competence)
                .filter(Competence.ambulance_id == ambulance.id)
                .all()
            )
            competence_ids_by_name = {
                competence.name: competence.id for competence in competence_rows
            }
            desired_ids = {
                competence_ids_by_name[name]
                for name in competence_names
                if name in competence_ids_by_name
            }
            existing_rows = (
                db.query(UserCompetence)
                .join(Competence, Competence.id == UserCompetence.competence_id)
                .filter(
                    UserCompetence.user_id == user.id,
                    Competence.ambulance_id == ambulance.id,
                )
                .all()
            )
            for assignment in existing_rows:
                if assignment.competence_id not in desired_ids:
                    db.delete(assignment)
                else:
                    assignment.is_active = True
            existing_ids = {assignment.competence_id for assignment in existing_rows}
            for competence_id in desired_ids - existing_ids:
                db.add(
                    UserCompetence(
                        user_id=user.id,
                        competence_id=competence_id,
                        is_active=True,
                    )
                )
    db.flush()


def _sync_unavailabilities(
    db: Session,
    entries: list[dict],
    users_by_email: dict[str, User],
) -> None:
    desired_by_user_reason: dict[tuple[int, str], dict[date, dict]] = {}
    for entry in entries:
        user = users_by_email.get(entry["user_email"])
        if not user:
            continue
        reason = entry.get("reason") or "UNAVAILABLE"
        desired_by_user_reason.setdefault((user.id, reason), {})[
            entry["date_absent"]
        ] = entry

    for (user_id, reason), desired_by_date in desired_by_user_reason.items():
        existing_rows = (
            db.query(Unavailability)
            .filter(
                Unavailability.user_id == user_id,
                Unavailability.reason == reason,
            )
            .all()
        )
        existing_by_date = {row.date_absent: row for row in existing_rows}
        for unavailable_date, row in existing_by_date.items():
            if unavailable_date not in desired_by_date:
                db.delete(row)
            else:
                row.is_active = True
        for unavailable_date in desired_by_date.keys() - existing_by_date.keys():
            db.add(
                Unavailability(
                    user_id=user_id,
                    date_absent=unavailable_date,
                    reason=reason,
                    is_active=True,
                )
            )
    db.flush()


def _generate_and_seed_schedules(
    db: Session,
    requests: list[dict],
    ambulances_by_name: dict[str, Ambulance],
) -> None:
    for request in requests:
        ambulance_name = request["ambulance_name"]
        month = request["month"]
        year = request["year"]
        ambulance = ambulances_by_name.get(ambulance_name)
        if not ambulance:
            continue
        try:
            generated = generate_ambulance_monthly_schedule(
                db,
                ambulance.id,
                month=month,
                year=year,
            )
        except ScheduleGenerationError as exc:
            raise SeedScheduleGenerationError(
                ambulance_name,
                month,
                year,
                exc,
            ) from exc

        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        db.query(Schedule).filter(
            Schedule.ambulance_id == ambulance.id,
            Schedule.work_date.between(start, end),
        ).delete(synchronize_session=False)
        db.add_all(
            [
                Schedule(
                    user_id=entry.user_id,
                    ambulance_id=ambulance.id,
                    competence_id=entry.competence_id,
                    work_date=entry.work_date,
                    is_active=True,
                )
                for entry in generated.entries
            ]
        )
        db.flush()
        print(
            f"Generated and seeded {generated.assignment_count} assignments for "
            f"{ambulance_name} ({year}-{month:02d})."
        )


def _apply_seed(db: Session, seed_config: dict) -> None:
    roles_by_code = _seed_roles(db)
    users_by_email = _seed_users(db, seed_config["users"])
    ambulances_by_name = _seed_ambulances(
        db, seed_config["ambulances"], users_by_email
    )
    _seed_competences(db, seed_config["competences"], ambulances_by_name)
    _sync_user_roles(db, seed_config["role_assignments"], users_by_email, roles_by_code)
    _sync_user_ambulances(
        db,
        seed_config["ambulance_assignments"],
        users_by_email,
        ambulances_by_name,
    )
    if "user_competence_assignments" in seed_config:
        _sync_user_competences(
            db,
            seed_config["user_competence_assignments"],
            users_by_email,
            ambulances_by_name,
        )
    if "unavailabilities" in seed_config:
        _sync_unavailabilities(
            db,
            seed_config["unavailabilities"],
            users_by_email,
        )
    if "schedules" in seed_config:
        _seed_schedules(db, seed_config["schedules"], users_by_email, ambulances_by_name)
    if "generated_schedules" in seed_config:
        _generate_and_seed_schedules(
            db,
            seed_config["generated_schedules"],
            ambulances_by_name,
        )


def seed_db(config_name: str | None = None, *, only_if_outdated: bool = False) -> bool:
    selected_config_name = config_name or os.getenv("SEED_CONFIG", "config_1")
    seed_config = _get_seed_config(selected_config_name)
    _validate_seed_config(seed_config)
    target_version = str(seed_config["version"])
    print(
        f"Checking database seed {selected_config_name} "
        f"(target version {target_version})..."
    )

    db: Session = SessionLocal()
    try:
        if engine.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(73644301)"))

        current = db.get(SeedVersion, selected_config_name)
        if only_if_outdated and current and current.version == target_version:
            print("Database seed is already current; no changes needed.")
            db.rollback()
            return False

        print(f"Applying database seed {selected_config_name}:{target_version}...")
        _apply_seed(db, seed_config)
        if current is None:
            current = SeedVersion(profile=selected_config_name, version=target_version)
            db.add(current)
        else:
            current.version = target_version
            current.applied_at = datetime.now(timezone.utc)
        db.commit()
        print("Database seeding completed successfully.")
        return True
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_db(sys.argv[1] if len(sys.argv) > 1 else None)
