# Report: komplexné testovanie generátora rozpisov

Dátum: 2. 10. 2026 · Testovaný kód: `main` @ `7800f6e` · Generátor: `backend/app/services/schedule_generation_service.py` (MILP, PuLP + CBC, dva prechody)

---

## 1. Zhrnutie

**Tvrdé pravidlá generátor dodržiava spoľahlivo.** Testy spustili generátor približne 9 000-krát: od 2 ľudí s 1 rolou po 120 ľudí s 8 rolami, s kalendármi vyplnenými neprítomnosťami na 0–90 %, so všetkými nastaveniami pravidiel, so sviatkami, s nadväzujúcimi mesiacmi aj s ručnými zásahmi. **Ani jeden vrátený rozpis neporušil tvrdé pravidlo.** To znamená plné obsadenie, kvalifikáciu, jednu rolu za deň, inú ambulanciu v ten deň, odpočinok, striktné neprítomnosti a striktné mesačné maximum. **Ani raz generátor neodmietol mesiac, ktorý sa dal obsadiť.** Každé jeho „nedá sa“ potvrdil nezávislý model.

**Vyrovnanosť záťaže je optimálna.** Na 2 288 malých mesiacoch, kde sa dá prehľadať každý možný rozpis, sa generátor zhodol s matematickým optimom presne. Na väčších mesiacoch testy nenašli žiadnu výmenu ani presun služby, ktoré by rozpis zlepšili. Rovnocenní ľudia majú počty služieb najviac o 1 rozdielne (148 z 148 kombinácií). Na reálnych dátach (`config_1`, 40 mesačných rozpisov) je rozptyl záťaže ≤ 1 v 34 zo 40 prípadov a ≤ 2 vo všetkých.

**Dogenerovanie rozpisov funguje správne.** Ide o doplnenie čiastočne vyplneného mesiaca, preplánovanie zvyšku mesiaca po zmene a nadviazanie na predchádzajúci mesiac. V 843 takýchto behoch zostala história nedotknutá v 100 % prípadov a všetky ručne vložené služby sa zachovali (100 %), aj tie, ktoré pravidlá porušujú. Medzery sa doplnili platne. Zvyšok mesiaca **vyrovnáva nerovnomernú históriu**: na malých mesiacoch presne optimálne (120/120), na väčších blízko teoretickej hranice. Jedno praktické obmedzenie: ak v histórii mesiaca slúžil človek, ktorý medzitým z pracoviska odišiel, dogenerovanie sa celé odmietne (oddiel 4.5).

**Slabé miesto je druhý prechod, ktorý rieši želania.** Ak má pracovisko služby **rôznej dĺžky** (napr. 4 h, 12 h a 24 h), tento prechod často skončí bez riešenia. Generátor potom vráti vyrovnaný rozpis, ale **želania „chcem“ a „radšej nie“ potichu ignoruje**, hoci by sa dali splniť bez straty vyrovnanosti. Pri zmiešaných dĺžkach a 20 a viac ľuďoch sa to stalo v 54–56 % mesiacov a pri meraní výkonu (40–60 ľudí) vo všetkých. Pri rovnako dlhých službách je to len 0–6 %, preto reálne dáta `config_1` (všetky služby 4 h) dopadli dobre. Na tom istom mieste sa prekračuje aj časový limit: pri limite 120 s trvalo generovanie až 577 s, pri limite 2 s 65–130 s. Pri zmiešaných dĺžkach a dlhom odpočinku sa navyše od ~20 ľudí nestihne do 120 s dokázať ani optimum vyrovnanosti. Rozpis je aj vtedy platný, len nie zaručene optimálny. Ďalšie nálezy sú stredné alebo nízke: nesúlad farieb konfliktov v plánovači s nastavením pravidiel, takmer neoptimalizovaný rozostup služieb, nekonzistentné hraničné vstupy a zastaraná dokumentácia. Prehľad je v oddiele 7.

| Oblasť | Verdikt |
|---|---|
| Tvrdé pravidlá | ✅ 0 porušení v ~9 000 behoch |
| Správnosť „nedá sa“ | ✅ každé odmietnutie potvrdené nezávislým modelom; mesiac, ktorý sa dal obsadiť, nikdy neodmietnutý |
| Vyrovnanosť záťaže (prvý prechod) | ✅ presné optimum (2 288/2 288 brute force) |
| Mesačné maximá | ✅ striktné nikdy prekročené; penalizované prekročené len o minimum (30/30 proti presnému modelu) |
| Dogenerovanie | ✅ história a ručné služby 100 %; vyrovnávanie histórie optimálne až takmer optimálne; ⚠️ odídený zamestnanec blokuje |
| Želania (druhý prechod) | ❌ pri službách rôznej dĺžky a ≥ 20 ľuďoch ignorované vo viac než polovici mesiacov, bez upozornenia |
| Časový limit | ❌ výrazne prekračovaný (druhý prechod) |
| Databáza, API, automatické generovanie | ✅ zhoda s modelom v pamäti, správne sviatky, scenáre, poradie pracovísk |
| Plánovač (frontend) | ⚠️ závažnosť konfliktov ignoruje nastavenia pravidiel pracoviska |

---

## 2. Ako sa testovalo

### 2.1 Nezávislý „oracle“

Rozpis nekontroloval generátor sám. Kontroloval ho samostatne napísaný testovací harness v `backend/tests/scheduling_harness/`, ktorý nepoužíva žiadnu pomocnú funkciu generátora. Pravidlá sú v ňom napísané znova podľa dokumentácie (`schedule_generation_model.md`, README, `constraint_setting_service.py`):

* **`oracle.validate`**: 11 typov porušení (`coverage`, `unqualified`, `double_role`, `other_workplace`, `rest`, `absence`, `soft_decline`, `max_shifts`, `fixed_missing`, `history_changed`, `malformed`).
* **`oracle.first_pass_cost`**: nezávislý výpočet účelovej funkcie prvého prechodu (štyri konvexné rebríky, penalizácie). Na pozorovaných behoch sa zhoduje s hodnotou, ktorú vráti CBC.
* **`oracle.find_improving_moves`**: lokálne hľadanie presunov a výmen služieb, ktoré by rozpis zlepšili.
* **`reference.reference_feasibility`**: druhý, inak formulovaný MILP iba s tvrdými pravidlami. Odpočinok je v ňom zapísaný po dvojiciach a pridané sú klikové rezy. Overuje každé „nedá sa“.
* **`reference.brute_force`**: úplné prehľadanie všetkých rozpisov pre malé mesiace (do 5 ľudí, do 2 rolí, okno 2–7 dní). Dokazuje optimalitu.
* **„Planted“ inštancie**: generátor testovacích dát najprv vytvorí skrytý platný rozpis a až potom pridá neprítomnosti, želania a maximá tak, aby ho nezneplatnili. O takom mesiaci sa vie, že **sa dá** obsadiť.
* **`db_builder`**: zapíše inštanciu do SQLite tak, ako ju ukladá aplikácia: scenáre, 8 slotov dňa, sviatky, iné pracoviská, nastavenia pravidiel. Takto sa testuje aj načítanie z databázy.

Spoľahlivosť harnessu overuje `tests/test_harness_selfcheck.py` (53 testov, 1 218 podtestov). Patria k nim mutačné testy, ktoré do platného rozpisu vložia každý typ porušenia a overia, že ho oracle nájde. Brute force sa porovnáva s naivným prehľadávaním bez orezávania (365/365 zhoda). Generovanie dát je deterministické pri ľubovoľnom `PYTHONHASHSEED`. Harness pred začatím testovania nezávisle preverili traja recenzenti a ich nálezy sa opravili.

