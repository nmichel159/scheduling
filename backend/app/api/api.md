# Scheduling API

Prehľad dostupných endpointov backendu. Každá kapitola zodpovedá jednému súboru v priečinku `app/api`.

> Chránené endpointy identifikujú používateľa výhradne cez serverom vydanú reláciu v `HttpOnly` cookie `scheduling_session`. Klient neposiela `user_id` ani token v hlavičke. Databáza obsahuje iba SHA-256 odtlačok náhodného relačného tokenu a jeho expirácie; Google access token sa nikdy neukladá. Pri každej požiadavke sa podľa odtlačku načíta aktívny používateľ a aktuálne aktívne roly z databázy.

<details>
<summary><strong>auth.py – Autentifikácia</strong></summary>

### `POST /auth/google`

Overí Google access token (vrátane overeného e-mailu), vráti alebo vytvorí lokálneho používateľa a nastaví `HttpOnly`, `SameSite=Lax` session cookie. Token cookie má štandardne platnosť 12 hodín; v DB je uložený iba jeho odtlačok.

- Oprávnenie: verejný endpoint
- Request body: `{"token": "Google access token"}`
- Response `200`: `{"id": 1, "email": "user@example.com", "full_name": "...", "login_count": 1}`
- Chyby: `401` pri neplatnom tokene, neoverenom e-maile alebo neaktívnom používateľovi.

### `POST /auth/logout`

Zruší aktuálnu reláciu v databáze a odstráni session cookie.

- Oprávnenie: prihlásený používateľ
- Request body: žiadne
- Response: `204 No Content`
- Chyby: `401` pri chýbajúcej, neplatnej alebo expirovanej relácii.

</details>

## Doplnenia API (2026-07-20)

### Kompetencie ambulancie

`GET /ambulances/{ambulance_id}/competences` vyžaduje rolu 2 pre vlastnú ambulanciu alebo rolu 3. Path parameter je `ambulance_id`; odpoveď `200` je zoznam kompetencií s `id`, `name`, `description`, `required_count` a kompatibilným `count`. Chyby: `401`, `403`, `404`.

`GET /ambulances/my-ambulance-competences` vyžaduje rolu 2. Bez parametrov vracia `200` so zoznamom `{ambulance_id, ambulance_name, ambulance_description, competences}` pre všetky ambulancie aktuálneho manažéra. Chyby: `401`, `403`.

`POST /ambulances/{ambulance_id}/competences`, `PUT /ambulances/{ambulance_id}/competences/{competence_id}` a `DELETE /ambulances/{ambulance_id}/competences/{competence_id}` majú rovnaké oprávnenia. POST body: `{"name":"...","description":"...","required_count":1}`; PUT prijíma ľubovoľnú podmnožinu týchto polí. POST vracia `201`, PUT `200`, DELETE `204` (soft delete). Chyby: `400/422`, `401`, `403`, `404`.

### Rozvrhy

`GET /schedules/me?month=&year=` vyžaduje prihlásenie. Bez filtrov vracia všetky aktívne položky používateľa; s oboma parametrami iba zvolený mesiac. Samotný `month` alebo `year` je `422`.

`GET /schedules/user/{user_id}?month=&year=`, `POST /schedules?user_id=`, `PUT /schedules/entries/{schedule_id}` a `DELETE /schedules/entries/{schedule_id}` vyžadujú rolu 2 pre používateľa v spravovanej ambulancii alebo rolu 3. POST body: `{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}`. PUT môže meniť `competence_id`, `work_date`, `is_active`; DELETE položku deaktivuje. Odpovede sú `200/201/204`; chyby `400`, `401`, `403`, `404`, `409`, `422`.

`PUT /schedules/monthly` je hromadné uloženie mesiaca. Vyžaduje rovnaké oprávnenia. Body: `{"user_id":1,"month":7,"year":2026,"entries":[{"ambulance_id":1,"competence_id":2,"work_date":"2026-07-20"}]}`. Neodoslané existujúce položky používateľa v mesiaci sa deaktivujú; odpoveď `200` obsahuje aktívne položky. Chyby: `400`, `401`, `403`, `404`, `422`.

