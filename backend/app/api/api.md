# Scheduling API

Dokumentácia backendu. Všetky texty sú uložené v UTF-8.

## Autentifikácia

Chránené endpointy používajú relačnú cookie `scheduling_session`. Frontend neposiela `user_id` ani token v hlavičke. Databáza uchováva iba SHA-256 odtlačok relačného tokenu a jeho expiráciu. Backend pri každej požiadavke overí aktívneho používateľa a aktuálne aktívne roly.

### `POST /auth/google`

- Oprávnenie: verejné
- Body: `{"token":"Google access token"}`
- Úspech: `200`, používateľ `{id, email, full_name, login_count}` a HttpOnly session cookie
- Chyby: `401` neplatný token, neoverený e-mail alebo neaktívny účet

### `POST /auth/logout`

- Oprávnenie: prihlásený používateľ
- Body: žiadne
- Úspech: `204`, relácia v DB aj cookie sa zrušia
- Chyby: `401` neplatná alebo expirovaná relácia

## Roly a používatelia

### `GET /roles/me`

- Oprávnenie: prihlásený používateľ
- Úspech: `200`, napr. `[{"name":"LEADER","index":2}]`
- Chyby: `401`

### `GET /roles`

- Oprávnenie: verejné
- Úspech: `200`, zoznam aktívnych rolí

### `GET /users`

- Oprávnenie: rola 2 alebo vyššia
- Úspech: `200`, aktívni používatelia
- Chyby: `401`, `403`

### `GET /users/{user_id}/roles`

- Oprávnenie: prihlásený používateľ; môže čítať iba svoje role
- Úspech: `200`, pole ID rolí
- Chyby: `401`, `403`

### `GET /users/by-role?role_id={role_id}`

- Oprávnenie: rola 3 alebo vyššia
- Parametre: `role_id` povinný
- Úspech: `200`, používatelia s `id`, `email`, `full_name`, `is_active`, `roles`, `ambulances`
- Chyby: `401`, `403`, `404`

## Ambulancie

Model ambulancie podporuje práve jedného manažéra cez `managed_by_user_id`.

### Čítanie ambulancií

- `GET /ambulances` — všetky aktívne ambulancie
- `GET /ambulances/standard` — neurgentné ambulancie
- `GET /ambulances/urgent` — urgentné ambulancie

Odpoveď `200`: ambulancia obsahuje `id`, `name`, `description`, `isurgent`, `managed_by_user_id`, `is_active`.

### `POST /ambulances`

- Oprávnenie: rola 3 alebo vyššia
- Body: `{"name":"...","description":"...","isurgent":false,"manager_id":3}`; `manager_id` je voliteľné
- Úspech: `201`, vytvorená ambulancia
- Chyby: `400`, `401`, `403`, `404`

### `PUT /ambulances/{ambulance_id}`

- Oprávnenie: rola 3 alebo vyššia
- Body: ľubovoľná časť `name`, `description`, `isurgent`, `manager_id`; `manager_id: null` manažéra odstráni
- Úspech: `200`
- Chyby: `400`, `401`, `403`, `404`

### Manažér ambulancie

- `PUT /ambulances/{ambulance_id}/manager/{manager_id}` — nastaví manažéra
- `DELETE /ambulances/{ambulance_id}/manager` — odstráni manažéra

Oba endpointy vyžadujú rolu 3. Nový manažér musí byť aktívny používateľ s aktívnou rolou aspoň 2. Odpovede sú `200` a `204`; možné chyby sú `401`, `403`, `404`.

### Zamestnanci ambulancie

- `GET /ambulances/{ambulance_id}/employees`
- `POST /ambulances/{ambulance_id}/employees` s body `{"user_id": 12}`
- `DELETE /ambulances/{ambulance_id}/employees/{user_id}`
- `GET /ambulances/me/managed`
- `GET /ambulances/me/assigned`

Zápis a čítanie konkrétnej ambulancie vyžaduje rolu 2 pre vlastnú ambulanciu alebo rolu 3. Duplikát pri priradení je `409`; ostatné bežné chyby sú `400`, `401`, `403`, `404`.

## Kompetencie ambulancie