### 2.2 Testovacie oblasti

| Súbor | Oblasť | Behov (stress) |
|---|---|---|
| `test_scenarios_hard_fuzz.py` | tvrdé pravidlá, všetky veľkosti a profily dát | 1 484 |
| `test_scenarios_availability_fill.py` | vyplnenosť kalendárov 0–90 %, dovolenky, želania | 926 |
| `test_scenarios_max_shifts_hours.py` | mesačné maximá, hodiny, preferencia druhu služby | 706 |
| `test_scenarios_fill_in.py` | dogenerovanie, preplánovanie, nadväzujúce mesiace | 843 |
| `test_scenarios_policy_matrix.py` | každé pravidlo striktne/penalizovane, váhy 0–100 000 | ~800 |
| `test_scenarios_optimality.py` | brute force, lokálne zlepšenia, spravodlivosť, rozostup | ~3 000 |
| `test_scenarios_edge_cases.py` | hraničné a degenerované vstupy | ~150 |
| `test_scenarios_db_end_to_end.py` | DB, sviatky, scenáre, HTTP API, automatické generovanie | ~400 |
| `test_scenarios_realistic_seed.py` | reálne dáta `config_1` (40 mesiacov) a `config_2` | 48 |
| `test_scenarios_frontend_conflicts.py` | kontrola konfliktov v plánovači proti oracle | 180 rozpisov + 228 mutácií |
| `test_scenarios_determinism_robustness.py` | determinizmus, permutácie, časové limity, extrémne čísla | ~250 |
| `test_scenarios_performance_scaling.py` + samostatné meranie | výkon podľa veľkosti | 44 |

Na každý vrátený rozpis sa uplatnili tieto kontroly:

1. `validate == []`;
2. planted mesiac nesmie byť odmietnutý;
3. každé odmietnutie musí potvrdiť referenčný model;
4. ak prvý prechod nenarazil na časový limit, rozpis nesmie byť horší než skrytý platný rozpis;
5. ak beh nenarazil na limit, nesmie zostať žiadne zlepšujúce presunutie.

Kontroly optimality sa vynechali, keď beh narazil na časový limit, aby výsledok neskreslila záťaž stroja.

---

## 3. Čo generátor dokáže (overené)

Každé tvrdenie je podložené počtom behov zo záťažového režimu (`SCHEDULING_STRESS=1`).

**Tvrdé pravidlá a správnosť**

* Každý vrátený rozpis je platný: **0 porušení** v ~9 000 behoch naprieč všetkými veľkosťami, profilmi a nastaveniami.
* Mesiac, ktorý sa dá obsadiť, **nikdy neodmietne**: tisíce planted mesiacov, 0 odmietnutí, 0 pádov.
* Keď mesiac odmietne, má pravdu: 432 odmietnutí v hard_fuzz a 248 pri úplnom prehľadaní malých mesiacov, **všetky potvrdené** nezávislým modelom, 0 nepotvrdených („unknown“).
* Predbežná kontrola kapacity (`insufficient_daily_capacity`, `insufficient_qualified_staff`, `insufficient_consecutive_day_*`) uvádza správne dni a čísla: **4 351 tvrdení prepočítaných, 0 chybných**.
* Odpočinok funguje pri hodnotách 0 až 6 dní, aj keď sa líši podľa dňa v týždni a sviatku, aj cez hranicu mesiaca (oboma smermi) a aj po službe na inom pracovisku s jeho vlastným kalendárom.
* Kalendár je správny pre 28-, 29-, 30- aj 31-dňové mesiace, prestupný február 2000/2028, neprestupný 2100 a prechod december → január.
* Slovenské sviatky sa staffujú zo slotu „deň pracovného pokoja“ presne v správne dni (všetkých 11 dní pokoja v roku 2026). Pracovné štátne sviatky (1. 9., 15. 9., 28. 10., 17. 11., 8. 5.) sa správne berú ako bežné dni.

**Kvalita rozpisu**

* Vyrovnanosť (prvý prechod) je **presne optimálna**: 2 288/2 288 malých mesiacov s rozdielom 0 oproti úplnému prehľadaniu. Na 118 väčších mesiacoch, ktoré nenarazili na limit, nezostal **ani jeden zlepšujúci presun**.
* Rovnocenní ľudia sa líšia najviac o 1 službu: 148/148 kombinácií (2–20 ľudí, 1–4 role, odpočinok 0–3, služby 4 h a 12 h).
* Neprítomný alebo obmedzený človek nerozhodí ostatných (9/9). Zvyšok tímu zostáva v rozptyle 1.
* Preferencia druhu služby funguje: kto chce príplatkové služby, dostane ich viac (433 proti 221), pričom celkové počty služieb zostanú rovnaké (rozdiel 0).
* Pri penalizovanom maxime s predvolenou váhou 1000 prekročí maximá presne o minimum, ktoré sa nedá obísť (30/30 proti presnému modelu). Ak maximá nestačia na celý mesiac, rozdelí nadbytok rovnomerne.
* Ak sa prvý aj druhý prechod dokážu do konca, sú denné želania na malých mesiacoch optimálne (2 201/2 201).
* Na reálnych dátach `config_1` (57 + 23 + 19 + 35 ľudí, 40 mesiacov) je **82–92 % „chcem“ dní splnených**, 0 „radšej nie“ dní odpracovaných, 0 služieb nad maximum a všetky mesiace sú dokázateľne optimálne.

**Nastavenia pravidiel (Ohraničenia)**

* Striktné pravidlo nebolo porušené v žiadnom z 368 + 140 behov matice pravidiel.
* Váha 0 člen skutočne vypúšťa: 19/19 dvojíc dalo identický výsledok ako vstup bez daného údaja.
* Platí poradie síl: pri váhe 1000 penalizované pravidlo vyhrá nad vyrovnanosťou, pri váhe 0,5–40 ustúpi.
* Želania nikdy nekúpia horšiu vyrovnanosť nad toleranciu zámku (0 z 508 behov). 37 behov skončilo v rámci tolerancie, čo je známa chyba `balance_lock_drift`.
* Služba nastavení pravidiel: 400 náhodných uložení a načítaní bez chyby, 81 neplatných dávok odmietnutých bez zmeny pracoviska.

**Databáza, API, viac pracovísk**

* Načítanie z databázy podáva generátoru presne ten istý problém ako vstup v pamäti: 186 dvojíc, 0 rozdielov v stave, 0 rozdielov v hodnote účelovej funkcie. Platí to aj pri šumových (neaktívnych) riadkoch, scenári bez slotu sviatku či bez scenára a cudzom kalendári.
* Prepnutie zvoleného scenára prepne počty, odpočinok aj hodiny, ktoré generátor číta.
* `POST /ambulances/{id}/schedule/generate`: 200 s platným rozpisom, 409 so štruktúrovanými konfliktmi, 422 pri 7 druhoch zlého vstupu, 404 pri neznámom pracovisku.
* Po uložení a schválení mesiaca generovanie ďalšieho mesiaca načíta posledný týždeň ako susedné služby a rešpektuje ich odpočinok.
* Automatické generovanie zoradí pracoviská správne (urgentné posledné, väčšie skôr): 10/10 behov. Pravidlá naprieč pracoviskami držia: 40 mesiacov, 0 porušení. Na `config_1` je to 4 625 služieb a 35 ľudí na viacerých pracoviskách, 0 porušení.
* Ak jedno pracovisko zlyhá, beh skončí ako `PARTIAL` a ostatné sa uložia konzistentne.

