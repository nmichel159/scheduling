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

Copy the environment template and replace the placeholder password and secret:

```powershell
Copy-Item .env.example .env
```


2. **Build and start the containers** in detached mode (PowerShell):
```powershell
.\start.ps1 -Detached

```


This command automatically:
* Builds the React frontend container.
* Builds the Python FastAPI backend container.
* Retries one transient Docker BuildKit snapshot failure automatically.
* Applies pending Alembic database migrations before the backend starts.
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

### UI rule: clickable text = clickable field

When a piece of text acts as a button (a table cell, a list row, a name in a
grid), the **whole field around it is the click target**, not just the glyphs
of the text. The button element must fill its cell/row — `display: block` or
`flex` with `width: 100%` and the cell's padding moved onto the button — so the
user can click anywhere in the field and still hit it.

Clicking exactly on the letters and nothing else is a miss target: it is
invisible where it starts and ends, and it feels broken on a wide cell with a
short name. Example: the employee name in the competence matrix
(`.cmatrix-row-name`) opens the employee detail — the entire name cell is the
button.

### Automatic test/demo data

The backend startup runs the database bootstrap before Uvicorn. Schema creation is
always safe to run, while deterministic mock data is updated only when explicitly
enabled:

```env
AUTO_SEED=true
SEED_CONFIG=config_1
```

Each seed profile declares a version. The backend stores applied versions in
`seed_versions` and skips an already-current profile. Increment the profile's
`version` whenever its data changes. Keep `AUTO_SEED=false` (the default) for
production databases; enable it only for CI, preview, test, or controlled demo
environments.

#### What `config_1` contains

`config_1` is the demo world. Every schedule in it is produced by the same MILP
generator the application uses, so a freshly seeded database opens on ten
months of 2026 rather than on empty calendars. The departments are named after
real ones; only the people on their rosters are invented.

| Department | Urgent | People | Roles | Where the people come from |
| --- | --- | --- | --- | --- |
| `I.KAIM` | no | 57 | 7, of which 3 to 7 are staffed in any given month | the department's own roster, reinforced with invented colleagues |
| `II.KAIM` | no | 23 | 3 | invented people, shuffled into the roster at random |
| `KDAIM` | no | 19 | 2 | invented people, shuffled into the roster at random |
| `KUM` | yes | 35 | 2 | borrowed from `I.KAIM` and from `II.KAIM` |

January to September are seeded as approved schedules and October as a
generated draft that is still waiting for its manager, which is the state a
planner is actually in partway through a year.

Four properties of the profile are worth knowing before you change it:

* **Demand moves from month to month in I.KAIM.** Each month is generated from
  its own entry in `MONTHLY_REQUIREMENTS`, so a quiet month staffs three roles
  and a busy one all seven, and the daily headcount ranges from four to nine. A
  role a month leaves out is simply not staffed that month. The levels of the
  **last** generated month stay in `competences` afterwards, so the
  configuration a manager opens is the newest one a schedule was built from.
* **Everybody has opinions about the calendar.** Every person gets 8 to 12
  blocked days and 2 to 4 requested days per month, drawn from a hash of the
  person and the month rather than from the clock. Blocked days are hard
  constraints; requested days only order schedules that are already equally
  balanced.
* **The urgent department is scheduled last, on purpose.** Its roster is already
  committed elsewhere by then, so it exercises the rule that a duty in one
  department blocks the same and the neighbouring day in every other one. That
  is also why all of its people are qualified for both of its roles: the few
  days each of them has left have to be usable for whichever role is open.
* **The year ends on the settled configuration.** September and October run the
  four roles the clinic has always run, so the staffing levels left behind in
  `competences` are the ones a manager would recognise rather than one of the
  experiments in the middle of the year.

`config_2` is the older, smaller profile (`ambulancia1`..`ambulancia4` and four
urgent workplaces) and is kept for tests and for comparison.

### Mailing schedules to the clinics

