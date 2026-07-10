# TODO for Codex

## ✅ Task 1 — Implement User Availability Management API

### Objective

Implement a complete CRUD API for managing user availability (work availability calendar).

### Requirements

Create REST endpoints that allow users to:

* Create an availability record.
* Update an availability record.
* Delete an availability record.
* Retrieve availability records.
* Retrieve availability within a given date range.

The API should allow users to specify:

* Available days.
* Unavailable days.
* Reason (optional).
* Date.

### Business Rules

* Users may only manage their own availability.
* Prevent duplicate records for the same user and date.
* Validate input dates.
* Return appropriate HTTP status codes.
* Follow the existing project architecture (routers, services, repositories, schemas, models).

---

## ✅ Task 2 — Ambulance Manager Employee Management

### Objective

Implement endpoints that allow an ambulance manager (Role Level = 2) to manage employees assigned to ambulances.

### Requirements

Create endpoints to:

* List employees assigned to an ambulance.
* Add an employee to an ambulance.
* Remove an employee from an ambulance.

The implementation should use the `user_ambulances` junction table.

### Business Rules

* Only users with **Role Level = 2** may access these endpoints.
* Managers may only manage ambulances that they own (`managed_by_user_id`).
* Prevent duplicate assignments.
* Return proper HTTP status codes.
* Validate that both the user and ambulance exist.
* Keep the implementation consistent with the current architecture.

---

## ✅ Task 3 — Ambulance Manager Competence Management

### Objective

Allow ambulance managers (Role Level = 2) to assign and remove competences for employees working in their ambulance.

### Requirements

Create endpoints to:

* Assign a competence to an employee.
* Remove a competence from an employee.
* List competences assigned to an employee for a specific ambulance.

The implementation should use the `user_competences` junction table.

### Business Rules

* Only users with **Role Level = 2** may perform these operations.
* Managers may only manage employees assigned to their own ambulances.
* A competence may only be assigned if it belongs to the manager's ambulance.
* The employee must already be assigned to the ambulance.
* Prevent duplicate competence assignments.
* Validate all foreign key references.
* Follow the existing project architecture and coding conventions.