---

## 4. Dogenerovanie rozpisov

Editor (`AmbulanceScheduleEditView.generateSchedule`) pošle generátoru **všetky služby na obrazovke** ako `fixed_entries` a ako `generate_from` prvý upraviteľný deň. Tlačidlo „Vymazať“ vyprázdni zvyšok mesiaca pred úplným pregenerovaním. Generátor preto musí históriu zachovať presne, každú ručnú službu ponechať, doplniť medzery platne a naplánovať zvyšok tak, aby bol vyrovnaný **celý mesiac**.

### 4.1 Doplnenie čiastočne vyplneného mesiaca

| Scenár | Behov | Platné | História zachovaná | Ručné služby zachované | Optimalita (kde overená) |
|---|---|---|---|---|---|
| 10 % vopred vyplnené (malé / stredné / veľké) | 14 | 100 % | 100 % | 100 % | 100 % |
| 30 % | 14 | 100 % | 100 % | 100 % | 100 % |
| 50 % | 14 | 100 % | 100 % | 100 % | 100 % |
| 70 % | 14 | 100 % | 100 % | 100 % | 100 % |
| 90 % | 14 | 100 % | 100 % | 100 % | 100 % |
| „Diery“ vyrazené do hotového rozpisu | 72 | 100 % | 100 % | 100 % | 100 % (72/72) |
| Celý mesiac zafixovaný | 80 | 100 % | 100 % | 100 % | vrátený **identicky** (80/80) |

### 4.2 Preplánovanie zvyšku mesiaca po zmene

Hotový rozpis sa zafixoval ako história do dňa *X*. Potom sa urobila jedna zmena a zvyšok mesiaca sa pregeneroval. Každá zmena sa skúšala skoro, v polovici a neskoro v mesiaci, po 15 mesiacov.

| Zmena | Behov | Vyriešené | Odmietnuté (všetky potvrdené ako naozaj nemožné) | Zmena rešpektovaná | História / ručné služby |
|---|---|---|---|---|---|
| bez zmeny | 45 | 45 | 0 | 45/45 | 100 % / 100 % |
| nová neprítomnosť | 45 | 42 | 3 | 42/42 | 100 % / 100 % |
| dovolenka 3–7 dní | 45 | 39 | 6 | 39/39 | 100 % / 100 % |
| znížené maximum najvyťaženejšieho | 45 | 34 | 11 | 34/34 | 100 % / 100 % |
| odchod najvyťaženejšieho do konca mesiaca | 45 | 22 | 23 | 22/22 | 100 % / 100 % |
| vyšší počet v jednom slote | 45 | 27 | 18 | 27/27 | 100 % / 100 % |

Každé odmietnutie overil nezávislý model ako skutočne neriešiteľné. Typický prípad je odchod človeka, bez ktorého pri striktných pravidlách nemá kto slúžiť. Keď harness našiel náhradný platný rozpis, generátor mesiac nikdy neodmietol.

### 4.3 Vyrovnávanie nerovnomernej histórie

Toto je otázka, či zvyšok mesiaca dorovná ľudí, ktorí už majú v histórii veľa (alebo málo) služieb. Merali sme rozptyl záťaže **za celý mesiac** (max − min služieb).

| Veľkosť | n | Rozptyl histórie | **Generátor** | Optimum (brute force) | Dolná hranica* | Keby sa zvyšok plánoval naslepo** | Generátor lepší než naslepo |
|---|---|---|---|---|---|---|---|
| malé (3–5 ľudí) | 120 | 7,22 | **4,95** | 4,95 (zhoda 120/120) | 3,77 | 7,49 | 107/120 |
| menšie (4–10) | 26 | 3,46 | **1,85** | – | 0,92 | 4,12 | 21/26 |
| stredné (10–25) | 20 | 3,05 | **1,15** | – | 0,95 | 3,60 | 18/20 |

\* Hranica, ktorá ignoruje kvalifikácie aj odpočinok, takže sa nemusí dať dosiahnuť.
\** Zvyšok mesiaca vyrovnaný sám osebe, bez ohľadu na históriu.

Generátor teda históriu **aktívne dorovnáva**. Na malých mesiacoch presne optimálne, na väčších blízko teoretickej hranice, a výrazne lepšie, než keby zvyšok plánoval bez ohľadu na históriu.

### 4.4 Ďalšie scenáre dogenerovania

| Scenár | Behov | Výsledok |
|---|---|---|
| Ručné služby, ktoré porušujú pravidlá (dve roly v deň, v odpočinku, bez kvalifikácie, v neprítomnosti, nad počet) | 94 | 100 % zachované; generátor okolo nich plánuje bez nových porušení |
| Nadväzujúce mesiace dec 2027 → jan 2028 → feb 2028 (prestupný), dlhý odpočinok | 48 | 100 % platné, odpočinok cez hranicu mesiaca dodržaný |
| Cesta cez databázu (`generate_ambulance_monthly_schedule` s `fixed_entries` + `generate_from`) | 22 | verdikt zhodný s výpočtom v pamäti 22/22 |
| API: služby alebo `generate_from` mimo mesiaca | – | správne 422 |
| Služby mimo mesiaca priamo vo vstupe generátora | – | potichu vynechané, rozpis platný |

### 4.5 Obmedzenia dogenerovania

1. **Odídený zamestnanec blokuje dogenerovanie** (stredná závažnosť). Ak človek odslúžil prvú polovicu mesiaca a potom mu deaktivovali členstvo, jeho služby sú stále na obrazovke. Editor ich pošle ako `fixed_entries` a generátor odmietne **celý mesiac** s `fixed_assignment_unknown`. Je to zdokumentované v `_detect_fixed_assignment_conflicts`, no prakticky to znamená, že zvyšok mesiaca sa dá pregenerovať len po zmazaní už odslúžených služieb. Test: `test_scenarios_fill_in.py::DepartedEmployeeTests`.
2. **Želania sa pri dogenerovaní ignorujú rovnako často ako pri plnom generovaní** (oddiel 7, chyba č. 1). V tabuľkách vyššie sa to vyskytlo v 21 behoch (zvyčajne stredné mesiace). Vyrovnanosť a pravidlá to neovplyvňuje.

---

## 5. Výsledky podľa oblastí

### 5.1 Tvrdé pravidlá naprieč profilmi dát (hard_fuzz)

| Veľkosť | Behov | Vyriešené | Odmietnuté (potvrdené) | Neplatné rozpisy | Narazilo na limit | Prechod pre želania bez riešenia | Medián s | Max s |
|---|---|---|---|---|---|---|---|---|
| tiny (3–5 ľudí) | 224 | 208 | 16 (16) | 0 | 0 | 0 | 0,28 | 1,9 |
| small (4–10) | 570 | 439 | 131 (131) | 0 | 38 | 22 | 0,34 | 12,5 |
| medium (10–25) | 150 | 123 | 27 (27) | 0 | 33 | 20 | 1,44 | 38,5 |
| large (25–60) | 76 | 66 | 10 (10) | 0 | 30 | 18 | 6,24 | 69,2 |
| xl (60–80) | 14 | 13 | 1 (1) | 0 | 11 | 7 | 30,75 | 272,7 |
| stress (ručné porušenia, tesné maximá) | 144 | 96 | 48 (48) | 0 | 5 | 1 | 0,31 | 15,7 |
| hraničná kapacita | 298 | 103 | 195 (195) | 0 | 21 | 15 | 0,01 | 38,6 |

