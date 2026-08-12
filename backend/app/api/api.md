# Scheduling API

Dokumentácia backendu v UTF-8. Rozbaľ sekciu podľa oblasti.

> Chránené endpointy určujú používateľa len cez `HttpOnly` cookie `scheduling_session`. Klient neposiela `user_id` ani token v hlavičke. Bežné chyby chránených endpointov sú `401` (chýbajúca/neplatná relácia) a `403` (nedostatočné oprávnenie). Neexistujúci alebo neaktívny zdroj vracia `404`.

<details>
<summary><strong>Stav služby a autentifikácia</strong></summary>

### `GET /`

- Oprávnenie: verejné
- Body/parametre: žiadne
- Úspech: `200` — `{"status":"ok"}`

### `POST /auth/google`

- Oprávnenie: verejné
- Body: `{"token":"Google access token"}`
- Úspech: `200` — `{id, email, full_name, login_count}` a relačná cookie
- Ak používateľ nemá žiadnu aktívnu rolu, prihlásenie mu pridelí rolu 1; pri existujúcej role 2, 3 alebo 4 sa rola 1 nepridáva
- Chyby: `401` neplatný token, neoverený e-mail alebo neaktívny účet

### `POST /auth/logout`

- Oprávnenie: prihlásený používateľ
- Body: žiadne
- Úspech: `204` — zruší cookie aj serverovú reláciu
</details>

<details>
<summary><strong>Roly a používatelia</strong></summary>

### `GET /roles`

- Oprávnenie: verejné
- Úspech: `200` — aktívne roly `[{"name":"LEADER","index":2}]`

### `GET /roles/me`

- Oprávnenie: prihlásený používateľ
- Úspech: `200` — aktívne roly prihláseného používateľa

### `GET /users/`

- Oprávnenie: rola 2 alebo vyššia
- Úspech: `200` — aktívni používatelia `{id,email,full_name}`

### `GET /users/{user_id}/roles`

- Oprávnenie: prihlásený používateľ; iba vlastné role
- Parametre: `user_id` v ceste
- Úspech: `200` — pole ID rolí

### `GET /users/role-assignments`

- Oprávnenie: rola 3 alebo vyššia
- Úspech: `200` — aktívni používatelia s detailmi všetkých aktívnych rolí

### `PUT /users/{user_id}/roles`

- Oprávnenie: rola 3 alebo vyššia
- Body: `{"role_ids":[1,2,3]}`
- Spravuje iba roly 1 až 3; rolu 4 zachová a odmietne pokus o jej zmenu
- Prázdne pole odoberie používateľovi všetky roly 1 až 3
- Úspech: `200` — používateľ s aktualizovanými rolami

### `GET /users/by-role?role_id={role_id}`

- Oprávnenie: rola 3 alebo vyššia
- Parametre: povinný `role_id`
- Úspech: `200` — používatelia s `id`, `email`, `full_name`, `is_active`, `roles`, `ambulances`
</details>

<details>
<summary><strong>Ambulancie a manažéri</strong></summary>

Model ambulancie má jedného manažéra cez `managed_by_user_id`.

### Čítanie ambulancií

- `GET /ambulances` — všetky aktívne ambulancie
- `GET /ambulances/standard` — neurgentné ambulancie
- `GET /ambulances/urgent` — urgentné ambulancie

Odpoveď `200`: `{id,name,description,isurgent,managed_by_user_id,is_active}`.

### `POST /ambulances`

- Oprávnenie: rola 3 alebo vyššia
- Body: `{"name":"...","description":"...","isurgent":false,"manager_id":3}`; `manager_id` je voliteľné
- Úspech: `201` — vytvorená ambulancia

### `PUT /ambulances/{ambulance_id}`

- Oprávnenie: rola 3 alebo vyššia
- Body: ľubovoľná časť `name`, `description`, `isurgent`, `manager_id`; `manager_id:null` manažéra odoberie
- Úspech: `200` — upravená ambulancia

### `DELETE /ambulances/{ambulance_id}`

- Oprávnenie: rola 3 alebo vyššia
- Úspech: `204` — soft-delete ambulancie

### Manažér ambulancie

- `PUT /ambulances/{ambulance_id}/manager/{manager_id}` — rola 3, úspech `200`
- `DELETE /ambulances/{ambulance_id}/manager` — rola 3, úspech `204`

Používateľ nastavovaný ako manažér musí byť aktívny a mať aktívnu rolu aspoň 2. Neplatný vstup je `400` alebo `404`.

