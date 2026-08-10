# Audit logiky ILP/MILP generovania rozvrhu

**Dátum auditu:** 10. 8. 2026  
**Auditovaný stav:** commit `d0efe43` (`ILP`)  
**Hlavný súbor:** `backend/app/services/schedule_generation_service.py`

> **Aktualizácia po audite (10. 8. 2026):** V pracovnej verzii boli na základe
> rozhodnutia vlastníka opravené zákazy susedných pracovných dní, presahy medzi
> ambulanciami a mesiacmi, rozlišovanie skutočnej nedostupnosti a cieľová
> funkcia férovosti. Pokrytie zostáva presne podľa aktívnych kompetencií a
> `required_count` konkrétnej ambulancie na každý kalendárny deň. Manuálna
> validácia zostala vedome mimo rozsahu tejto zmeny.

## 1. Záver

Aktuálny model vie vytvoriť matematicky platný rozvrh podľa svojich vlastných,
užších pravidiel, ale **nezodpovedá požiadavke, že lekár nesmie pracovať dva dni
za sebou bez ohľadu na rolu**. Preto ho v súčasnom stave nemožno považovať za
spoľahlivú implementáciu opísanej reality.

Najzávažnejšie zistenia:

1. zákaz práce dva dni po sebe sa kontroluje iba pre tú istú kompetenciu;
2. preferovaný deň (`PREFERRED`) sa v generátore interpretuje ako nedostupný deň;
3. deklarované vyrovnávanie služieb môže vytvoriť veľmi nevyrovnané výsledky;
4. odpočinok sa nekontroluje voči službám v iných ambulanciách ani správne cez
   hranicu mesiaca;
5. pravidlá platné počas generovania nie sú znovu overené pri manuálnej úprave a
   ukladaní návrhu;
6. každá aktívna kompetencia sa vyžaduje v rovnakom počte každý kalendárny deň,
   bez rozlíšenia pracovných dní, víkendov, sviatkov alebo urgentného pracoviska.

Verdikt: **model potrebuje úpravu pred produkčným používaním**. Body 1 až 4 sú
chyby alebo zásadné doménové nezhody, nie iba vylepšenia optimalizácie.

## 2. Čo model v súčasnosti rieši

Rozhodovacia premenná je binárna:

`x[e, c, d] = 1`, ak zamestnanec `e` pracuje kompetenciu/rolu `c` v deň `d`.

Premenná vznikne iba vtedy, keď:

- zamestnanec je aktívnym členom ambulancie;
- má aktívne priradenú danú kompetenciu;
- deň nie je v načítaných nedostupnostiach;
- v ten istý deň nemá aktívnu službu v inej ambulancii;
- na prvý alebo posledný deň mesiaca nemá v susednom mesiaci rovnakú
  kompetenciu v tej istej ambulancii.

Následne model používa tieto obmedzenia:

1. pre každú kompetenciu a každý deň musí byť priradených presne
   `required_count` ľudí;
2. jeden človek môže mať v generovanej ambulancii najviac jednu kompetenciu za
   deň;
3. jeden človek nemôže mať **rovnakú kompetenciu** dva po sebe idúce dni;
4. cieľ minimalizuje súčet absolútnych odchýlok počtu služieb od jedného
   spoločného priemeru.

Ide technicky o MILP, pretože model obsahuje binárne celočíselné premenné. V
bežnej komunikácii označenie ILP neprekáža.

Kľúčové miesta v zdrojovom kóde:

- tvorba povolených premenných: `schedule_generation_service.py:217-232`;
- denné pokrytie a jedna rola denne: `schedule_generation_service.py:241-262`;
- zákaz iba rovnakej kompetencie po sebe: `schedule_generation_service.py:264-273`;
- cieľová funkcia férovosti: `schedule_generation_service.py:275-295`;
- načítanie nedostupností: `schedule_generation_service.py:362-374`;
- externé a hraničné služby: `schedule_generation_service.py:376-407`;
- význam `PREFERRED` vo frontende: `frontend/src/services/unavailabilityService.js:9-38`;
- validácia a hromadné ukladanie: `schedule_service.py:105-120` a
  `schedule_service.py:170-225`;