Polovica behov v každej veľkosti boli planted mesiace (dajú sa obsadiť) a polovica náhodné. Pokryté profily, každý zvlášť: odpočinok 0 / 1 / 0–3 / 2–6, dĺžky služieb 4 h / 12 h / mix 4–24 h / zlomkové, dopyt rovnomerný / podľa dňa / riedky s nulovými dňami / ťažký / zmiešaný, sviatky žiadne / slovenské / náhodné / zmiešané, kvalifikácie náhodné / hierarchia / vzácna rola, ľudia bez kvalifikácie, roly s nulovým dopytom, služby na inom pracovisku (s vlastným aj predvoleným odpočinkom), susedné služby a vyradená rola. **Žiadny profil nemal ani jeden neplatný rozpis ani jedno nepotvrdené odmietnutie.**

### 5.2 Vyplnenosť kalendárov

Pri náhodných (nie planted) mesiacoch so striktnými neprítomnosťami ukazuje tabuľka, koľko sa ich ešte dá obsadiť. Každé odmietnutie potvrdil referenčný model.

| Podiel dní „nemôžem“ | 0 % | 10 % | 20 % | 30 % | 45 % | 60 % | 75 % | 90 % |
|---|---|---|---|---|---|---|---|---|
| malé (4–10 ľudí), obsaditeľné | 94 % | 89 % | 83 % | 78 % | 28 % | 22 % | 0 % | 0 % |
| stredné (10–25), obsaditeľné | 100 % | 100 % | 100 % | 100 % | 80 % | 40 % | 40 % | 0 % |
| penalizované neprítomnosti (malé), vyriešené | 100 % | 93 % | 93 % | 100 % | 86 % | 79 % | 86 % | 86 % |

* Planted mesiace boli vyriešené **vždy**: 171/171 pri každej vyplnenosti 0–90 % a 15/15 pri „sviatočnom zhluku“, keď si všetci berú voľno v tých istých dňoch.
* Pri penalizovaných neprítomnostiach generátor pracuje v deň neprítomnosti len vtedy, keď inak mesiac obsadiť nejde. Pri vyplnenosti 0–30 % to bolo 1–4 takých služieb spolu na 14 mesiacov, pri 75–90 % 210–274. Na planted mesiacoch, ktoré sa dali obsadiť bez porušenia, to bolo 0 (92 + 92 behov).
* Na planted mesiacoch sa splnilo **14–66 % „chcem“ dní** a odpracovalo 1–34 % „radšej nie“ dní. Zvyšok sa obvykle nedá splniť bez zhoršenia vyrovnanosti alebo porušenia pravidiel. Viditeľná časť strát je však spôsobená chybou č. 1: v strednej veľkosti pri 10 % a 75 % vyplnenosti skončilo 5 zo 6 behov bez riešenia prechodu pre želania.
* Monotónnosť: pridanie neprítomností nikdy nezlepšilo optimum a neprítomnosti v dňoch mimo rozpisu ho nezmenili (35 základných mesiacov, 64 variantov).

### 5.3 Mesačné maximá a hodiny

| Skupina | Behov | Výsledok |
|---|---|---|
| Striktné maximum, všetky režimy (žiadne, 0, voľné, tesné, pod záťažou, heterogénne, hladné, zmiešané) | 315 | 242 vyriešených, 73 odmietnutých (všetky potvrdené), **0 prekročení** |
| Striktné maximum pod počtom ručných služieb | 22 | ručné služby ponechané, ďalšie nepridané |
| Maximum 0 / žiadne = bez limitu | 75 | správne |
| Penalizované maximum, váha 1000 / 100 000 | 60 | prekročenie = presné minimum v 60/60 (súčet 255 = 255) |
| Penalizované maximum, váha 0,5 / 10 | 60 | prekročenie väčšie (339 / 336), čo je zámer: lacnejšie než zhoršiť vyrovnanosť |
| „Hladný“ mesiac (súčet maxím < dopyt), symetrický | 12 | nadbytok rozdelený rovnomerne (rozptyl ≤ 1) |
| Dvojčatá: rovnaká dostupnosť, jeden chce príplatkové a druhý bežné služby | 46 | príplatkové 433 : 221, rozdiel v celkovom počte služieb 0 |
| Hodiny, malé mesiace s mixom dĺžok (brute force) | 78 | prvý prechod optimálny, rozdiel 0 |

**Hodiny nie sú vždy vyrovnané.** Pri zmiešaných dĺžkach služieb vychádza rozpis vyrovnaný v počtoch, ale nie vždy v hodinách. V nájdenom prípade bol rozptyl 10,25 h, hoci existuje rovnako vyrovnaný rozpis s 1,25 h. Rebríky druhu služby (príplatková/bežná) prevážia hodinový rebrík. Dokumentácia (3.2) sľubuje vyrovnanosť „v oboch“. Je to nesúlad s dokumentáciou nízkej závažnosti.

### 5.4 Nastavenia pravidiel (Ohraničenia)

V stresovom režime prešlo maticou pravidiel 368 behov: 7 prepínateľných pravidiel striktne aj penalizovane pri váhach 0 / 0,5 / predvolená / 1000 / 100 000 a 3 pravidlá, ktoré sa dajú len penalizovať. K tomu prišlo 10 predvolieb × 6, 80 náhodných politík a 36 „súbojov“ pravidiel.

* Striktné pravidlo **nikdy** nebolo porušené.
* Poradie síl zodpovedá dokumentácii. Napríklad pri súboji neprítomnosť proti vyrovnanosti klesne počet porušení z 10 (váha 0) cez 5 (váha 40) na 0 (váha 1000).
* Chybové hlásenie pri `constraint_conflict` uvádza sprísnené pravidlá správne (33/33). Pri zlyhaní predbežnej kontroly kapacity ich **neuvádza**: 56 zo 72 prípadov, známa chyba `capacity_error_without_tightened_rules`.

### 5.5 Optimalita a spravodlivosť

| Kontrola | Výsledok |
|---|---|
| Brute force, malé mesiace (2 579 inštancií) | prvý prechod v optime 2 288/2 288 (rozdiel 0), želania v optime 2 201/2 201, odmietnutia 248/248 správne |
| Lokálne zlepšenia, 130 menších a stredných mesiacov | 0 zlepšení vyrovnanosti; všetky nájdené zlepšenia želaní pochádzali z behov, kde prechod pre želania skončil bez riešenia |
| Generátor proti skrytému platnému rozpisu | nikdy horší; v 75–87 % prípadov striktne lepší |
| Symetrická spravodlivosť | 148/148 v rozptyle ≤ 1 |
| Rozostup služieb (medzery medzi službami) | ⚠️ prakticky sa neoptimalizuje: 32–41 % služieb leží na najtesnejšej povolenej medzere a v 21 z 24 mesiacov existuje rovnako vyrovnaná výmena, ktorá medzeru rozšíri. Príčina: tolerancia druhého prechodu (1,0) je väčšia než celý člen rozostupu (~0,35). |

### 5.6 Hraničné prípady

