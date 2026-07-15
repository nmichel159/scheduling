## Task 1 — Získanie rolí aktuálneho používateľa (getroles)

### Objective

Vytvoriť endpoint, ktorý umožní frontendu zistiť, aké role má prihlásený používateľ.

### Requirements

* Vytvoriť endpoint, ktorý na základe kontextu prihláseného používateľa (tokenu) vráti zoznam jeho rolí.
* Návratová hodnota musí byť pole (list) názvov rolí priradených danému používateľovi.

---

## Task 2 — Číselník všetkých rolí v systéme

### Objective

Implementovať endpoint pre získanie kompletného zoznamu všetkých rolí definovaných v systéme.

### Requirements

* Vytvoriť endpoint, ktorý vráti číselník všetkých rolí.
* Každá rola v zozname musí obsahovať:
* **názov roly** (string)
* **index roly** (integer)



---

## Task 3 — Rozdelenie zoznamu ambulancií na štandardné a urgentné

### Objective

Rozšíriť API pre prácu s ambulanciami o možnosť špecifického výberu podľa ich typu, pričom existujúce endpointy zostanú zachované.

### Requirements

* Ponechať pôvodné všeobecné funkcie (get, list, update, delete...) pre ambulancie bez zmeny.
* Dorobiť dva nové spôsoby volania zoznamu ambulancií:
1. Získanie zoznamu bežných ambulancií, kde platí podmienka `is_urgent = false`.
2. Získanie zoznamu urgentných ambulancií (urgenty), kde platí podmienka `is_urgent = true`.

implemtovat aj v ktory je ucastnik veduci (vystup list)

implemtovat aj v ktorych je zamenancom (vystup list)



---

## Task 4 — Autorizovaná správa číselníka kompetencií

### Objective

Implementovať bezpečné CRUD operácie pre číselník kompetencií s obmedzením prístupu na základe rolí.

### Requirements

* Vytvoriť endpointy pre get list, update a delete kompetencií.
* Implementovať kontrolu prístupových práv (Authorization):
* Akciu môže vykonať používateľ s **Rolou 2** iba v prípade, ak je **manažérom** danej ambulancie.
* Akciu môže vykonať používateľ s **Rolou 3 a vyššou** (Admin) bez obmedzení.
* Pre ostatné roly alebo neoprávnených manažérov vrátiť chybu `403 Forbidden`.



---

## Task 5 — Autorizovaná správa priraďovania kompetencií zamestnancom

### Objective

Implementovať endpointy na priraďovanie a odoberanie kompetencií konkrétnym zamestnancom pod rovnakým autorizačným modelom ako v Tasku 4.

### Requirements

* Vytvoriť endpointy pre priradenie, aktualizáciu a zmazanie väzby medzi kompetenciou a zamestnancom (get list, update, delete).
* Zachovať identickú kontrolu práv ako v Tasku 4:
* Povolené len pre **Rolu 2** (ak je manažérom príslušnej ambulancie) alebo **Rolu 3 a vyššiu**.



---

## Task 6 — Správa číselníka ambulancií a priraďovanie manažérov pre Rolu 3

### Objective

Umožniť administrátorom (Rola 3) plnú editáciu číselníka ambulancií vrátane správy priradených manažérov.

### Requirements

* Sprístupniť editáciu číselníka ambulancií (get, list, update, delete, atď.) **výhradne pre používateľov s Rolou 3**.
* Implementovať funkciu na **pridanie (priradenie)** manažéra k danej ambulancii.
* Implementovať funkciu na **odobranie** manažéra z ambulancie.

---

## Zoznam očakávaných metód na implementáciu

Pre úspešné splnenie všetkých úloh je potrebné implementovať/upraviť nasledujúce backendové metódy a API endpointy:

### Správa rolí (Tasks 1 & 2)

* `GET /roles/me` — Vráti zoznam rolí prihláseného používateľa (`get_user_roles`)
* `GET /roles` — Vráti kompletný zoznam rolí s indexmi (`list_all_roles`)

### Ambulancie & Urgenty (Task 3)

* `GET /ambulances/standard` — Načíta ambulancie, ktoré nie sú urgentné (`get_standard_ambulances`)
* `GET /ambulances/urgent` — Načíta urgentné ambulancie (`get_urgent_ambulances`)

### Číselník kompetencií (Task 4)

* `GET /competences` — Načíta zoznam kompetencií (`list_competences`)
* `POST /competences` — Vytvorí novú kompetenciu (`create_competence`) - *Vyžaduje Rolu 3 alebo Rolu 2 (manažér)*
* `PUT /competences/{id}` — Upraví kompetenciu (`update_competence`) - *Vyžaduje Rolu 3 alebo Rolu 2 (manažér)*
* `DELETE /competences/{id}` — Vymaže kompetenciu (`delete_competence`) - *Vyžaduje Rolu 3 alebo Rolu 2 (manažér)*

### Priraďovanie kompetencií (Task 5)

* `GET /employees/competences` — Zoznam priradených kompetencií (`list_user_competences`)
* `POST /employees/competences` — Priradí kompetenciu zamestnancovi (`assign_competence_to_user`) - *Vyžaduje Rolu 3 alebo Rolu 2 (manažér)*
* `DELETE /employees/competences` — Odoberie kompetenciu zamestnancovi (`remove_competence_from_user`) - *Vyžaduje Rolu 3 alebo Rolu 2 (manažér)*

### Administrácia ambulancií & Manažérov (Task 6)

* `POST /ambulances` — Vytvorí novú ambulanciu (`create_ambulance`) - *Vyžaduje Rolu 3*
* `PUT /ambulances/{id}` — Upraví detaily ambulancie (`update_ambulance`) - *Vyžaduje Rolu 3*
* `DELETE /ambulances/{id}` — Odstráni ambulanciu (`delete_ambulance`) - *Vyžaduje Rolu 3*
* `PUT /ambulances/{id}/manager/{manager_id}` — Priradí manažéra k ambulancii (`assign_manager_to_ambulance`) - *Vyžaduje Rolu 3*
* `DELETE /ambulances/{id}/manager` — Odoberie manažéra z ambulancie (`remove_manager_from_ambulance`) - *Vyžaduje Rolu 3*