### Zamestnanci ambulancie

- `GET /ambulances/{ambulance_id}/employees`
- `POST /ambulances/{ambulance_id}/employees` s body `{"user_id":12}`
- `DELETE /ambulances/{ambulance_id}/employees/{user_id}`
- `GET /ambulances/me/managed`
- `GET /ambulances/me/assigned`
- `GET /ambulances/managers/{user_id}/ambulances`
- `GET /ambulances/employees/{user_id}/ambulances`

Práca s konkrétnou ambulanciou vyžaduje rolu 2 pre vlastnú ambulanciu alebo rolu 3. Odpovede sú `200`, `201`, `204`; duplicitné priradenie je `409`.
</details>

<details>
<summary><strong>Kompetencie ambulancie</strong></summary>

Kompetencia obsahuje `id`, `name`, `description`, `ambulance_id`, `required_count` a kompatibilné `count`.

### Kompetencie ambulancie

- `GET /ambulances/{ambulance_id}/competences`
- `POST /ambulances/{ambulance_id}/competences`
- `PUT /ambulances/{ambulance_id}/competences/{competence_id}`
- `DELETE /ambulances/{ambulance_id}/competences/{competence_id}`

Oprávnenie: rola 2 pre vlastnú ambulanciu alebo rola 3. POST body: `{"name":"Sestra","description":"...","required_count":2}`. PUT prijíma časť týchto polí. Odpovede sú `200`, `201`, `204`; chyby navyše `409` pri duplicitnom názve a `422` pri neplatnom počte.

### `GET /ambulances/my-ambulance-competences`

- Oprávnenie: rola 2 alebo vyššia
- Úspech: `200` — `{ambulance_id,ambulance_name,ambulance_description,competences}` pre ambulancie aktuálneho manažéra

### Krátke aliasy číselníka

- `GET /competences?ambulance_id={id}`
- `POST /competences?ambulance_id={id}`
- `PUT /competences/{competence_id}?ambulance_id={id}`
- `DELETE /competences/{competence_id}?ambulance_id={id}`

Majú rovnaké práva, body a odpovede ako CRUD kompetencií ambulancie.

### Kompetencie zamestnancov — tabuľka

- `GET /ambulances/{ambulance_id}/employees/competences`
- `PUT /ambulances/{ambulance_id}/employees/competences`

PUT body: `{"employees":[{"user_id":12,"competence_ids":[1,3]},{"user_id":15,"competence_ids":[]}]}`. Oprávnenie: rola 2 pre vlastnú ambulanciu alebo rola 3. Úspech `200` — zamestnanci s kompetenciami.

### Kompetencie jedného zamestnanca

- `GET /employees/competences?ambulance_id={id}&user_id={id}`
- `POST /employees/competences?ambulance_id={id}&user_id={id}` s body `{"competence_id":1}`
- `DELETE /employees/competences?ambulance_id={id}&user_id={id}&competence_id={id}`
- `GET /ambulances/{ambulance_id}/employees/{user_id}/competences`
- `POST /ambulances/{ambulance_id}/employees/{user_id}/competences` s body `{"competence_id":1}`
- `DELETE /ambulances/{ambulance_id}/employees/{user_id}/competences/{competence_id}`

Oprávnenie: rola 2 pre vlastnú ambulanciu alebo rola 3. Úspech `200`, `201`, `204`; chyby `400`, `404`, `409`, `422`.
### Zamestnanci podla kompetencie

- `GET /ambulances/{ambulance_id}/competences/{competence_id}/employees`

Opravnenie: rola 2 pre vlastnu ambulanciu alebo rola 3. Vracia aktivnych zamestnancov ambulancie, ktori maju priradenu zadanu kompetenciu: `[{"id":12,"full_name":"Meno Priezvisko","email":"meno@nemocnica.sk"}]`. Neexistujuca alebo neaktivna kompetencia, pripadne kompetencia z inej ambulancie, vracia `404`.

</details>

<details>
<summary><strong>Rozvrhy</strong></summary>

Manažér s rolou 2 spravuje iba vlastnú ambulanciu; rola 3 má globálny prístup. Neplatná alebo neaktívna väzba používateľ–ambulancia–kompetencia vracia `400` alebo `404`.

### Vlastný rozvrh

### `GET /schedules/me?month={month}&year={year}`

- Oprávnenie: prihlásený používateľ
- Úspech: `200` — všetky aktívne položky alebo len zvolený mesiac
- Chyby: `422`, ak chýba jeden z parametrov `month`, `year`