Z 36 hraničných prípadov sa 33 správa správne a zdokumentovane. Patria k nim: žiadni ľudia alebo roly, nulový dopyt, jeden človek, odpočinok 6 dní v 36 mesiacoch, všetky dĺžky mesiacov, `generate_from` v prvý, posledný aj stredný deň, služby mimo mesiaca, duplicitné služby, neznámi ľudia alebo roly, neplatné argumenty, služby 0 h a 24 h, striktné maximum 1, extrémne váhy a služba každý deň na inom pracovisku.

Výnimky (tri chyby a jedna kozmetická vec):

* duplicitné ID zamestnanca spôsobí `PulpError` (cez databázu sa to stať nedá, členstvo má zložený primárny kľúč);
* `weekday_recovery_days`, `weekday_shift_hours` a `weekday_is_surcharge` nesprávnej dĺžky spôsobia `IndexError` namiesto `ValueError` (cez databázu nedosiahnuteľné);
* časový limit 1 s na najväčšom mesiaci trvá 3,5–7,4 s;
* `time_limit_seconds` v hlásení `solver_timeout` sa zaokrúhľuje na celé sekundy, takže pri limite pod 1 s ukazuje 0 (kozmetické).

### 5.7 Databáza, API, automatické generovanie

Detaily sú v oddiele 3. Okrem toho sa našli dve drobnosti:

* Ak scenáru chýba slot „deň pokoja“, editor ukazuje sviatok ako príplatkový, ale generátor ho vyvažuje ako bežný (berie nedeľu). Počty, odpočinok aj hodiny sa zhodujú, líši sa len príznak príplatku.
* `automatic_schedule_generation_service._monthly_demand` pri zoraďovaní pracovísk ignoruje slot sviatku, takže poradie môže byť iné, než by zodpovedalo skutočnému dopytu.

### 5.8 Reálne dáta (`config_1`)

| Oddelenie | Mesiace | Ľudia | Služby/mesiac | Rozptyl (max) | Rozptyl hodín (max) | „Chcem“ splnené | „Radšej nie“ odpracované | Nad max | Riešenie (priemer/max) |
|---|---|---|---|---|---|---|---|---|---|
| I.KAIM | 10 | 57 | 120–279 | 1 | 4 h | 1 353/1 655 (82 %) | 0 | 0 | 5,1 / 17,4 s |
| II.KAIM | 10 | 23 | 112–124 | 1 | 4 h | 595/662 (90 %) | 0 | 0 | 3,0 / 5,4 s |
| KDAIM | 10 | 19 | 84–93 | 2 | 8 h | 445/547 (81 %) | 0 | 0 | 1,4 / 2,5 s |
| KUM (urgentné) | 10 | 35 | 56–62 | 1 | 4 h | 72/78 (92 %) | 0 | 0 | 0,5 / 0,6 s |

* Všetkých 40 mesiacov je platných a oba prechody sú v každom dokázateľne optimálne. Nezostal žiadny zlepšujúci presun a opakované riešenie dáva identickú hodnotu účelovej funkcie (8/8).
* Seed `config_1` trvá 102–116 s.
* KDAIM má rozptyl 2 v 6 mesiacoch, pretože 93 služieb sa nedá rozdeliť medzi 19 ľudí rovnomernejšie pri ich dostupnosti.
* Ručne písané služby v `config_2` (`base.SCHEDULES`) porušujú členstvo (32 zo 44), kvalifikáciu (44 zo 44) a odpočinok (4). Nie je to chyba generátora, ale kvality testovacích dát.

### 5.9 Kontrola konfliktov v plánovači

`frontend/src/utils/scheduleConflicts.js` sa testoval proti oracle na 180 platných rozpisoch a 228 vložených porušeniach.

* Každé vložené porušenie označí na správnej bunke (228/228).
* Na platných rozpisoch neukáže žiadnu nevysvetlenú chybu.
* **Závažnosť konfliktov však nečíta nastavenia pravidiel pracoviska.** Penalizovanú neprítomnosť alebo penalizovaný odpočinok, ktoré generátor legálne použil, kreslí ako **chybu** (v stresovom teste 41 a 956 prípadov). Naopak porušenie *striktného* nadpočtu, maxima alebo „radšej nie“ ukazuje len ako **varovanie** (70 prípadov).

### 5.10 Determinizmus a časový limit

| Kontrola | Výsledok |
|---|---|
| Rovnaký vstup dvakrát / v 3 interpretroch s rôznym `PYTHONHASHSEED` | 24/24 a 24/24 identických rozpisov (ak žiadny prechod nenarazil na limit) |
| Iné poradie ľudí alebo rolí, prečíslovanie ID | 42/42 rovnaká hodnota účelovej funkcie |
| Extrémne váhy (všetky 100 000), zlomkové hodiny, veľa penalizovaných porušení | 24 behov, všetky vrátené rozpisy platné, 0 zlepšujúcich presunov |
| Vstupy generátora sa nemenia, databáza sa nezapisuje | ✅ |
| Rovnaký vstup pri vyčerpanom limite | ⚠️ rozpis sa môže líšiť (hodnota účelovej funkcie rovnaká); dokumentácia sľubuje deterministický výstup |
| Časový limit 1 / 2 / 5 / 15 / 60 s, stredné a veľké mesiace | prekročenie ≤ 1,3 s |
| Časový limit 1 / 2 / 5 / 15 / 60 s, xl (80 ľudí) | ❌ prekročenie o 6 / 123 / 203 / 193 / 149 s (max) |

---

## 6. Výkon a veľkosti dát

Meranie prebehlo na voľnom stroji: 32 jadier, 8 súbežných riešení, CBC jednovláknové. Riešili sa planted mesiace (október 2026) so slovenskými sviatkami, zmiešaným dopytom, 10 % neprítomností, dovolenkami a želaniami. Spolu 44 behov. „1. prechod dokázaný“ znamená, že CBC dokázal optimum vyrovnanosti do limitu. Inak vráti najlepší nájdený rozpis, ktorý bol aj v týchto prípadoch vždy platný a nikdy horší než skrytý platný rozpis.

