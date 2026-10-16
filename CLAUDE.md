# CLAUDE.md

Kontext projektu je v [CONTEXT.md](CONTEXT.md).

## Úloha obrazoviek

- **Zamestnanci** (`frontend/src/views/EmployeesView.jsx`) — prehľadová tabuľka.
  Jeden riadok na človeka, hlavne na čítanie (stav, kompetencie, zaťaženie
  v mesiaci). Editovať sa dá, ale cez profil, ktorý otvorí riadok — nie
  priamo v tabuľke.
- **Pracoviská** (`frontend/src/views/DepartmentsView.jsx`) — hromadné
  vypĺňanie. Všetko, čo sa o ľuďoch na pracovisku nastavuje (aktívny,
  limity služieb, preferencia príplatkové/štandardné/je mu to jedno,
  kompetencie), sa dá vyplniť priamo v bunkách tabuľky pre všetkých naraz
  a uloží sa jedným „Uložiť“. Nové nastavenie zamestnanca patrí aj sem ako
  stĺpec.
