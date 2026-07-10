import os
import sys
from sqlalchemy import select, text
from sqlalchemy.orm import Session

# Add the project root to python path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.session import engine, SessionLocal, Base
from app.models.role import Role
from app.models.user import User
from app.models.ambulance import Ambulance
from app.models.competence import Competence
from app.models.associations import UserRole, UserAmbulance

def seed_db():
    print("Starting database seeding...")
    
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        # 1. Seed Roles
        roles_data = [
            {"id": 1, "code": "EMPLOYEE", "name": "Zamestnanec", "level": 1},
            {"id": 2, "code": "LEADER", "name": "Vedúci", "level": 2},
            {"id": 3, "code": "AMBULANCE_OVERSEER", "name": "Dohľad nad ambulanciou", "level": 3},
            {"id": 4, "code": "HOSPITAL_ADMIN", "name": "Celá nemocnica", "level": 4},
        ]
        
        roles_by_code = {}
        for r_info in roles_data:
            role = db.query(Role).filter(Role.code == r_info["code"]).first()
            if not role:
                # Check if the ID is already taken
                role_by_id = db.query(Role).filter(Role.id == r_info["id"]).first()
                if role_by_id:
                    role = role_by_id
                    role.code = r_info["code"]
                    role.name = r_info["name"]
                    role.level = r_info["level"]
                else:
                    role = Role(id=r_info["id"], code=r_info["code"], name=r_info["name"], level=r_info["level"])
                    db.add(role)
                print(f"Created/Updated Role: {r_info['code']}")
            else:
                role.name = r_info["name"]
                role.level = r_info["level"]
            roles_by_code[r_info["code"]] = role
        
        db.commit()
        
        # Reset roles primary key sequence if on Postgres
        if engine.dialect.name == 'postgresql':
            db.execute(text("SELECT setval(pg_get_serial_sequence('roles', 'id'), coalesce(max(id), 1)) FROM roles;"))
            db.commit()

        # 2. Seed Users
        users_data = [
            {"email": "a14325999@gmail.com", "full_name": "Leader A"},
            {"email": "alexthesecond0000@gmail.com", "full_name": "Alex the Second"},
            {"email": "noro.michel159@gmail.com", "full_name": "Noro Michel 159"},
            {"email": "noro.michel@gmail.com", "full_name": "Noro Michel"},
        ]
        
        users_by_email = {}
        for u_info in users_data:
            user = db.query(User).filter(User.email == u_info["email"]).first()
            if not user:
                user = User(email=u_info["email"], full_name=u_info["full_name"], login_count=0)
                db.add(user)
                print(f"Created User: {u_info['email']}")
            else:
                user.full_name = u_info["full_name"]
            users_by_email[u_info["email"]] = user
        
        db.commit()

        # 3. Seed Ambulances
        ambulances_data = [
            {"name": "ambulancia1", "description": "Prvá ambulancia", "manager_email": "noro.michel159@gmail.com"},
            {"name": "ambulancia2", "description": "Druhá ambulancia", "manager_email": "a14325999@gmail.com"},
        ]
        
        ambulances_by_name = {}
        for a_info in ambulances_data:
            manager = users_by_email.get(a_info["manager_email"])
            manager_id = manager.id if manager else None
            
            ambulance = db.query(Ambulance).filter(Ambulance.name == a_info["name"]).first()
            if not ambulance:
                ambulance = Ambulance(
                    name=a_info["name"],
                    description=a_info["description"],
                    managed_by_user_id=manager_id
                )
                db.add(ambulance)
                print(f"Created Ambulance: {a_info['name']} managed by {a_info['manager_email']}")
            else:
                ambulance.managed_by_user_id = manager_id
                ambulance.description = a_info["description"]
            ambulances_by_name[a_info["name"]] = ambulance
        
        db.commit()

        # 4. Seed Competences
        competences_data = {
            "ambulancia1": ["role1", "role2", "role3"],
            "ambulancia2": ["rola1", "rola2"]
        }
        
        for amb_name, comp_list in competences_data.items():
            amb = ambulances_by_name.get(amb_name)
            if not amb:
                continue
            for comp_name in comp_list:
                comp = db.query(Competence).filter(
                    Competence.name == comp_name,
                    Competence.ambulance_id == amb.id
                ).first()
                if not comp:
                    comp = Competence(name=comp_name, ambulance_id=amb.id)
                    db.add(comp)
                    print(f"Created Competence: {comp_name} under {amb_name}")
        
        db.commit()

        # 5. Seed Associations
        # - alexthesecond0000@gmail.com is linked to ambulancia1 and role EMPLOYEE
        user_alex = users_by_email.get("alexthesecond0000@gmail.com")
        role_emp = roles_by_code.get("EMPLOYEE")
        amb1 = ambulances_by_name.get("ambulancia1")
        
        if user_alex and role_emp:
            ur = db.query(UserRole).filter(UserRole.user_id == user_alex.id, UserRole.role_id == role_emp.id).first()
            if not ur:
                db.add(UserRole(user_id=user_alex.id, role_id=role_emp.id))
                print(f"Assigned role EMPLOYEE to alexthesecond0000@gmail.com")
        
        if user_alex and amb1:
            ua = db.query(UserAmbulance).filter(UserAmbulance.user_id == user_alex.id, UserAmbulance.ambulance_id == amb1.id).first()
            if not ua:
                db.add(UserAmbulance(user_id=user_alex.id, ambulance_id=amb1.id))
                print(f"Assigned alexthesecond0000@gmail.com to ambulancia1")

        # Leaders: noro.michel159@gmail.com and a14325999@gmail.com must have EMPLOYEE and LEADER roles
        role_ldr = roles_by_code.get("LEADER")
        leaders_emails = ["noro.michel159@gmail.com", "a14325999@gmail.com"]
        for email in leaders_emails:
            user_leader = users_by_email.get(email)
            if not user_leader:
                continue
            
            # Roles assignment
            for role_obj in [role_emp, role_ldr]:
                if role_obj:
                    ur = db.query(UserRole).filter(UserRole.user_id == user_leader.id, UserRole.role_id == role_obj.id).first()
                    if not ur:
                        db.add(UserRole(user_id=user_leader.id, role_id=role_obj.id))
                        print(f"Assigned role {role_obj.code} to {email}")
            
            # Link to managed ambulance
            target_amb_name = "ambulancia1" if email == "noro.michel159@gmail.com" else "ambulancia2"
            target_amb = ambulances_by_name.get(target_amb_name)
            if target_amb:
                ua = db.query(UserAmbulance).filter(UserAmbulance.user_id == user_leader.id, UserAmbulance.ambulance_id == target_amb.id).first()
                if not ua:
                    db.add(UserAmbulance(user_id=user_leader.id, ambulance_id=target_amb.id))
                    print(f"Assigned {email} to {target_amb_name}")
                    
        db.commit()
        print("Database seeding completed successfully.")
        
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