### Osobný prehľad (dashboard)

- `GET /schedules/me/next` — najbližšia aktívna služba od dneška. Vždy vracia `200`; pri prázdnom rozvrhu je `next_shift: null`.
- `GET /schedules/me/monthly-statistics` — počet aktuálne naplánovaných služieb v mesiaci: `scheduled_shift_count`, `month`, `year`.
- `GET /schedules/me/worked-statistics` — počet unikátnych odpracovaných dní aktuálneho mesiaca do dneška vrátane: `worked_day_count`, `through_date`, `month`, `year`.

### Rozvrh používateľa

- `GET /schedules/user/{user_id}?month=&year=`
- `POST /schedules?user_id={user_id}`
- `PUT /schedules/entries/{schedule_id}`
- `DELETE /schedules/entries/{schedule_id}`

POST body: `{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}`. PUT môže meniť `competence_id`, `work_date`, `is_active`. Odpovede: `200`, `201`, `204`; chyby `400`, `401`, `403`, `404`, `409`, `422`.

### `PUT /schedules/monthly`

- Oprávnenie: rola 2 v spravovanej ambulancii alebo rola 3
- Body: `{"user_id":1,"month":7,"year":2026,"entries":[{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}]}`
- Úspech: `200` — aktívne položky vo vybranom mesiaci
- Správanie: neodoslané existujúce položky sa deaktivujú, fyzicky sa nemažú

### Rozvrh ambulancie

- `GET /ambulances/{ambulance_id}/schedule?month=&year=`
- `PUT /ambulances/{ambulance_id}/schedule?month=&year=`
- `POST /ambulances/{ambulance_id}/schedule/generate?month=&year=`

GET vracia položky rozdelené podľa používateľa: `user_id`, `user_full_name`, `month`, `year`, `entries`. PUT je kompatibilný endpoint s body `{"entries":[{"user_id":1,"competence_id":2,"work_date":"2026-07-20"}]}`. Oprávnenie: rola 2 pre danú ambulanciu alebo rola 3.

### `POST /ambulances/{ambulance_id}/schedule/generate?month={month}&year={year}`

- Oprávnenie: rola 2 pre spravovanú ambulanciu alebo rola 3 pre ľubovoľnú aktívnu ambulanciu
- Parametre: povinné `month` (`1–12`) a `year` (`2000–2100`)
- Request body: žiadny
- Úspech: `200` — neuložený mesačný návrh s poľami `month`, `year`, `assignment_count` a `entries`
- Každá položka `entries` obsahuje `user_id`, `ambulance_id`, `competence_id`, `work_date`, `user_email`, `user_full_name` a `competence_name`
- Správanie: MILP model obsadí každý deň každú aktívnu kompetenciu danej ambulancie presne počtom `required_count`, povolí najviac jednu rolu človeka denne a zakáže akúkoľvek službu dva dni po sebe aj pri zmene kompetencie. Skutočne nedostupné dni sú zakázané; záznam `PREFERRED` zostáva neutrálny, kým nebude implementovaná optimalizácia preferencií. Existujúce služby v iných ambulanciách blokujú rovnaký aj susedné dni a pravidlo odpočinku platí aj cez hranice mesiaca. Konvexná cieľová funkcia vyrovnáva počet služieb medzi dostupnými kvalifikovanými zamestnancami.
- Endpoint nič nezapisuje. Návrh sa uloží až existujúcim `PUT /ambulances/{ambulance_id}/schedule`.
- Chyby: `401` bez prihlásenia, `403` pri cudzej ambulancii, `404` pri neexistujúcej alebo neaktívnej ambulancii, `409` pri neriešiteľnom modeli a `422` pri neplatnom mesiaci alebo roku
- `409` vracia `detail.message` a `detail.issues`; konflikt podľa možnosti obsahuje dátum, kompetenciu, požadovaný a dostupný počet pracovníkov.
</details>

<details>
<summary><strong>Nedostupnosti</strong></summary>

- `POST /unavailabilities/`
- `GET /unavailabilities/`
- `GET /unavailabilities/{unavailability_id}`
- `PUT /unavailabilities/{unavailability_id}`
- `DELETE /unavailabilities/{unavailability_id}`

Všetky endpointy vyžadujú prihlásenie a povoľujú prácu len nad vlastnými záznamami. POST/PUT prijímajú schému nedostupnosti s dátumom, časom a dôvodom. Úspech: `200`, `201` alebo `204`; chyby `400`, `401`, `403`, `404`, `422`.
</details>