`GET /ambulances/{ambulance_id}/schedule?month=&year=` vracia rozvrh po používateľoch (`user_id`, `user_full_name`, `month`, `year`, `entries`); bez filtrov použije aktuálny mesiac. Rola 2 smie len vlastnú ambulanciu, rola 3 ktorúkoľvek. Starší `PUT` na rovnakej URL je zachovaný a prijíma `{"entries":[{"user_id":1,"competence_id":2,"work_date":"2026-07-20"}]}`.

### Administrácia

`POST /ambulances` a `PUT /ambulances/{ambulance_id}` prijímajú voliteľné `manager_id`; rola 3 môže manažéra nastaviť, zmeniť alebo v PUT odstrániť hodnotou `null`. Používateľ musí byť aktívny a mať aktívnu rolu aspoň 2. Model podporuje práve jedného manažéra (`managed_by_user_id`).

`GET /users/by-role?role_id={role_id}` vyžaduje rolu 3. Vráti používateľov s danou aktívnou rolou vrátane `id`, `email`, `full_name`, `is_active`, `roles` a `ambulances`. Chyby: `401`, `403`, `404`.

<details>
<summary><strong>roles.py – Roly</strong></summary>

### `GET /roles/me`

Vráti zoznam rolí prihláseného používateľa. Každá rola obsahuje názov aj číselný index, napríklad:

```json
[
  {"name": "EMPLOYEE", "index": 1},
  {"name": "LEADER", "index": 2}
]
```

### `GET /roles`

Vráti číselník všetkých aktívnych rolí. Každá položka obsahuje názov role a jej číselný index.

</details>

<details>
<summary><strong>ambulances.py – Ambulancie a ich administrácia</strong></summary>

### `GET /ambulances`

Vráti všetky aktívne ambulancie.

### `GET /ambulances/standard`

Vráti iba štandardné ambulancie, pri ktorých je `isurgent = false`.

### `GET /ambulances/urgent`

Vráti iba urgentné ambulancie, pri ktorých je `isurgent = true`.

### `POST /ambulances`

Vytvorí novú ambulanciu. Vyžaduje rolu 3 alebo vyššiu.

### `PUT /ambulances/{ambulance_id}`

Upraví názov, popis alebo typ ambulancie. Vyžaduje rolu 3 alebo vyššiu.

### `DELETE /ambulances/{ambulance_id}`

Deaktivuje ambulanciu. Vyžaduje rolu 3 alebo vyššiu.

### `PUT /ambulances/{ambulance_id}/manager/{manager_id}`

Priradí používateľa ako manažéra ambulancie. Používateľ musí mať minimálne rolu 2. Vyžaduje rolu 3 alebo vyššiu.

### `DELETE /ambulances/{ambulance_id}/manager`

Odoberie aktuálneho manažéra z ambulancie. Vyžaduje rolu 3 alebo vyššiu.

</details>

<details>
<summary><strong>ambulance_employee.py – Zamestnanci a ambulancie</strong></summary>

### `GET /ambulances/{ambulance_id}/employees/competences`

Vráti tabuľku všetkých aktívnych zamestnancov ambulancie a pri každom zamestnancovi zoznam jeho kompetencií.

### `PUT /ambulances/{ambulance_id}/employees/competences`

Prijme celú tabuľku zamestnancov a kompetencií. Kompetencie každého odoslaného zamestnanca zosynchronizuje podľa zoznamu `competence_ids` a vráti aktualizovanú tabuľku.

Príklad tela požiadavky:

```json
{
  "employees": [
    {"user_id": 12, "competence_ids": [1, 3]},
    {"user_id": 15, "competence_ids": []}
  ]
}
```

### `GET /ambulances/me/managed`

Vráti ambulancie, ktoré spravuje prihlásený používateľ.

### `GET /ambulances/me/assigned`

Vráti ambulancie, v ktorých je prihlásený používateľ priradený ako zamestnanec.

### `GET /ambulances/managers/{user_id}/ambulances`

Vráti ambulancie spravované konkrétnym používateľom.

### `GET /ambulances/employees/{user_id}/ambulances`

Vráti ambulancie, v ktorých je konkrétny používateľ priradený.

### `GET /ambulances/{ambulance_id}/employees`

