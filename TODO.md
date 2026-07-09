# Databázová schéma: Nemocničný plánovací systém

Tento dokument definuje relačnú štruktúru pre systém na tvorbu rozvrhov v nemocnici. 

## Všeobecné pravidlá schémy
- Každá tabuľka má primárny kľúč `id` (odporúčané UUID alebo auto-inkrementálny Integer).
- Tabuľky obsahujú štandardné auditné stĺpce pre sledovanie zmien:
  - `created_at` (Timestamp, default: now)
  - `updated_at` (Timestamp, auto-update pri zmene)
  - `is_active` (Boolean, default: true) - slúži na soft-delete záznamov.

---

## 1. Hlavné Entity

### 1.1 Users (Zamestnanci / Používatelia)
Ukladá základné informácie o používateľoch.
* `id` (PK)
* `email` (String, Unique, Index)
* `full_name` (String, Nullable)
* `auth_token` (String, Nullable) - Pre uloženie identifikátora z externého overenia (napr. Google Sub ID).
* `login_count` (Integer, Default: 0) - Počet prihlásení.
* `created_at`, `updated_at`, `is_active`

### 1.2 Roles (Roly v systéme)
Číselník všetkých oprávnení v aplikácii (1=zamestnanec, 2=vedúci, 3=dohľad ambulancie, 4=admin nemocnice).
* `id` (PK)
* `code` (String, Unique) - napr. 'EMPLOYEE', 'ADMIN'
* `name` (String) - Zrozumiteľný názov.
* `level` (Integer) - Hierarchická úroveň roly (1 až 4).
* `created_at`, `updated_at`, `is_active`

### 1.3 Ambulances (Ambulancie / Pracoviská)
Miesta, kde môžu používatelia pracovať.
* `id` (PK)
* `name` (String) - Názov ambulancie (napr. "Chirurgia 1").
* `description` (String, Nullable)
* `created_at`, `updated_at`, `is_active`

### 1.4 Competences (Kompetencie / Zručnosti)
Číselník zručností, ktoré vyžadujú jednotlivé ambulancie a ktorými disponujú používatelia (napr. "Triaž", "Sestra špecialistka", "Lekár atestovaný").
* `id` (PK)
* `name` (String)
* `description` (String, Nullable)
* `created_at`, `updated_at`, `is_active`

### 1.5 Unavailabilities (Nedostupnosť zamestnanca)
Dni, kedy používateľ nemôže pracovať (PN, dovolenka, iné prekážky). 1:N s User.
* `id` (PK)
* `user_id` (FK -> users.id)
* `date_absent` (Date) - Konkrétny deň, kedy nemôže pracovať.
* `reason` (String, Nullable) - Dôvod neprítomnosti (voliteľné).
* `created_at`, `updated_at`, `is_active`

### 1.6 Schedules (Rozvrhy / Služby)
Finálny rozpis služieb. Prepája používateľa, ambulanciu, dátum a kompetenciu, ktorú v danej službe vykonáva.
* `id` (PK)
* `user_id` (FK -> users.id)
* `ambulance_id` (FK -> ambulances.id)
* `competence_id` (FK -> competences.id) - Akú rolu/kompetenciu vykonáva v tento konkrétny deň.
* `work_date` (Date) - Dátum služby.
* `shift_start` (Time, Nullable) - Začiatok služby.
* `shift_end` (Time, Nullable) - Koniec služby.
* `created_at`, `updated_at`, `is_active`

### 1.7 Audit_Logs (Logovanie aktivity)
Záznamy o tom, kto, kedy a čo v aplikácii zmenil. Tieto dáta sa nikdy nemažú ani nemenia.
* `id` (PK)
* `user_id` (FK -> users.id, Nullable pre systémové akcie)
* `action` (String) - Typ akcie (napr. "CREATE_SCHEDULE", "UPDATE_USER").
* `entity_type` (String) - Názov tabuľky, ktorá bola zmenená (napr. "schedules").
* `entity_id` (String/Integer) - ID zmeneného záznamu.
* `changes` (JSON, Nullable) - Detailná história zmien (pôvodný stav vs. nový stav).
* `created_at` (Timestamp) - Kedy k akcii došlo.

---

## 2. Pomocné Prepojovacie Tabuľky (Vzťahy M:N)

### 2.1 user_roles
Každý používateľ môže mať viacero rolí (napr. zamestnanec aj vedúci).
* `user_id` (FK -> users.id)
* `role_id` (FK -> roles.id)
* *(PK je zložený z user_id a role_id)*

### 2.2 user_ambulances
Určuje, na ktorých ambulanciách má používateľ oprávnenie/schopnosť pracovať.
* `user_id` (FK -> users.id)
* `ambulance_id` (FK -> ambulances.id)
* `created_at`, `is_active`

### 2.3 ambulance_competences
Zoznam kompetencií, ktoré sú potrebné pre chod konkrétnej ambulancie.
* `ambulance_id` (FK -> ambulances.id)
* `competence_id` (FK -> competences.id)
* `required_count` (Integer, Default: 1) - Koľko ľudí s touto kompetenciou ambulancia denne potrebuje (užitočné pre optimalizačné algoritmy).

### 2.4 user_competences
Ktoré kompetencie ovláda konkrétny používateľ. 
*(Poznámka pre aplikačnú logiku: Pri priradení do Schedule sa musí skontrolovať, či prienik user_competences a ambulance_competences nie je prázdny).*
* `user_id` (FK -> users.id)
* `competence_id` (FK -> competences.id)
* `created_at`, `is_active`