- manuálne pridanie a uloženie v editore:
  `AmbulanceScheduleEditView.jsx:468-532`;
- databázový unikátny index: `build.sql:167-174`.

Aktuálna API dokumentácia na `backend/app/api/api.md:207-217` výslovne sľubuje
iba zákaz „rovnakej kompetencie dva dni po sebe“. Implementácia teda zodpovedá
tejto dokumentácii, ale dokumentovaný kontrakt nezodpovedá požiadavke zadanej
pre tento audit.

## 3. Kontrola požadovaných pravidiel

| Požiadavka | Aktuálny stav | Hodnotenie |
|---|---|---|
| Lekár v označený nedostupný deň nemôže pracovať | Premenná sa pre taký deň nevytvorí. | Správne iba pre skutočne nedostupné dni; aktuálne sa rovnako blokuje aj preferovaný deň. |
| Lekár môže pracovať najviac na jednej role za deň | `sum_c x[e,c,d] <= 1`. | Správne v čerstvo vygenerovanom návrhu jednej ambulancie. Ukladacia logika túto podmienku všeobecne negarantuje. |
| Každá rola musí byť dostatočne obsadená | `sum_e x[e,c,d] == required_count[c]`. | Presne obsadí fixný počet, ale rovnaký pre každý kalendárny deň. |
| Lekár nesmie pracovať dva dni za sebou | Kontroluje sa `x[e,c,d] + x[e,c,d+1] <= 1` samostatne pre každú kompetenciu. | **Nesprávne.** Zmena kompetencie dovolí prácu dva dni po sebe. |
| Lekár musí mať kvalifikáciu | Premenné existujú iba pre aktívne priradené kompetencie. | Správne. |
| Lekár nesmie byť v dvoch ambulanciách v ten istý deň | Existujúca služba v inej ambulancii zablokuje daný deň. | Správne pre už uložené dáta, ale bez databázovej ochrany proti súbežnému zápisu. |
| Odpočinok musí platiť aj medzi ambulanciami | Služby z iných ambulancií sa sledujú iba v rovnaký deň. | **Nesprávne/chýba.** |
| Pravidlo musí platiť cez hranicu mesiaca | Kontroluje sa iba rovnaká kompetencia v tej istej ambulancii. | **Nesprávne pre všeobecný zákaz dvoch dní po sebe.** |
| Rozdelenie služieb má byť férové | Minimalizuje sa odchýlka od priemeru počítaného aj z ľudí, ktorí nemôžu odpracovať žiadny deň. | **Nespoľahlivé; existujú optimálne, ale veľmi nevyrovnané výsledky.** |
| Preferované dni majú byť uprednostnené | Preferencia nie je súčasťou cieľovej funkcie. | **Chýba a momentálne sa dokonca správa ako zákaz.** |

## 4. Detailné zistenia podľa priority

### P0 — Zákaz dvoch po sebe idúcich pracovných dní je implementovaný nesprávne

Kód vytvára obmedzenie v cykle po kompetenciách. Zakáže teda iba kombináciu:

- pondelok: triage,
- utorok: triage.

Stále však dovolí napríklad:

- pondelok: triage,
- utorok: zákrok.

To je v rozpore s požiadavkou „dva dni za sebou nemôže pracovať“.

Reprodukčný scenár:

- august 2026;
- 4 lekári;
- všetci ovládajú 2 roly;
- každá rola potrebuje 1 človeka denne;
- nikto nie je nedostupný.

Rozvrh bez po sebe idúcich služieb existuje: dve dvojice sa môžu striedať po
dňoch. Aktuálny solver však vytvoril **21 prípadov**, v ktorých ten istý človek
pracoval aj nasledujúci deň, iba na inej kompetencii.

Správne hard constraint musí byť pre každého človeka a dvojicu susedných dní:

`sum_c x[e,c,d] + sum_c x[e,c,d+1] <= 1`

Toto obmedzenie nesmie byť rozdelené podľa kompetencie.

