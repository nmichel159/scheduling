# Antigravity (AG) Global Development Rules & Guidelines

This document outlines the strict global engineering standards, structural requirements, and coding workflows that must be followed by the AI Agent (Antigravity) across the entire project lifecycle.

---

## 1. Code Language & Documentation Standards
* **Implementation Language:** All source code (variable names, functions, classes, database fields, API endpoints) must be written exclusively in **English**.
* **Inline Comments:** Code must be clearly commented in English. Focus on *why* a complex piece of logic exists, not just *what* it does.
* **Docstrings & Types:** 
  * Every Python function/class must include valid docstrings (Google or Sphinx style) and explicit Python Type Hints.
  * Every TypeScript function/component must have explicit type definitions or interfaces. Avoid the `any` type at all costs.

---

## 2. Strict Modularity & Separation of Concerns
* **No Monolithic Files:** Code must be split into logical layers and individual files. Putting unrelated logic, utilities, or multiple major components into a single file is strictly prohibited.
* **Backend Layering (FastAPI):**
  * `models/`: Pure SQLAlchemy ORM database definitions.
  * `schemas/`: Pure Pydantic data validation and serialization models.
  * `api/`: Router definitions and request handling only. No raw business logic or direct DB mutations here.
  * `services/`: Core business logic, data processing, and scheduling optimization algorithms.
* **Frontend Layering (React + TypeScript):**
  * Keep components atomic. Maximize reusability.
  * Separate UI layout (`views/`/`components/`) from business state (`stores/` with Zustand) and API communication (`services/`/`api/`).

---

## 3. AI Agent Workflow & Thought Process
Before generating any code, modifying a file, or outputting a solution, Antigravity must execute the following workflow:

1. **Context Discovery:** Read the project blueprint (`context.md`) and check the active solution layouts (`.slnx` files) to understand where the change fits.
2. **Impact Assessment:** Analyze if the change impacts both frontend and backend (e.g., changing a database field requires updating the SQLAlchemy model, Pydantic schema, FastAPI endpoint, TypeScript interface, and Zustand store).
3. **Plan Refinement:** Present a brief, structured plan of which files will be created or modified *before* dumping raw code blocks.

---

## 4. Architectural Safeguards (Hospital Scheduling Domain)
* **Clinic Isolation:** Ensure all API endpoints filtering or modifying shifts strictly enforce validation at the clinic level. A manager from Clinic A must never be allowed to view or manipulate schedules for Clinic B.
* **Constraint Validation:** Any logic writing to the database must run validation checks against `EmployeeUnavailability` and `EmployeeQualifications` before committing a shift assignment.
* **Idempotency & Transactions:** Database writes, especially during complex matrix operations like scheduling generation, must be wrapped in transactional blocks (`db.begin()`) to prevent partial or corrupted states.

---

## 5. Error Handling & Logging
* **Backend:** Do not use generic `try-except` blocks without action. Implement structured HTTP Exceptions with precise status codes (e.g., `400 Bad Request` for constraint violations, `403 Forbidden` for cross-clinic access). Use the internal logging layer to trace failures.
* **Frontend:** Implement robust data validation using Zod on form submissions. Gracefully catch API errors and display actionable messages to the user via UI error states.