| Ľudia × roly | Odpočinok | Dĺžky služieb | Limit | Behov | Služieb za mesiac | Stavba modelu (s) | 1. prechod dokázaný | …za (s) | 2. prechod našiel riešenie | Celkový čas (s) | Platné |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 × 1 | 1 deň | mix 4–24 h | 120 s | 2 | 28–62 | 0,0 | 2/2 | 0 | 2/2 | 1 | 2/2 |
| 5 × 1 | 2–6 dní | mix 4–24 h | 120 s | 2 | 14–31 | 0,0 | 2/2 | 1–2 | 2/2 | 1–20 | 2/2 |
| 10 × 2 | 1 deň | mix 4–24 h | 120 s | 2 | 112–127 | 0,1 | 1/2 | 2 | 1/2 | 25–121 | 2/2 |
| 10 × 2 | 2–6 dní | mix 4–24 h | 120 s | 2 | 53–58 | 0,1 | 2/2 | 4–8 | 2/2 | 11–120 | 2/2 |
| 20 × 2 | 1 deň | mix 4–24 h | 120 s | 2 | 35–204 | 0,1 | 2/2 | 0–2 | 1/2 | 0–118 | 2/2 |
| 20 × 2 | 2–6 dní | mix 4–24 h | 120 s | 2 | 14–49 | 0,0 | 2/2 | 0–1 | 2/2 | 0–5 | 2/2 |
| 20 × 4 | 1 deň | mix 4–24 h | 120 s | 2 | 230–234 | 0,2 | 2/2 | 2–5 | 0/2 | 117–118 | 2/2 |
| 20 × 4 | 2–6 dní | mix 4–24 h | 120 s | 2 | 120–124 | 0,2 | 0/2 | – | 0/2 | 122–123 | 2/2 |
| 40 × 4 | 1 deň | mix 4–24 h | 120 s | 2 | 433–483 | 0,4 | 2/2 | 32–34 | 0/2 | 114–174 | 2/2 |
| 40 × 4 | 2–6 dní | mix 4–24 h | 120 s | 2 | 205–213 | 0,6 | 0/2 | – | 0/2 | 127–132 | 2/2 |
| 57 × 7 | 1 deň | mix 4–24 h | 120 s | 2 | 547–565 | 1,4 | 2/2 | 19–49 | 0/2 | 130–152 | 2/2 |
| 57 × 7 | 2–6 dní | mix 4–24 h | 120 s | 2 | 139–205 | 0,9 | 0/2 | – | 0/2 | 123–124 | 2/2 |
| 60 × 6 | 1 deň | mix 4–24 h | 120 s | 2 | 604–639 | 0,6 | 1/2 | 15 | 0/2 | 239–399 | 2/2 |
| 60 × 6 | 2–6 dní | mix 4–24 h | 120 s | 2 | 175–249 | 0,7 | 0/2 | – | 0/2 | 123–132 | 2/2 |
| 80 × 8 | 1 deň | mix 4–24 h | 120 s | 1 | 780 | 0,6 | 1/1 | 68 | 0/1 | 329 | 1/1 |
| 80 × 8 | 2–6 dní | mix 4–24 h | 120 s | 1 | 381 | 0,6 | 0/1 | – | 0/1 | 131 | 1/1 |
| 100 × 8 | 1 deň | mix 4–24 h | 120 s | 1 | 857 | 0,7 | 1/1 | 46 | 0/1 | 207 | 1/1 |
| 100 × 8 | 2–6 dní | mix 4–24 h | 120 s | 1 | 434 | 0,7 | 0/1 | – | 0/1 | 131 | 1/1 |
| 120 × 8 | 1 deň | mix 4–24 h | 120 s | 1 | 1233 | 0,9 | 0/1 | – | 0/1 | 577 | 1/1 |
| 120 × 8 | 2–6 dní | mix 4–24 h | 120 s | 1 | 459 | 0,8 | 0/1 | – | 0/1 | 132 | 1/1 |
| 40 × 4 (vyťaženie 50 %) | 1 deň | mix 4–24 h | 120 s | 1 | 202 | 0,2 | 0/1 | – | 0/1 | 124 | 1/1 |
| 40 × 4 (vyťaženie 50 %) | 2–6 dní | mix 4–24 h | 120 s | 1 | 77 | 0,1 | 0/1 | – | 0/1 | 122 | 1/1 |
| 40 × 4 (vyťaženie 95 %) | 1 deň | mix 4–24 h | 120 s | 1 | 381 | 0,6 | 1/1 | 5 | 0/1 | 110 | 1/1 |
| 40 × 4 (vyťaženie 95 %) | 2–6 dní | mix 4–24 h | 120 s | 1 | 164 | 0,5 | 0/1 | – | 0/1 | 122 | 1/1 |
| 20 × 4 | 1 deň | mix 4–24 h | 30 s | 1 | 234 | 0,2 | 1/1 | 5 | 0/1 | 27 | 1/1 |
| 57 × 7 | 1 deň | mix 4–24 h | 30 s | 1 | 565 | 0,9 | 0/1 | – | 0/1 | 105 | 1/1 |
| 100 × 8 | 1 deň | mix 4–24 h | 30 s | 1 | 857 | 1,8 | 0/1 | – | 0/1 | 170 | 1/1 |
| 20 × 4 | 1 deň | všetky 4 h | 120 s | 1 | 202 | 0,1 | 1/1 | 0 | 1/1 | 38 | 1/1 |
| 57 × 7 | 1 deň | všetky 4 h | 120 s | 1 | 567 | 0,5 | 1/1 | 2 | 1/1 | 106 | 1/1 |
| 100 × 8 | 1 deň | všetky 4 h | 120 s | 1 | 800 | 0,9 | 1/1 | 2 | 1/1 | 97 | 1/1 |

**Čo z merania vyplýva**

1. **Stavba modelu je zanedbateľná**, najviac 1,8 s aj pri 120 ľuďoch a 1 233 službách za mesiac. Čas zaberá výhradne CBC.
2. **Rýchlosť určuje dĺžka služieb viac než veľkosť pracoviska.**
   * Keď sú všetky služby rovnako dlhé, je vyrovnanosť dokázaná za 0–2 s aj pri 100 ľuďoch a 8 rolách a prechod pre želania nájde riešenie.
   * Pri mixe 4–24 h trvá dôkaz 15–68 s (odpočinok 1 deň). Pri odpočinku 2–6 dní sa od 20 ľudí a 4 rolí nedokáže do 120 s ani raz.
   * Príčina je pravdepodobne hodinový rebrík: krokuje sa priemernou dĺžkou služby, takže koeficienty aj optimum sú neceločíselné.
3. **Prechod pre želania pri mixe dĺžok od 20 × 4 nenašiel riešenie ani raz (0 z 29 behov).** Pri dĺžkach 4 h ho našiel vo všetkých 3 behoch. Je to tá istá chyba č. 1 z oddielu 7.
4. **Časový limit sa prekračuje mnohonásobne.**
   * Pri limite 120 s trvalo generovanie až 577 s (120 ľudí) a 207–399 s (60–100 ľudí).
   * Pri limite 30 s trvalo 105–170 s (57–100 ľudí).
   * Editor posiela predvolene 60 s (na výber je 5 s – 30 min), takže manažér čaká niekoľkonásobne dlhšie, než si nastavil. Časť prekročenia ide na vrub chyby č. 1 a zvyšok na chybu č. 2.
5. **Reálne dáta sú rýchle.** Všetkých 40 mesiacov `config_1` (služby 4 h, odpočinok 1 deň, do 57 ľudí × 7 rolí) sa dokázalo optimálne v oboch prechodoch, najdlhšie za 17,4 s.

**Odporúčanie.** Pri bežných veľkostiach rieši prvý prechod (vyrovnanosť) mesiac v sekundách až desiatkach sekúnd. Úzkym hrdlom je prechod pre želania. Oprava chyby č. 1 by celkový čas priblížila času prvého prechodu a odstránila by väčšinu prekročení limitu.

---

## 7. Nájdené chyby

Stav: **potvrdené** = reprodukované opakovane a v rozpore s dokumentovaným správaním; **obmedzenie** = zdokumentované alebo zámerné, no s dopadom na prax. Ku každej chybe existuje test s `@unittest.expectedFailure`. Keď chybu niekto opraví, test hlási „unexpected success“ a dekorátor treba odstrániť.

### 7.1 Nové nálezy