### P0 — Preferovaný deň sa považuje za nedostupný

Frontend používa jednu tabuľku `unavailabilities` na tri stavy:

- bez záznamu = neutrálny deň;
- `reason = UNAVAILABLE` alebo starší iný dôvod = blokovaný deň;
- `reason = PREFERRED` = preferovaný deň.

Generátor však načíta všetky aktívne záznamy z `unavailabilities` bez kontroly
hodnoty `reason`. Následne ich všetky vloží do `unavailable_dates`. Lekár preto
nemôže byť pridelený práve v deň, ktorý označil ako preferovaný.

Rovnaký problém má aj validácia manuálne ukladaných služieb v
`schedule_service.py`.

Odporúčané riešenie:

- zaviesť explicitný typ/stav dostupnosti v databáze, napríklad
  `UNAVAILABLE` / `PREFERRED`, nie voľný text s implicitným významom;
- iba `UNAVAILABLE` použiť ako hard constraint;
- `PREFERRED` použiť ako soft preferenciu v cieľovej funkcii.

### P1 — Cieľová funkcia negarantuje férový rozvrh

Priemer sa počíta ako:

`celkový počet služieb / počet všetkých kvalifikovaných zamestnancov`.

Do menovateľa sa započítajú aj ľudia, ktorí sú nedostupní celý mesiac alebo pre
ktorých nevznikla žiadna použiteľná premenná. To môže spôsobiť, že všetci reálne
dostupní ľudia sú nad umelo nízkym cieľom. Vtedy je súčet absolútnych odchýlok v
širokom rozsahu rozdelení rovnaký a solver nemá motiváciu služby vyrovnať.

Reprodukčný scenár:

- 5 kvalifikovaných lekárov;
- 1 je nedostupný celý mesiac;
- 4 sú plne dostupní;
- 2 roly po jednom človeku denne, spolu 62 služieb.

Aktuálny solver vrátil počty:

- lekár 1: 0;
- lekár 2: 13;
- lekár 3: 13;
- lekár 4: 13;
- lekár 5: **23**.

Vyrovnanejšie rozdelenie medzi štyroch dostupných ľudí je možné. Výsledok
23/13/13/13 preto vyvracia tvrdenie, že súčasná cieľová funkcia všeobecne
vyrovnáva pracovnú záťaž.

Odporúčanie:

1. určiť individuálny cieľ podľa úväzku, dostupnosti a prípadne zmluvného počtu
   služieb;
2. primárne minimalizovať maximálnu normalizovanú odchýlku alebo maximálne
   zaťaženie;
3. sekundárne minimalizovať súčet odchýlok;
4. preferencie riešiť až ďalšou prioritou, aby neporušili férovosť;
5. pri viacerých cieľoch použiť lexikografickú optimalizáciu alebo jasne
   zdokumentované váhy.

### P1 — Služby v iných ambulanciách a hranice mesiaca sú kontrolované nedostatočne

Vygenerovaný rozvrh blokuje deň, v ktorom má človek už službu v inej
ambulancii. Nekontroluje však deň pred ňou a deň po nej. Pri všeobecnom zákaze
dvoch pracovných dní po sebe musí fixná externá služba v deň `d` zablokovať pre
novú ambulanciu dni `d-1`, `d` aj `d+1`.

Na hranici mesiaca sa načítajú iba služby:

- v tej istej ambulancii;
- presne deň pred začiatkom alebo deň po konci mesiaca;
- s identifikátorom rovnakej kompetencie.

To dovolí človeku pracovať 31. júla na role A a 1. augusta na role B. Dovolí aj
kombináciu 31. júla v inej ambulancii a 1. augusta v generovanej ambulancii.

Odporúčané načítanie fixných služieb:

- všetky aktívne služby daných ľudí vo všetkých ambulanciách v intervale
  `start - 1 deň` až `end + 1 deň`;
- služby v generovanej ambulancii vnútri mesiaca možno považovať za nahrádzaný
  návrh, ale služby mimo mesiaca sú pevné;
- externá služba musí blokovať aj susedné dni, ak je odpočinok globálnym
  pravidlom človeka.

