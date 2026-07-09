# Antigravity Rule: Backend SQLAlchemy Models

When creating or modifying database models in `backend/models/`, you must strictly adhere to these rules:

## 1. File & Naming Conventions
* Create one isolated file per database table (e.g., `employee.py`, `shift.py`, `clinic.py`). Do not bundle multiple primary models into a single file.
* Class names must use `PascalCase` and represent a singular noun (e.g., `class Shift(Base):`).
* Table names must be explicitly defined using `__tablename__` in lowercase and plural format (e.g., `__tablename__ = "shifts"`).

## 2. Structural Requirements
* Every model must inherit from the shared `Base` class imported from `backend.db.base` or `backend.database`.
* Every table must contain an integer primary key named `id` with an index (`index=True`).
* All foreign key columns must explicitly state the target table and field (e.g., `ForeignKey("clinics.id")`) and use naming convention `target_singular_id`.
* Every field must explicitly state its nullability (`nullable=True/False`). Do not rely on implicit defaults.

## 3. Relationships & Type Hints
* Always define bidirectional relationships using SQLAlchemy `relationship()` and specify `back_populates`.
* Use Python type hinting alongside SQLAlchemy columns where applicable to maximize IDE autocompletion for the developer.