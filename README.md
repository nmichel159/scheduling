# Hospital Shift Optimization & Scheduling System

An automated scheduling and shift optimization platform designed for hospital clinics (such as the Louis Pasteur University Hospital). The system balances staff availability, specialized qualifications, and complex clinical constraints using Mathematical Optimization.

---

## 🚀 Project Overview

The application streamlines clinical scheduling by dividing the workflow into two major pillars:

1. **Core Administration & Tracking (Phase 1):**
* **Employees:** Log in to submit their unavailabilities and manage their medical qualifications.
* **Clinic Managers:** Oversee specific clinics, manually adjust schedules, and manage staff constraints.


2. **Automated Optimization (Phase 2):**
* Uses a Linear Programming (LP) solver to automatically construct optimal monthly or weekly shift schedules, fully respecting employee unavailabilities and required clinical credentials.



---

## 🛠️ Technical Stack

* **Frontend:** React, Vite, TypeScript, Zustand (State Management), Axios
* **Backend:** Python (FastAPI), SQLAlchemy (ORM), Alembic (Migrations)
* **Database:** PostgreSQL
* **Containerization:** Docker & Docker Compose

---

## 📂 Project Structure

```text
├── .agents/
│   └── rules/              # Custom behavioral guidelines for AI development agents
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI REST endpoints
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic data validation and serialization
│   │   └── services/       # Core business logic and LP optimization algorithms
│   └── database/           # DB engine sessions and migrations
├── frontend/
│   └── src/
│       ├── api/            # API client configurations (Axios)
│       ├── components/     # Reusable UI component library
│       ├── stores/         # Global application state (Zustand)
│       └── views/          # Page layouts (Manager Board, Calendars)
├── docker-compose.yml      # Orchestrates Python, React, and PostgreSQL containers
└── CONTEXT.md              # Global technical architectural context

```

---

## ⚡ Quick Start (Docker Deployment)

The easiest way to run the entire stack (React frontend, FastAPI backend, and PostgreSQL database) is using Docker Compose.

### Prerequisites

Make sure you have [Docker](https://www.docker.com/) and **Docker Compose** installed on your system.

### Running the Application

1. **Clone the repository** and navigate to the root directory:
```bash
git clone <repository-url>
cd scheduling

```


2. **Spin up the containers** in detached mode:
```bash
docker compose up -d --build

```


This command automatically:
* Builds the React frontend container.
* Builds the Python FastAPI backend container.
* Pulls and initializes the PostgreSQL database.
* Links them all under a single shared network.


3. **Verify the services are running**:
```bash
docker compose ps

```


4. **Access the applications**:
* **Frontend (React UI):** [http://localhost:3000](http://localhost:3000) (or the port specified in your `docker-compose.yml`)
* **Backend API Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)



### Stopping the Services

To stop and remove all containers, networks, and associated volumes:

```bash
docker compose down -v

```

---

## 🧑‍💻 Development Rules & Guidelines

If you are modifying this project or using an AI developer agent (like Antigravity), you **must** strictly adhere to the contracts defined in `.agents/rules/`:

* **`global.md`**: Enforces strict English code, docstrings, type hinting, and structural modularity.
* **`backend.md`**: Mandates a strict 1:1:1 domain decoupling (SQLAlchemy Models ↔ Pydantic Schemas ↔ FastAPI Routers).
* **`database.md`**: Outlines transaction safety boundaries and Alembic migration protocols.
* **`database-schema.md`**: Defines the exact relational database layout.