### P1 — Pokrytie je fixné pre každý kalendárny deň

`required_count` patrí ku kompetencii a model ho použije bez zmeny na každý deň
mesiaca. Neexistuje:

- kalendár otvorených pracovných dní;
- iný počet ľudí cez pracovný deň a cez víkend;
- podpora sviatkov;
- denná výnimka;
- rozdiel v plánovaní urgentnej a štandardnej ambulancie, hoci model ambulancie
  obsahuje `isurgent`.

Toto môže byť správne pre nepretržitú prevádzku, ale je veľmi pravdepodobne
nesprávne pre bežnú ambulanciu. Pred opravou treba potvrdiť doménové pravidlo:

- ktoré pracoviská sa plánujú 7 dní v týždni;
- či `required_count` znamená presný alebo minimálny počet;
- či sa počet mení podľa dňa.

Aktuálna rovnosť `== required_count` je vhodná, ak ide o presný počet pozícií.
Ak ide o minimum, treba vedome rozhodnúť, či nadpočet vôbec povoľovať. Samotná
zmena na `>=` bez úpravy cieľovej funkcie nie je bezpečná, pretože optimizer by
mohol pridávať nepotrebné služby na znižovanie odchýlok.

### P1 — Uloženie manuálne upraveného návrhu nechráni invarianty modelu

Endpoint generovania vracia neuložený návrh. Manažér ho môže v UI meniť a až
potom uložiť hromadným `PUT`.

Pri uložení sa kontroluje členstvo, kompetencia, nedostupnosť a už uložená
služba v inej ambulancii. Nekontroluje sa však:

- najviac jedna rola človeka za deň v tej istej ambulancii;
- zákaz práce dva dni po sebe;
- počet ľudí na každej role a deň;
- úplnosť pokrytia;
- duplicita človeka v rozdielnych rolách toho istého dňa;
- zmena `required_count` medzi generovaním a uložením.

Frontend navyše umožňuje pridať ďalší záznam do ľubovoľného dňa a pri výbere
človeka nekontroluje jeho ostatné služby v lokálnom návrhu. Databázový unikátny
index obsahuje aj `competence_id`, takže rovnaký človek môže mať v ten istý deň
dve rôzne kompetencie.

Výsledok: validný vygenerovaný návrh sa môže pred uložením zmeniť na rozvrh,
ktorý porušuje základné pravidlá, a backend ho prijme.

Odporúčanie: vytvoriť jednu spoločnú validačnú funkciu invariantov a spúšťať ju
aj nad hromadným návrhom tesne pred transakčným uložením. UI kontrola je vhodná
pre používateľský komfort, ale backend musí byť autoritatívny.

### P2 — Kompetencia a pracovná rola musia mať jednoznačnú doménovú interpretáciu

Systém používa `Role` pre oprávnenia používateľa a `Competence` pre prácu v
rozvrhu. Solver predpokladá, že **každá aktívna kompetencia je samostatná povinná
denná pozícia**, ktorú treba obsadiť `required_count` ľuďmi.

To je správne iba vtedy, ak kompetencie naozaj reprezentujú rozvrhové roly
(napríklad triage, odbery, recepcia). Ak niektoré reprezentujú iba certifikácie
alebo schopnosti, model ich nesprávne vytvorí ako samostatné povinné miesta.

Pred ďalším vývojom treba doménovo potvrdiť:

- či kompetencia je zároveň obsadzovaná rola;
- či jedna rola môže vyžadovať viac kompetencií;
- či človek na jednej role môže súčasne pokryť viac požiadaviek.

### P2 — Diagnostika neriešiteľnosti je iba čiastočná

Predbežná kontrola vie nájsť:

- málo unikátnych ľudí v konkrétny deň;
- málo kvalifikovaných ľudí pre konkrétnu kompetenciu;
- málo ľudí na striedanie tej istej kompetencie cez dva dni.

