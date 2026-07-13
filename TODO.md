# TODO for Backend

## Task 1 — Create Multiple Database Configuration Profiles

### Objective

Implement a configuration system that supports two separate database initialization profiles.

### Requirements

Create two independent configuration files for database initialization:

* `config_1`
* `config_2`

Each configuration should initialize a separate database with its own seed data.

### Requirements

* Keep the existing database schema unchanged.
* Reuse the current seed logic where possible.
* The application should be able to initialize either configuration independently.
* Organize the configuration so that adding additional profiles in the future is straightforward.

---

## Task 2 — Extend Seed Data for Both Configurations

### Objective

Populate both database configurations with realistic testing data.

### Requirements

For **both configurations**:

* Keep all pre-built users that already exist.
* Add **at least 15 additional users**.
* The additional users should:

  * have unique email addresses,
  * have realistic full names,
  * not be assigned to any ambulance,
  * not have any competences,
  * not have any schedules.

For **Configuration 2 only**:

* Keep the same four primary/pre-built accounts.
* Change the role combinations assigned to these four accounts so they differ from Configuration 1.
* Do not modify the additional 15 generated users unless necessary.

### Notes

* The names and email addresses may be fictional.
* Ensure all generated data satisfies foreign key constraints.
* Avoid duplicate emails.
* Keep the seed deterministic so repeated database initialization always produces the same data.
