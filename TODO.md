# TODO

> **Dôležité:** Všetky nové alebo upravené endpointy je potrebné zdokumentovať v súbore `api.md`. Dokumentácia musí obsahovať minimálne názov endpointu, HTTP metódu, URL, požadované oprávnenia, vstupné parametre, request body, response body a možné chybové odpovede.

---

## 1. Ambulance Competences

Vytvoriť a skontrolovať endpointy súvisiace s tabuľkou `ambulance_competences`.

### 1.1 Zobrazenie kompetencií ambulancie

Vytvoriť endpoint, ktorý po zadaní `ambulance_id` vráti zoznam všetkých kompetencií priradených k danej ambulancii.

Každá položka musí obsahovať minimálne:

* identifikátor kompetencie,
* názov kompetencie,
* počet požadovaných pracovníkov alebo hodnotu `count`,
* prípadne ďalšie existujúce údaje z tabuľky `ambulance_competences`.

### 1.2 Endpoint `my-ambulance-competences`

Vytvoriť endpoint `my-ambulance-competences`, ktorý vráti kompetencie všetkých ambulancií, v ktorých je aktuálne prihlásený používateľ manažérom.

Výsledok musí byť rozdelený podľa ambulancií. Každá ambulancia musí obsahovať:

* `ambulance_id`,
* základné informácie o ambulancii,
* zoznam kompetencií ambulancie,
* počet pre každú kompetenciu.

Prístup k endpointu má používateľ s rolou `2`.

### 1.3 Editovanie kompetencií ambulancie

Vytvoriť endpointy na pridávanie, úpravu a odoberanie záznamov v tabuľke `ambulance_competences`.

Oprávnenia:

* používateľ s rolou `2` môže upravovať iba ambulancie, v ktorých je manažérom,
* používateľ s rolou `3` môže upravovať kompetencie ktorejkoľvek ambulancie.

Backend musí pri každej operácii overiť oprávnenie používateľa voči konkrétnej ambulancii.

---

## 2. Scheduling

Skontrolovať existujúcu implementáciu plánovania a overiť, či sú implementované všetky potrebné endpointy na zobrazovanie, pridávanie, editovanie a deaktivovanie rozvrhových jednotiek.

### 2.1 Úprava endpointu `my-schedule`

Upraviť endpoint `my-schedule` tak, aby nevracal iba rozvrhové jednotky aktuálneho mesiaca.

Endpoint musí podporovať nasledujúce možnosti:

* zobrazenie všetkých rozvrhových jednotiek používateľa,
* zobrazenie rozvrhu pre konkrétny mesiac a rok,
* zobrazenie rozvrhu pre aktuálny mesiac.

Pri filtrovaní podľa mesiaca sa musia používať parametre:

* `month`,
* `year`.

### 2.2 Správa rozvrhu používateľov

Vytvoriť alebo upraviť endpointy tak, aby bolo možné rozvrhové jednotky:

* pridávať,
* editovať,
* deaktivovať,
* zobrazovať pre konkrétny mesiac a rok.

Oprávnenia:

* používateľ s rolou `2` môže spravovať rozvrhy používateľov patriacich do ambulancie, v ktorej je manažérom,
* používateľ s rolou `3` môže spravovať všetky rozvrhy.

### 2.3 Hromadné uloženie mesačného rozvrhu

Hlavný endpoint na uloženie rozvrhu musí prijímať:

* `user_id`,
* `month`,
* `year`,
* zoznam rozvrhových jednotiek, ktoré majú zostať aktívne alebo sa majú uložiť.

Logika endpointu:

1. Backend načíta existujúce rozvrhové jednotky používateľa pre zadaný mesiac a rok.
2. Rozvrhové jednotky nachádzajúce sa v prijatom zozname sa vytvoria alebo aktualizujú.
3. Rozvrhové jednotky, ktoré existujú v databáze, ale nenachádzajú sa v prijatom zozname, sa nastavia ako neaktívne.
4. Záznamy sa nemajú fyzicky odstrániť, pokiaľ projekt používa systém `is_active`.

Endpoint musí fungovať pre manažéra s rolou `2` aj administrátora s rolou `3` podľa ich oprávnení.

### 2.4 Zobrazenie rozvrhov ambulancie

Vytvoriť endpoint pre manažéra, ktorý po zadaní `ambulance_id` zobrazí rozvrhy všetkých používateľov patriacich do danej ambulancie.