Nevie však vysvetliť všetky konflikty spôsobené prekryvom kvalifikácií a
pravidlom jednej roly denne. Po zlyhaní solvera sa preto často vráti iba
`constraint_conflict` bez konkrétnej príčiny. Po zmene pravidla odpočinku treba
zmeniť aj predbežnú kontrolu; súčasná kontrola po kompetenciách už nebude
zodpovedať modelu.

### P2 — Chýbajú produkčné limity solvera

CBC sa spúšťa bez časového limitu. Pri väčšom počte ľudí, rolí alebo ďalších
obmedzeniach môže API požiadavka trvať neprimerane dlho. Produkčná verzia by mala
mať:

- časový limit;
- rozlíšenie stavov optimal, feasible-with-gap, infeasible a timeout;
- logovanie veľkosti modelu a času riešenia;
- prípadne asynchrónne generovanie pre väčšie inštancie.

## 5. Navrhovaný model

### Hard constraints

1. **Kvalifikácia a členstvo**  
   `x[e,c,d]` môže existovať iba pre aktívneho člena ambulancie s aktívnou
   kompetenciou.

2. **Skutočná nedostupnosť**  
   Ak je `availability[e,d] = UNAVAILABLE`, potom `sum_c x[e,c,d] = 0`.

3. **Jedna rola denne**  
   `sum_c x[e,c,d] <= 1`.

4. **Denné pokrytie**  
   `sum_e x[e,c,d] == demand[c,d]` pre každý plánovaný deň a rolu.

5. **Žiadne dva pracovné dni za sebou**  
   `sum_c x[e,c,d] + sum_c x[e,c,d+1] <= 1`.

6. **Fixné služby mimo generovaného návrhu**  
   Existujúce služby vo všetkých ambulanciách musia blokovať rovnaký a pri
   pravidle odpočinku aj susedné dni.

7. **Hranica mesiaca**  
   Služba deň pred mesiacom zablokuje prvý deň a služba deň po mesiaci
   zablokuje posledný deň bez ohľadu na kompetenciu alebo ambulanciu.

8. **Individuálne limity**  
   Ak realita vyžaduje maximálny počet služieb alebo zmluvný fond, treba pridať
   `min_shifts[e]`, `max_shifts[e]` alebo individuálny cieľ.

### Soft constraints a poradie cieľov

Odporúčané poradie:

1. minimalizovať najväčšie prekročenie individuálneho cieľa;
2. minimalizovať celkovú odchýlku od cieľov;
3. maximalizovať využitie preferovaných dní;
4. minimalizovať nežiaduce víkendy/sviatky alebo ich nerovnomerné rozdelenie;
5. použiť stabilný tie-break pre reprodukovateľný výsledok.

Hard pravidlá sa nesmú nahrádzať vysokou penalizáciou. Nedostupnosť,
kvalifikácia, pokrytie, jedna rola denne a povinný odpočinok majú zostať
neporušiteľné.

## 6. Chýbajúce doménové rozhodnutia

Pred finálnou implementáciou treba od vlastníka procesu získať odpovede:

1. Platí zákaz dvoch dní po sebe globálne vo všetkých ambulanciách?
2. Je `required_count` presný počet alebo minimálny počet?
3. Ktoré ambulancie fungujú cez víkendy a sviatky?
4. Mení sa požadované obsadenie podľa konkrétneho dňa?
5. Majú zamestnanci rovnaké úväzky a rovnaký cieľ služieb?
6. Existuje mesačné minimum/maximum služieb alebo hodín?
7. Ako silná je preferencia zelených dní voči férovosti?
8. Treba vyrovnávať osobitne víkendy, sviatky alebo jednotlivé roly?
9. Je `Competence` vždy obsadzovaná rola, alebo niekedy iba certifikácia?
10. Majú manuálne úpravy povoliť vedomú výnimku, a ak áno, kto ju môže schváliť
    a ako sa zaznamená?

## 7. Minimálny testovací plán po oprave

### Hard constraints