Kompetencia patrí priamo ambulancii. Obsahuje `id`, `name`, `description`, `ambulance_id`, `required_count` a kompatibilné pole `count`.

### `GET /ambulances/{ambulance_id}/competences`

- Oprávnenie: rola 2 pre vlastnú ambulanciu alebo rola 3
- Úspech: `200`, zoznam aktívnych kompetencií
- Chyby: `401`, `403`, `404`

### `GET /ambulances/my-ambulance-competences`

- Oprávnenie: rola 2 alebo vyššia
- Úspech: `200`, zoznam `{ambulance_id, ambulance_name, ambulance_description, competences}` pre ambulancie aktuálneho manažéra
- Chyby: `401`, `403`

### Zápis kompetencií

- `POST /ambulances/{ambulance_id}/competences`
- `PUT /ambulances/{ambulance_id}/competences/{competence_id}`
- `DELETE /ambulances/{ambulance_id}/competences/{competence_id}`

POST body: `{"name":"Sestra","description":"...","required_count":2}`. PUT prijíma časť týchto polí. DELETE je soft-delete. Vyžadujú sa rovnaké práva ako pri čítaní; odpovede sú `201`, `200`, `204`. Chyby: `400`, `401`, `403`, `404`, `409`, `422`.

### Kompetencie zamestnancov

- `GET /ambulances/{ambulance_id}/employees/competences`
- `PUT /ambulances/{ambulance_id}/employees/competences`

PUT body:

```json
{"employees":[{"user_id":12,"competence_ids":[1,3]},{"user_id":15,"competence_ids":[]}]}
```

Vyžaduje rolu 2 pre vlastnú ambulanciu alebo rolu 3. Odpoveď `200` je tabuľka zamestnancov a ich kompetencií.

## Rozvrhy

Manažér s rolou 2 môže spravovať iba používateľov a ambulancie, ktoré sám spravuje. Rola 3 má globálny prístup. Neplatné alebo neaktívne väzby používateľ–ambulancia–kompetencia sú odmietnuté.

### Vlastný rozvrh

`GET /schedules/me?month={month}&year={year}` vyžaduje prihlásenie. Bez filtrov vracia všetky aktívne položky; s oboma parametrami len vybraný mesiac. Samotný `month` alebo `year` vracia `422`.

### Rozvrh používateľa

- `GET /schedules/user/{user_id}?month=&year=`
- `POST /schedules?user_id={user_id}`
- `PUT /schedules/entries/{schedule_id}`
- `DELETE /schedules/entries/{schedule_id}`

POST body: `{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}`. PUT môže meniť `competence_id`, `work_date`, `is_active`; DELETE záznam deaktivuje. Odpovede sú `200`, `201`, `204`; chyby `400`, `401`, `403`, `404`, `409`, `422`.

### `PUT /schedules/monthly`

- Oprávnenie: rola 2 v spravovanej ambulancii alebo rola 3
- Body:

```json
{"user_id":1,"month":7,"year":2026,"entries":[{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}]}
```

- Úspech: `200`, aktívne položky používateľa vo vybranom mesiaci
- Správanie: neodoslané existujúce položky sa deaktivujú, nevykonáva sa fyzické odstránenie
- Chyby: `400`, `401`, `403`, `404`, `422`

### Rozvrh ambulancie

- `GET /ambulances/{ambulance_id}/schedule?month=&year=`
- `PUT /ambulances/{ambulance_id}/schedule?month=&year=`

GET vracia rozvrh rozdelený podľa používateľov: `user_id`, `user_full_name`, `month`, `year`, `entries`. Bez parametrov použije aktuálny mesiac. PUT je zachovaný kompatibilný endpoint s body `{"entries":[{"user_id":1,"competence_id":2,"work_date":"2026-07-20"}]}`. Vyžaduje rolu 2 pre danú ambulanciu alebo rolu 3.

## Nedostupnosti

- `POST /unavailabilities`
- `POST /unavailabilities/pattern`
- `GET /unavailabilities`
- `GET /unavailabilities/{unavailability_id}`
- `PUT /unavailabilities/{unavailability_id}`
- `DELETE /unavailabilities/{unavailability_id}`

Všetky endpointy vyžadujú prihlásenie a povoľujú operácie iba nad vlastnými záznamami.