| # | Závažnosť | Stav | Popis | Dosah v praxi | Navrhovaná oprava | Test |
|---|---|---|---|---|---|---|
| 1 | **vysoká** | potvrdené (5 oblastí + ručná reprodukcia) | **Prechod pre želania často skončí bez riešenia** (CBC `sol_status 0`) a generátor vráti rozpis z prvého prechodu. Denné želania („chcem“, „radšej nie“) sú tak ignorované, hoci existujú výmeny, ktoré vyrovnanosť nezmenia a želanie splnia. Príklad: 18 ľudí, 4 roly, prvý prechod dokázaný za 1 s, druhý ani za 60 s nenájde riešenie; zostalo 16 výmien, každá za +10. Pri 20 ľuďoch a 4 rolách nenašiel riešenie ani za 115 s. | Závisí od dĺžky služieb (hard_fuzz, vyriešené mesiace):<br>• rovnaká dĺžka (4 h alebo 12 h): 0–1 % pri < 20 ľuďoch, 3–6 % pri ≥ 20<br>• zmiešané alebo zlomkové dĺžky: 8–9 % pri < 20 ľuďoch, **54–56 % pri ≥ 20**<br>Pri meraní výkonu so zmiešanými dĺžkami nastalo vo všetkých behoch so 40–60 ľuďmi, hoci prechod bežal 79–223 s. Manažér nedostane žiadne upozornenie. | (a) V druhom prechode nezamykať súčet vyrovnanosti jednou hustou podmienkou, ale zafixovať záťaž každého človeka (počet, príplatkové, bežné, hodiny) na hodnotách z prvého prechodu. Je to prísnejšie, no pre CBC oveľa ľahšie a vyrovnanosť sa nezmení. (b) Dať druhému prechodu rozpis z prvého ako štartovacie riešenie (`warmStart=True`); samotné to pomôže len čiastočne. (c) Ako poistku doplniť lokálne vylepšovanie výmenami, ktoré vyrovnanosť nemenia (rádovo milisekundy). (d) Aspoň vrátiť príznak, že želania neboli spracované. | `test_scenarios_fill_in.py::WishPassFindsNothingTests`, `test_scenarios_optimality.py::…test_wish_pass_finds_a_roster_on_a_small_month`, `test_scenarios_availability_fill.py::WishPassStallTests` |
| 2 | **stredná** | potvrdené | **Časový limit sa nedodrží.** Druhý prechod dostane vždy aspoň 1 s. CBC navyše svoj `timeLimit` nekontroluje počas presolve a koreňovej LP relaxácie a do limitu sa nezapočítava ani stavba modelu. Pri limite 5 s trval stredný mesiac 39–47 s, pri limite 2 s xl mesiac 65–130 s a pri limite 120 s mesiac so 120 ľuďmi 577 s (oddiel 6). | Nastavenie „časový rozpočet“ v editore nezaručuje, ako dlho manažér čaká. HTTP požiadavka môže vypršať a slot `SCHEDULE_GENERATION_MAX_CONCURRENCY=1` je celý čas obsadený. | Merať zvyšný čas vrátane stavby modelu; druhý prechod vynechať, keď nezostáva čas; CBC spúšťať s `timeMode elapsed` a prípadne ho tvrdo ukončiť po limite (ponechá sa výsledok prvého prechodu). Oprava chyby č. 1 problém výrazne zmenší. | `test_scenarios_determinism_robustness.py::…test_wall_time_stays_near_the_budget`, `test_scenarios_edge_cases.py::…test_one_second_budget_ends_about_on_time` |
| 3 | stredná | obmedzenie | **Odídený zamestnanec v histórii blokuje dogenerovanie** (oddiel 4.5). | Pri odchode človeka v priebehu mesiaca sa zvyšok mesiaca nedá pregenerovať bez zmazania odslúžených služieb. | Ručné služby ľudí, ktorí už nie sú členmi, brať ako zmrazené záväzky: ponechať ich vo výstupe, započítať do pokrytia a nevyžadovať pre ne kvalifikáciu ani členstvo. | `test_scenarios_fill_in.py::DepartedEmployeeTests` (ukotvuje súčasné správanie) |
| 4 | stredná | potvrdené | **Plánovač farbí konflikty bez ohľadu na nastavenia pravidiel.** `CONFLICT_SEVERITY` je natvrdo: neprítomnosť a odpočinok sú vždy chyba, nadpočet, maximum a „radšej nie“ vždy varovanie. | Pracovisko, ktoré dovolilo penalizovanú neprítomnosť alebo odpočinok, vidí vo vygenerovanom (legálnom) rozpise červené chyby. Naopak porušenie striktného maxima vyzerá ako drobnosť. | `analyzeScheduleConflicts` má dostať nastavenia (`GET /constraints`) a závažnosť odvodiť z nich: striktné = chyba, penalizované = varovanie. | `test_scenarios_frontend_conflicts.py` (2 testy) |
| 5 | nízka | potvrdené | **Rozostup služieb sa prakticky neoptimalizuje.** Absolútna tolerancia druhého prechodu `gapAbs = min(váha rozostupu, 0,1 × váha želania) = 1,0` je väčšia než celý člen rozostupu (typicky 0,3–0,4), takže CBC môže skončiť s ľubovoľným rozostupom. Dokumentácia (3.6) tvrdí, že tolerancia púšťa „nanajvýš zlomok rozptylu jedného zamestnanca“. | Služby jedného človeka bývajú zbytočne nahusto (32–41 % na najtesnejšej povolenej medzere), aj keď sa dajú bez straty rozložiť. | Toleranciu odvodiť od skutočnej veľkosti člena (napr. 0,1 × najmenšia jednotka rozostupu) alebo použiť relatívnu medzeru. | `test_scenarios_optimality.py::…test_two_people_without_rest_alternate` |
| 6 | nízka | potvrdené | Pri zmiešaných dĺžkach služieb nie sú vždy vyrovnané hodiny (oddiel 5.3), hoci dokumentácia 3.2 to sľubuje. | Ľudia s rovnakým počtom služieb môžu mať rozdiel viac než jednu priemernú službu v hodinách. | Upraviť dokumentáciu, alebo zvážiť váhu hodinového rebríka proti rebríkom druhu služby. | `test_scenarios_max_shifts_hours.py::…test_hours_balanced_where_counts_are` |
| 7 | nízka | potvrdené | Pri vyčerpanom časovom limite nie je výstup deterministický; docstring `solve_monthly_schedule` sľubuje deterministický výstup. | Dvakrát „Generovať“ na nezmenenom mesiaci môže dať rôzne návrhy s rovnakou kvalitou. | Upraviť dokumentáciu (determinizmus platí, len keď oba prechody dobehnú). | `test_scenarios_determinism_robustness.py::…test_same_input_same_roster_even_at_the_budget` |
| 8 | nízka | potvrdené | Duplicitné ID zamestnanca vo vstupe spôsobí `PulpError` („overlapping constraint names“) namiesto čistej chyby. Iné 7-prvkové n-tice (`weekday_recovery_days`, `weekday_shift_hours`, `weekday_is_surcharge`) sa nekontrolujú na dĺžku a skončia `IndexError`. | Cez databázu a API nedosiahnuteľné (zložený primárny kľúč členstva, loader vždy skladá 7 hodnôt). Týka sa len priameho volania. | Validovať vstup na začiatku `solve_monthly_schedule`. | `test_scenarios_edge_cases.py` (2 testy) |
| 9 | nízka | potvrdené | Chýbajúci slot „deň pokoja“ v scenári: editor ukazuje sviatok ako príplatkový, generátor ako bežný (podľa nedele). | Len pri starých dátach bez slotu 7. | Zjednotiť záložnú hodnotu príznaku príplatku v `_slot_value` a `competence_service.weekly_parameters`. | `test_scenarios_db_end_to_end.py::…test_holiday_surcharge_matches_what_the_editor_shows` |
| 10 | nízka | potvrdené | `_monthly_demand` v automatickom generovaní ignoruje slot sviatku. | Mení sa len poradie pracovísk pri automatickom behu. | Čítať dopyt cez rovnakú logiku slotov ako generátor. | `test_scenarios_db_end_to_end.py::…test_holiday_demand_counts_towards_the_size` |
| 11 | nízka | potvrdené | Ručne písané služby v seede `config_2` porušujú členstvo, kvalifikáciu a odpočinok. | Len testovacie a demo dáta. | Opraviť `base.SCHEDULES` alebo doplniť kvalifikácie do `config_2`. | `test_scenarios_realistic_seed.py::…test_config_2_duties_are_held_by_qualified_members` |