Endpoint musí podporovať:

* konkrétny mesiac a rok,
* aktuálny mesiac.

Výsledok musí byť rozdelený podľa používateľov a musí obsahovať minimálne:

* `user_id`,
* meno používateľa,
* rozvrhové jednotky používateľa,
* mesiac a rok zobrazovaného rozvrhu.

Používateľ s rolou `2` môže zobraziť iba ambulanciu, v ktorej je manažérom. Používateľ s rolou `3` môže zobraziť ľubovoľnú ambulanciu.

---

## 3. User a autentifikácia

Opraviť model, ukladanie a aktualizáciu používateľa, pretože autentifikačný token sa aktuálne neukladá správne do tabuľky `users`.

Je potrebné:

1. Skontrolovať model `User` a overiť, či obsahuje správne definovaný stĺpec pre autentifikačný token.
2. Skontrolovať prihlasovaciu logiku a miesto, kde sa autentifikačný token vytvára alebo prijíma.
3. Zabezpečiť, aby sa token pri prihlásení alebo autentifikácii korektne uložil alebo aktualizoval v databáze.
4. Skontrolovať, či sa zmeny správne commitujú do databázy.
5. Overiť, či sa pri ďalšej požiadavke token správne načíta a validuje.
6. Skontrolovať celú autorizačnú logiku.

Osobitne skontrolovať:

* podľa čoho backend identifikuje aktuálne prihláseného používateľa,
* ako sa z tokenu získava `user_id`,
* ako sa načítavajú roly používateľa,
* ako sa kontrolujú roly `2` a `3`,
* či sa roly kontrolujú z aktuálnych údajov v databáze,
* či nie je možné obísť kontrolu oprávnení zmenou vstupných parametrov,
* či neaktívny používateľ alebo neaktívna rola nemôžu vykonávať chránené operácie.

---

## 4. Administrácia ambulancií a používateľov

### 4.1 Manažér ambulancie

Skontrolovať endpointy na vytváranie, zobrazovanie a editovanie ambulancií.

Pri ambulancii musí byť možné:

* zobraziť aktuálneho manažéra alebo manažérov,
* nastaviť manažéra pri vytvorení ambulancie,
* zmeniť manažéra pri editovaní ambulancie,
* odobrať aktuálneho manažéra,
* pridať nového manažéra.

Backend musí overiť, že používateľ nastavovaný ako manažér má požadovanú rolu, prípadne mu musí byť rola priradená podľa existujúcej aplikačnej logiky.

Je potrebné skontrolovať dátový model a určiť, či ambulancia môže mať:

* jedného manažéra,
* alebo viacerých manažérov.

Implementácia endpointov musí rešpektovať aktuálny databázový model.

### 4.2 Endpoint `users-by-role`

Vytvoriť endpoint `users-by-role`, ktorý po zadaní role vráti zoznam všetkých používateľov, ktorí majú danú rolu.

Vstup môže obsahovať:

* `role_id`,
* prípadne `role_code`, ak sa v projekte používa jednoznačný kód role.

Každý používateľ vo výsledku musí obsahovať minimálne:

* `id`,
* `email`,
* `full_name`,
* `is_active`,
* zoznam rolí,
* ambulancie používateľa,
* prípadne ďalšie údaje používané v administračnom rozhraní.

Endpoint musí podporovať iba oprávnených používateľov, minimálne rolu `3`. Ak ho potrebuje aj manažér, rola `2` môže vidieť iba používateľov relevantných pre ambulancie, ktoré spravuje.

---

## Všeobecné požiadavky

Pri každom bode je potrebné:

* používať existujúcu architektúru projektu,
* dodržať existujúce pomenovanie modelov, schém, služieb a routerov,
* doplniť Pydantic schémy pre requesty a response objekty,
* implementovať kontrolu oprávnení na backendovej strane,
* kontrolovať existenciu používateľa, ambulancie, role a kompetencie,
* kontrolovať hodnotu `is_active`,
* používať vhodné HTTP status kódy,
* ošetriť neplatné vstupné údaje,
* zabrániť vytváraniu duplicitných záznamov,
* zachovať spätnú kompatibilitu existujúcich endpointov, pokiaľ to je možné,
* doplniť alebo upraviť testy,
* všetky zmeny podrobne zapísať do `api.md`.
