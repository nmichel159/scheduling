# Scheduling API

Prehľad dostupných endpointov backendu. Každá kapitola zodpovedá jednému súboru v priečinku `app/api`.

> Pri chránených endpointoch sa aktuálne používa hlavička `X-User-Id`. Autentifikačná vrstva je oddelená cez provider, takže spôsob prihlasovania sa môže neskôr vymeniť bez úprav doménových endpointov.

<details>
<summary><strong>auth.py – Autentifikácia</strong></summary>

### `POST /auth/google`

Overí Google access token a vráti alebo vytvorí lokálneho používateľa.

</details>

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
