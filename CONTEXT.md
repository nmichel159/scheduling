# Project Context: Hospital Shift Optimization & Scheduling System

## Overview
This application solves the complex task of scheduling hospital shifts for medical clinics. 

### Key Workflow:
1. **Employees (Staff):** Log into the system to submit their unavailabilities (when they cannot work) and specify the types of work/shifts they are qualified to perform based on their specific certifications.
2. **Clinic Managers (Heads of Clinics):** Use the system to automatically or manually generate optimized monthly/weekly shift schedules for their respective clinics based on staff availability, qualifications, and hospital constraints.
3. **Hospital Management (Future Scope):** A high-level analytics layer will be added later for statistics, reporting, and hospital-wide KPIs.

---

## Technical Stack & Architecture
The project is split into a separated frontend and backend structure:
* **Backend:** Python 13 with FastAPI, SQLAlchemy, Alembic (migrations), and Uvicorn.
* **Frontend:** React, Vite, Axios, Zustand (state management), React Router, and Zod (validation).
* **IDE / Tooling:** Structured with `.slnx` solution files for Visual Studio / agent tracking, and `.agents/rules` for AI agent behavior.

---

## Key Directory Structure

```text
├── .agents/
│   └── rules/              # Custom behavioral guidelines and prompt rules for AI agents
├── .vs/
│   ├── project-root.slnx   # Global project solution layout
│   └── scheduling.slnx     # Context layout specifically for scheduling algorithms
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI router endpoints (Endpoints grouped by domain)
│   │   ├── core/           # Configuration, security, JWT authentication, logging
│   │   ├── db/             # Database session setups, base classes, Alembic migration environment
│   │   ├── models/         # SQLAlchemy ORM models (Employees, Clinics, Shifts, Qualifications)
│   │   ├── schemas/        # Pydantic models for request/response serialization & validation
│   │   └── services/       # Core business logic (Shift scheduling optimization algorithms)
├── database/               # Local database storage or migration scripts setup
├── docker/                 # Containerization blueprints for quick deployment
└── frontend/
    ├── public/             # Static public assets
    └── src/                # React source code
        ├── api/            # API client configurations (Axios instances)
        ├── components/     # Shared UI component library
        ├── hooks/          # Custom React hooks
        ├── layouts/        # Page layout blueprints (Sidebar, Navbar, Admin dashboard wrapper)
        ├── locales/        # Localization settings (i18next dictionary definitions)
        ├── router/         # Application routing structure (React Router)
        ├── services/       # Frontend service wrappers interacting with api/
        ├── stores/         # Global application state management (Zustand stores)
        ├── types/          # TypeScript domain model types and type definitions
        └── views/          # Main page views (Login, Staff Calendar, Manager Scheduling Board)