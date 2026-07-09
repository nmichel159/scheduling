# Antigravity Rule: Backend Architecture & Development Standards

This document specifies the mandatory structural, architectural, and behavioral rules for all Python/FastAPI backend code. Every file created or modified in `backend/` must strictly comply with these directives.

---

## 1. Modular Architecture Strategy
* **Strict 1:1:1 Domain Mapping:** For any business domain (e.g., `Shift`, `Employee`, `Clinic`, `Qualification`), code must be decoupled across exactly three separated layers. Putting models, schemas, or routing logic into a single monolithic file is strictly forbidden.
* **Directory Structure Enforce:**
  * `backend/models/{domain}.py` -> Pure SQLAlchemy definition.
  * `backend/schemas/{domain}.py` -> Pure Pydantic data serialization/validation.
  * `backend/api/v1/{domain}.py` -> Pure FastAPI router endpoints.

---

## 2. Layer-Specific Implementation Rules

### A. SQLAlchemy Models (`backend/models/`)
* **Naming:** Classes must be singular `PascalCase` (e.g., `class Shift(Base):`), and tables must be explicitly pluralized lowercase using `__tablename__ = "{domain}s"`.
* **Primary Keys:** Every model must have an integer primary key named exactly `id` with `index=True`.
* **Foreign Keys:** Must use explicit target tables and field mappings (e.g., `ForeignKey("clinics.id")`) following the naming pattern `target_singular_id`.
* **Nullability & Relations:** Always explicitly declare `nullable=True/False`. Always define bidirectional relations using `relationship()` with matching `back_populates`.

### B. Pydantic Schemas (`backend/schemas/`)
Every business domain must implement exactly 4 distinct Pydantic schemas to manage data lifecycles cleanly:
1. `{Domain}Base`: Shared fields between read and write operations.
2. `{Domain}Create`: For resource creation via `POST`. Contains all strictly required fields.
3. `{Domain}Update`: For resource mutation via `PUT`/`PATCH`. **All fields must be optional (`Optional[...] = None`)** to inherently support partial payload parsing.
4. `{Domain}Response`: For JSON serialization returned to the frontend. Must include the `id` field and the configuration block:
   ```python
   class Config:
       from_attributes = True