- nedostupný človek sa nikdy nepriradí;
- preferovaný deň zostane dostupný a môže dostať službu;
- človek nemá viac než jednu rolu v deň;
- každá rola má presne požadované obsadenie;
- človek nepracuje dva susedné dni ani pri zmene roly;
- služba 31. júla blokuje 1. august a naopak;
- služba v inej ambulancii blokuje rovnaký aj susedný deň;
- nekvalifikovaný alebo neaktívny človek sa nepriradí;
- infeasible prípad vráti zrozumiteľný dôvod.

### Férovosť

- pri štyroch rovnako dostupných ľuďoch a 62 službách je rozdiel počtov najviac
  jeden, ak ostatné pravidlá umožňujú také rozdelenie;
- človek nedostupný celý mesiac nespôsobí degeneráciu 23/13/13/13;
- rozdielne úväzky vedú k pomernému rozdeleniu;
- preferované dni nemenia hard constraints a nevedú k neprimeranému zaťaženiu.

### Ukladanie a manuálne úpravy

- bulk save odmietne dve roly jedného človeka v rovnaký deň;
- bulk save odmietne po sebe idúce dni;
- bulk save odmietne podstav aj nadstav, ak sa vyžaduje presné obsadenie;
- validácia prebehne v jednej transakcii nad konečným návrhom;
- súbežné uloženie rozvrhov dvoch ambulancií nevytvorí dvojité pridelenie.

## 8. Vykonané overenia

Spustené existujúce testy:

`python -m unittest discover -s tests -v`

Výsledok: **2 testy prešli**. To potvrdzuje implementáciu súčasného užšieho
kontraktu, nie požadovaný všeobecný zákaz práce dva dni po sebe. Existujúci test
výslovne kontroluje iba opakovanie rovnakej kompetencie.

Okrem toho boli spustené dva izolované reprodukčné scenáre priamo nad
`solve_monthly_schedule`:

1. model vytvoril 21 po sebe idúcich pracovných dvojíc cez zmenu kompetencie;
2. model rozdelil služby medzi štyroch plne dostupných ľudí ako 23/13/13/13,
   keď piaty kvalifikovaný človek nemohol pracovať celý mesiac.

Počas pôvodného auditu nebol zmenený produkčný kód ani databáza. Následná
implementácia opráv zmenila generátor, jeho testy, text diagnostiky vo frontende
a API dokumentáciu; databázová schéma zostala bez zmeny.

### Stav následnej implementácie

- zákaz susedných pracovných dní sa sčítava cez všetky kompetencie;
- pevná služba v inej ambulancii blokuje deň pred ňou, daný deň aj deň po nej;
- externé služby sa načítavajú aj jeden deň pred a po generovanom mesiaci;
- služba v rovnakej ambulancii na hranici mesiaca blokuje človeka bez ohľadu na
  kompetenciu;
- `PREFERRED` nie je hard zákaz; ostatné aktívne záznamy nedostupnosti zostávajú
  blokované;
- férovosť používa konvexnú cenu druhej mocniny počtu služieb. Reprodukčný
  prípad 23/13/13/13 sa po oprave rozdelí 16/16/15/15;
- presné denné obsadenie každej kompetencie podľa jej `required_count` zostalo
  zachované;
- regresná sada sa rozšírila z 2 na 9 testov a všetkých 9 prechádza vrátane
  servisného testu nad dočasnou relačnou databázou.

Budúce hodinové limity zatiaľ nemožno priamo započítať, pretože rozvrhová
položka obsahuje iba dátum a nemá dĺžku služby ani individuálny maximálny fond
hodín. Konvexná férovostná časť je oddelená tak, aby sa dala neskôr rozšíriť z
počtu služieb na hodinové segmenty.

## 9. Odporúčané poradie opráv

1. opraviť hard constraint dvoch po sebe idúcich dní;
2. oddeliť `UNAVAILABLE` od `PREFERRED`;
3. načítať externé a hraničné služby globálne;
4. opraviť cieľovú funkciu férovosti;
5. zaviesť deňovo závislé `demand[c,d]` alebo kalendár plánovaných dní;
6. zdieľať invariantnú validáciu medzi generovaním a ukladaním;
7. doplniť testy uvedené vyššie;
8. zlepšiť diagnostiku infeasibility a pridať časový limit solvera.