A clinic does not log in: the people who need the finished month read it in a
mailbox. Each workplace therefore keeps its own list of addresses, maintained
by the scheduler who manages it, on **Rozposlanie rozpisu**
(`/ambulances/mail`).

Only an approved month can be sent — an unapproved package is a draft the
employees themselves cannot see yet. The message carries the month as a
day-by-day list and the same rows as a CSV attachment, and every attempt is
recorded, failures included, so "when did they get it, and which version" has
an answer.

Configure the mail server through the `SMTP_*` / `MAIL_*` variables in
`.env.example`. With no mail server at hand, set `MAIL_DRY_RUN=true`: the whole
path runs, the message goes to the backend log, and the attempt is recorded as
a dry run.

### Printing the month

The schedule is worked out on screen and lived with on paper, so **Tlac rozvrhu**
(`/ambulances/print`) exists to produce the wall copy: a row per day, a column
per competence, names in the squares. It never runs onto a second sheet. The
type size is not configured but measured -- the table is laid out against the
printable area of an A4 and the size halved in on until the largest one that
still fits is found -- so a month with three competences and a month with
fifteen both come out as one page.

The same month leaves in three ways, and all three are files rather than
dialogs. **Stiahnut PDF** writes the sheet with jsPDF; **Excel** writes a real
`.xlsx`, and **CSV** a semicolon-separated file with a byte-order mark, which is
what makes Excel open it with the columns already split. The spreadsheet and the
CSV are assembled by hand in `frontend/src/utils/tableExport.js` -- an `.xlsx` is
a zip of six short XML parts, and carrying a spreadsheet library in the bundle
to write them is a poor trade.

The PDF carries its own font. A PDF's built-in Helvetica is encoded for Western
Europe and has no glyph at all for c-caron or t-caron, so half the surnames on a
Slovak rota would come out broken; `frontend/src/assets/fonts/` therefore holds
DejaVu Sans cut down to Latin and Latin Extended-A, 22 kB instead of the 750 kB
the whole face weighs. The one-page rule is kept the same way it is on screen,
only counted rather than measured: the table is laid out, its pages are counted,
and the type size is halved in on until the largest one that still leaves a
single page is found. The rows are then stretched to reach the foot of the page
-- and if stretching costs a page after all, the unstretched sheet stands, since
one page is the promise and filling it is only a courtesy.

Ctrl+P still works on this screen and prints the same sheet and nothing else,
but it is the fallback, not the way out.

The second layout turns the month on its side, a row per person and a column per
day, which is the sheet somebody reads to find their own name rather than the
day's cover. Its printed squares carry the competence's number from the legend,
since a name will not fit in a column a month wide; the exported files, which
have no such limit, carry the competence name itself.

### Rebuilding a database from scratch

Seeding upserts by natural key and only deletes inside the narrow scopes a
profile declares, so switching profiles never produces a clean database: rows
from an earlier profile stay. To rebuild an environment from nothing, clear it
explicitly first:

```bash
docker compose exec backend python -m app.db.reset config_1 --yes
```

This deletes every row of every mapped table and reapplies the profile in a
single transaction, so an infeasible profile rolls back instead of leaving the
database empty. The table list is read from the ORM metadata, which does not
describe Alembic's `alembic_version` table -- the schema and its migration
history therefore survive a reset, and only rows are removed.

A reset of `config_1` solves 40 monthly schedules -- ten months in each of the
four departments -- and takes well under a minute; the progress of each one is
printed as it is generated, together with whether it was seeded approved.

The command refuses to run without `--yes` and prints the connection target
first, because nothing distinguishes a local database from a production one at
the point of use. Two consequences are worth planning for:

* Every session token lives in `users`, so a reset logs everybody out.
* A user absent from the profile is recreated on next login with the `EMPLOYEE`
  role only. Put the accounts you demo with in the profile, with the roles they
  need, and seed before logging back in.