Vráti zoznam zamestnancov priradených k ambulancii.

### `POST /ambulances/{ambulance_id}/employees`

Priradí zamestnanca k ambulancii. Vyžaduje manažéra danej ambulancie alebo administrátora.

### `DELETE /ambulances/{ambulance_id}/employees/{user_id}`

Odoberie zamestnanca z ambulancie.

</details>

<details>
<summary><strong>competence.py / codebooks.py – Číselník kompetencií</strong></summary>

### `GET /competences?ambulance_id={id}`

Vráti kompetencie patriace k určenej ambulancii.

### `POST /competences?ambulance_id={id}`

Vytvorí kompetenciu v číselníku ambulancie.

### `PUT /competences/{competence_id}?ambulance_id={id}`

Upraví názov alebo popis kompetencie.

### `DELETE /competences/{competence_id}?ambulance_id={id}`

Odstráni kompetenciu z číselníka.

Všetky operácie vyžadujú rolu 3 alebo vyššiu, prípadne rolu 2 s vlastníctvom danej ambulancie.

Pôvodné endpointy ostávajú dostupné:

- `GET /ambulances/{ambulance_id}/competences`
- `POST /ambulances/{ambulance_id}/competences`
- `PUT /ambulances/{ambulance_id}/competences/{competence_id}`
- `DELETE /ambulances/{ambulance_id}/competences/{competence_id}`

</details>

<details>
<summary><strong>employee_competences.py / user_competence.py – Priraďovanie kompetencií</strong></summary>

### `GET /employees/competences?ambulance_id={id}&user_id={id}`

Vráti kompetencie priradené konkrétnemu zamestnancovi v ambulancii.

### `POST /employees/competences?ambulance_id={id}&user_id={id}`

Priradí zamestnancovi kompetenciu podľa `competence_id` v tele požiadavky.

### `DELETE /employees/competences?ambulance_id={id}&user_id={id}&competence_id={id}`

Odoberie kompetenciu zamestnancovi.

Pôvodné endpointy s cestou `/ambulances/{ambulance_id}/employees/{user_id}/competences` ostávajú zachované.

</details>

<details>
<summary><strong>users.py – Používatelia</strong></summary>

### `GET /users`

Vráti zoznam aktívnych používateľov. Vyžaduje manažérsku rolu.

### `GET /users/{user_id}/roles`

Vráti ID rolí konkrétneho používateľa. Používateľ môže čítať iba vlastné role.

</details>

<details>
<summary><strong>unavailability.py – Nedostupnosť</strong></summary>

### `POST /unavailabilities`

Vytvorí nedostupnosť prihláseného používateľa.

### `POST /unavailabilities/pattern`

Vytvorí opakujúcu sa nedostupnosť podľa zadaného vzoru.

### `GET /unavailabilities`

Vráti nedostupnosti prihláseného používateľa s voliteľným filtrovaním podľa dátumu.

### `GET /unavailabilities/{unavailability_id}`

Vráti jednu nedostupnosť používateľa.

### `PUT /unavailabilities/{unavailability_id}`

Upraví existujúcu nedostupnosť.

### `DELETE /unavailabilities/{unavailability_id}`

Odstráni nedostupnosť.

</details>

<details>
<summary><strong>schedules.py – Rozvrhy</strong></summary>

### `GET /schedules/me`

Vráti rozvrh prihláseného používateľa iba za aktuálny mesiac. Každá položka obsahuje deň práce, ambulanciu a kompetenciu.

### `GET /ambulances/{ambulance_id}/schedule`

Vráti kompletný rozvrh určenej ambulancie za aktuálny mesiac. Vyžaduje rolu 2 alebo vyššiu; rola 2 musí byť manažérom danej ambulancie.

### `PUT /ambulances/{ambulance_id}/schedule`

Aktualizuje rozvrh ambulancie za aktuálny mesiac podľa odoslaného zoznamu zmien. Existujúce záznamy v aktuálnom mesiaci sa zosynchronizujú s novým zoznamom.

Príklad tela požiadavky:

```json
{
  "entries": [
    {
      "user_id": 12,
      "competence_id": 3,
      "work_date": "2026-07-20"
    }
  ]
}
```

</details>
