# Zadanie pre Antigravity: Implementácia DB modelov a Seeding dát

Ahoj Agent. Potrebujem kompletne prebudovať a zinicializovať databázovú vrstvu pre náš nemocničný plánovací systém s použitím SQLAlchemy a FastAPI/Pydantic architektúry.

Nasleduje presná biznis logika vzťahov a štruktúra testovacích dát, ktoré sa musia automaticky nasadiť (seedovať) pri štarte kontajnera.

---

## 1. Pravidlá a Vzťahy medzi Modelmi
skontroluj ci tie vztahy su

### Presná topológia vzťahov:
1. **User <-> Role (M:N):** Používateľ môže mať 1 až N rolí, rola môže patriť viacerým používateľom. 
2. **User <-> Ambulance (M:N):** Používateľ môže pracovať na viacerých ambulanciách, ambulancia má viacero používateľov.
3. **Ambulance -> Competence (1:N):** Každá ambulancia má vlastnú množinu unikátnych kompetencií. Každá kompetencia patrí **striktne jednej**
4. **User <-> Competence (M:N):** Používateľ môže ovládať viacero kompetencií, kompetencia môže byť ovládaná viacerými používateľmi.
5. **Ambulance -> User (Vedúci - 1:N):** Tabuľka `ambulances` obsahuje stĺpec `managed_by_user_id` (ForeignKey na `users.id`, nullable=True), ktorý určuje vedúceho danej ambulancie.
6. **User -> Unavailabilities (1:N):** Vyťaženosť/nedostupnosť sa viaže na konkrétneho používateľa (jeden používateľ má viacero záznamov dní v roku).
7. **User / Ambulance / Competence -> Schedule (1:N):** Finálna rozvrhová jednotka prepája konkrétneho používateľa, konkrétny deň, konkrétnu ambulanciu a konkrétnu kompetenciu.

---

## 2. Inicializačné (Seed) Dáta

Zabezpeč, aby po spustení migrácie alebo inicializácii databázy docker-compose down -v
docker-compose up --build

boli v systéme natvrdo zapísané tieto dáta:

### Používatelia (Users)
1. `a14325999@gmail.com`
2. `alexthesecond0000@gmail.com`
3. `noro.michel159@gmail.com`
4. `noro.michel@gmail.com`

### Globálne Roly (Roles)
- ID 1: `EMPLOYEE` (Zamestnanec)
- ID 2: `LEADER` (Vedúci)
- ID 3: `AMBULANCE_OVERSEER` (Dohľad nad ambulanciou)
- ID 4: `HOSPITAL_ADMIN` (Celá nemocnica)

### Ambulancie (Ambulances)
1. **ambulancia1** -> Vedúci (`managed_by_user_id`): `noro.michel159@gmail.com`
2. **ambulancia2** -> Vedúci (`managed_by_user_id`): `a14325999@gmail.com`

### Kompetencie (Competences)
*Priradené striktne pod konkrétne ambulancie podľa zadania:*
- **Pod ambulancia1 patrí:** `role1`, `role2`, `role3` (pozn. v DB modeli to budú objekty Competence s názvami role1, role2, role3 priradené k ID ambulancie 1).
- **Pod ambulancia2 patrí:** `rola1`, `rola2`

### Priradenia a Väzby (Asociácie)
- `alexthesecond0000@gmail.com` je bežný zamestnanec (Rola: `EMPLOYEE`) priradený k **ambulancia1**.
- Vedúci pracovníci (`noro.michel159@gmail.com` a `a14325999@gmail.com`) musia mať v systéme priradené minimálne roly `EMPLOYEE` aj `LEADER`, keďže majú aj zamestnanecké povinnosti.

---

## 3. Tvoje úlohy (Krok za krokom)

1. **Skontroluj a uprav SQLAlchemy modely** v priečinku `app/models/` tak, aby presne reflektovali štruktúru vyššie (najmä presun `ambulance_id` do `Competence` a pridanie `managed_by_user_id` do `Ambulance`).
2. **Vytvor alebo uprav asociačné tabuľky** v `app/models/associations.py`.
3. **Napíš inicializačný Python skript** (napr. `app/db/seed.py`), ktorý skontroluje, či dáta existujú, a ak nie, bezpečne ich vloží do databázy.
4. **Uprav vstupný bod aplikácie** alebo docker súbory tak, aby sa tento `seed.py` spustil automaticky po úspešnom vykonaní databázových migrácií, keď zavolám `docker-compose up --build`.