### 7.2 Nálezy z overenia harnessu

Tieto chyby našli recenzenti harnessu a každú z nich harness reprodukoval. Každá má test v `test_harness_selfcheck.py::KnownSolverBugTests`.

| Kľúč | Závažnosť | Popis | Dosah v praxi | Navrhovaná oprava |
|---|---|---|---|---|
| `capacity_error_without_tightened_rules` | stredná | Pri zlyhaní predbežnej kontroly kapacity chyba neuvádza `tightened_constraints`, hoci README sľubuje, že pomenuje sprísnené pravidlo. | Najčastejšia cesta zlyhania (56 zo 72 v teste) nedá manažérovi radu, čo uvoľniť. | Doplniť `policy.tightened()` aj do chyby z `_detect_capacity_issues`. |
| `zero_balance_skips_wishes` | nízka – stredná | Pri váhe vyrovnanosti 0 (dovolené v UI) a ničom inom v prvom prechode vráti `value(balance)` `None` a druhý prechod sa potichu vynechá. | Manažér, ktorý vypne vyrovnanosť, prestane mať splnené želania; napríklad človek, ktorý odmietol všetky dni, dostane všetkých 31 služieb. | Ošetriť `reached is None` ako 0, alebo druhý prechod spustiť aj bez zámku. |
| `duplicate_external_dates` | nízka | Dve služby na inom pracovisku v jeden deň: `dict(external_commitments)` ponechá poslednú, takže dlhší odpočinok sa môže stratiť. Výsledok závisí od poradia riadkov. | Len pri ručne zdvojenej službe na inom pracovisku. | Brať maximum odpočinku na dátum. |
| `balance_lock_drift` | nízka | Relatívna tolerancia zámku `1e-7·|reached|` dovolí druhému prechodu mierne horšiu vyrovnanosť (pozorované +0,48) pri veľkých penalizáciách. Tvrdenie dokumentácie 3.2, že rozdiely sú celé čísla, neplatí pri zlomkových hodinách. | Zanedbateľná odchýlka, ale porušuje sľub „želania nikdy nekúpia horšiu vyrovnanosť“. | Absolútna tolerancia; prípadne zámok po ľuďoch (oprava č. 1a). |
| `penalized_rest_month_end` | nízka | Penalizovaný odpočinok sa medzi dvoma službami v modeli účtuje len za dni v mesiaci, voči službám mimo modelu za všetky spoločné dni. | Pri penalizovanom odpočinku sú porušenia na konci mesiaca lacnejšie. | Účtovať aj dni za hranicou mesiaca. |
| `unconfigured_external_rest` | nízka | Služba na pracovisku bez scenára dostane 1 deň odpočinku, nie dokumentovanú záložnú hodnotu (najdlhší odpočinok tu v ten deň). | Len pracovisko, ktoré nikdy nikto nekonfiguroval. | Zjednotiť s dokumentáciou (alebo dokumentáciu s kódom). |
| `noncanonical_reason` | nízka | Dôvod `'preferred'` alebo `' SOFT_DECLINE'` (malé písmená, medzery) sa číta ako tvrdá neprítomnosť; iné služby dôvod normalizujú. | Frontend posiela veľké písmená; týka sa len priameho API. | Normalizovať `reason` (`strip().upper()`) aj v generátore. |
| `retired_competence_rest` | nejasné | Susedná služba v deaktivovanej role: generátor jej dá 1 deň odpočinku, plánovač uložený odpočinok. | Zriedkavé. | Rozhodnúť a zjednotiť. |
| `doc_coverage_equality` | dokumentácia | Model doc 2.1 hovorí o rovnosti pokrytia; predvolene je to „aspoň“ (nadpočet je penalizovaný). | – | Opraviť dokumentáciu. |

### 7.3 Zastarané veci mimo generátora

* `backend/benchmarks/_common.py` importuje `_maximum_nonconsecutive_days` a `_rest_blocked_dates`, ktoré v generátore už neexistujú, takže benchmarky sa nedajú spustiť.
* Docstring `CompetenceWeekdayRequirement` tvrdí, že `recovery_days` „generátor zatiaľ nevynucuje“. Vynucuje ho.
* Model doc 3.6 uvádza, že tolerancia druhého prechodu púšťa „nanajvýš zlomok rozptylu jedného zamestnanca“; v skutočnosti môže pustiť celý člen rozostupu (chyba č. 5).

---

## 8. Obmedzenia testovania

* **Súbežná záťaž.** Väčšina testov bežala súbežne s ďalšími (2 agenti, každý až 6 procesov CBC). Behy, ktoré narazili na časový limit, sa preto z kontrol optimality vynechali a čísla o čase z oddielov 5.1 a 5.2 sú horšie než na voľnom stroji. Oddiel 6 sa meral na voľnom stroji. Platnosť rozpisov a správnosť „nedá sa“ od záťaže nezávisia.
* **Optimalitu nad ~25 ľudí nemožno dokázať úplne.** Overilo sa, že nezostáva zlepšujúci presun ani výmena a že rozpis nie je horší než skrytý platný rozpis. Dôkaz globálneho optima je len na malých mesiacoch (brute force).
* **Frontend** sa testoval len vo funkcii, ktorá počíta konflikty (`scheduleConflicts.js`), nie celé UI.
* **PostgreSQL** sa nepoužil; databázové testy bežia na SQLite.
* Testoval sa generátor tak, ako je; **v `backend/app` sa nič nemenilo**.

---

## 9. Ako spustiť testy

Všetko sa spúšťa z `backend/` cez projektový `venv`.

Posledný beh celej sady v predvolenom režime: **412 testov prešlo, 23 očakávaných zlyhaní** (testy zdokumentovaných chýb z oddielu 7), **14 preskočených** (bežia len v záťažovom režime), **0 zlyhaní**. Trval ~16 min v 3 paralelných prúdoch. Existujúce testy projektu (292) prechádzajú aj naďalej.

```bash
venv/Scripts/python.exe -m pytest tests/test_harness_selfcheck.py tests/test_scenarios_*.py
```

```bash
SCHEDULING_STRESS=1 venv/Scripts/python.exe -m pytest tests/test_scenarios_fill_in.py -s
```

* Predvolený režim trvá ~1,5–4,5 min na súbor.
* Záťažový režim (`SCHEDULING_STRESS=1`) trvá ~2–19 min na súbor; prepínač `-s` vypíše tabuľky.
* Premenné `FILL_IN_REPORT`, `AVAILABILITY_FILL_REPORT`, `MAX_SHIFTS_HOURS_REPORT`, `DETERMINISM_REPORT` a `HARD_FUZZ_METRICS` uložia výsledky ako JSON.
* Prehľad súborov a API harnessu je v `backend/tests/scheduling_harness/README.md`.
