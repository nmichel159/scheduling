# Database Structure

## Overview

This database is designed to manage users, ambulances (clinics/workplaces), competences, roles, work schedules, user unavailability, and audit logs.

The core principles of the data model are:

* A user can work in multiple ambulances.
* Each ambulance owns its own set of competences.
* A user can possess multiple competences.
* Every competence belongs to exactly one ambulance.
* A user can have multiple roles.
* Every schedule assigns a user to a specific ambulance with a specific competence.

---

# Entities

## Users

Represents all users of the system.

### Main Attributes

* id
* email (unique)
* full_name
* auth_token
* login_count
* created_at
* updated_at
* is_active

### Relationships

* 1:N → AuditLogs
* 1:N → Schedules
* 1:N → Unavailabilities
* M:N → Ambulances (via `user_ambulances`)
* M:N → Competences (via `user_competences`)
* M:N → Roles (via `user_roles`)
* 1:N → Ambulances as manager (`managed_by_user_id`)

---

## Ambulances

Represents clinics or workplaces.

### Main Attributes

* id
* name
* description
* managed_by_user_id
* created_at
* updated_at
* is_active

### Relationships

* belongs to one manager (`Users`)
* 1:N → Competences
* 1:N → Schedules
* M:N → Users

---

## Competences

Represents job competences or qualifications.

**Each competence belongs to exactly one ambulance.**

This means that two ambulances may have competences with the same name, but they are stored as separate records.

### Main Attributes

* id
* name
* description
* ambulance_id
* created_at
* updated_at
* is_active

### Relationships

* N:1 → Ambulance
* M:N → Users
* 1:N → Schedules

---

## Roles

Represents user permissions and system roles.

### Main Attributes

* id
* code (unique)
* name
* level
* created_at
* updated_at
* is_active

### Relationships

* M:N → Users

---

## Schedules

Represents work shifts assigned to users.

Each schedule specifies:

* who is working,
* in which ambulance,
* with which competence,
* during which time period.

### Main Attributes

* id
* user_id
* ambulance_id
* competence_id
* work_date
* shift_start
* shift_end
* created_at
* updated_at
* is_active

### Relationships

* N:1 → Users
* N:1 → Ambulances
* N:1 → Competences

---

## Unavailabilities

Represents user absences.

### Main Attributes

* id
* user_id
* date_absent
* reason
* created_at
* updated_at
* is_active

### Relationships

* N:1 → Users

---

## AuditLogs

Stores the audit history of system changes.

### Main Attributes

* id
* user_id
* action
* entity_type
* entity_id
* changes (JSON)
* created_at

### Relationships

* N:1 → Users

---

# Many-to-Many Tables

## user_roles

Associates users with roles.

Relationship:

```
Users * <-> * Roles
```

* A user can have multiple roles.
* A role can be assigned to multiple users.

---

## user_ambulances

Associates users with ambulances.

Relationship:

```
Users * <-> * Ambulances
```

* A user can work in multiple ambulances.
* An ambulance can have multiple users.

---

## user_competences

Associates users with competences.

Relationship:

```
Users * <-> * Competences
```

* A user can possess multiple competences.
* A competence can be assigned to multiple users.

---

# Business Rules

## Users

* A user may have multiple roles.
* A user may belong to multiple ambulances.
* A user may possess multiple competences.
* A user may have multiple scheduled shifts.
* A user may have multiple unavailability records.

---

## Ambulances

* An ambulance may have one manager.
* Every ambulance owns its own competences.
* An ambulance may have multiple employees.
* An ambulance may have multiple scheduled shifts.

---

## Competences

* Every competence belongs to exactly one ambulance.
* Competences with identical names may exist in different ambulances.
* A competence may be assigned to multiple users.
* A competence may appear in multiple schedules.

---

## Scheduling

Each schedule must reference:

* an existing user,
* an existing ambulance,
* an existing competence.

Before creating or updating a schedule, the application should verify that:

1. The user is assigned to the ambulance (`user_ambulances`).
2. The user possesses the required competence (`user_competences`).
3. The competence belongs to the selected ambulance (`competence.ambulance_id == schedule.ambulance_id`).

These constraints are **not enforced by foreign keys** and must be implemented in the application's business logic.

---

# Logical ER Diagram

```
Users
 ├──< AuditLogs
 ├──< Schedules >── Ambulances
 │                   │
 │                   └──< Competences
 │                          │
 │                          └──< Schedules
 │
 ├──< Unavailabilities
 │
 ├──< user_roles >── Roles
 │
 ├──< user_ambulances >── Ambulances
 │
 └──< user_competences >── Competences
```

---

# Important Notes for AI Agents

When designing new functionality, always follow these rules:

1. Never create global competences. Every competence must belong to a specific ambulance.

2. Never assume that a user has only one role. Users may have multiple roles.

3. Never assume that a user belongs to only one ambulance. Users may work across multiple ambulances.

4. Before creating a schedule, always validate the relationship between the user, ambulance, and competence.

5. Preserve the existing many-to-many relationships. Do not duplicate information already represented by junction tables.

6. Any new tables should follow the existing database architecture and maintain referential integrity.

7. Every newly introduced entity should clearly define its relationships (1:1, 1:N, or M:N) together with the appropriate foreign keys.

8. New entity tables should follow the existing naming conventions and structure:

   * `id` as an identity primary key (except for junction tables),
   * `created_at`,
   * `updated_at`,
   * `is_active` for entities that support soft deletion or deactivation.
