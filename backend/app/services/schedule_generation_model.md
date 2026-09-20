# Model generovania rozpisu

Ako je zostavená úloha zmiešaného celočíselného programovania (MILP), ktorú
rieši `schedule_generation_service.solve_monthly_schedule`. Jedna úloha, dva
prechody, jedna ambulancia, jeden kalendárny mesiac.

---

## 1. Premenné

### Priradenia

Jediné skutočné rozhodnutie modelu:

```
x[z, k, d] ∈ {0, 1}     zamestnanec z slúži kompetenciu k v deň d
```

Premenná **vôbec nevznikne**, ak je priradenie nemožné. To je lacnejšie než
ju vytvoriť a zakázať podmienkou, a zároveň to zmenšuje model:

| Vynechané, keď | |
|---|---|
| `k ∉ z.competence_ids` | zamestnanec kompetenciu nemá |
| `d` je mimo generovacieho okna (`generate_from`) | deň už je odslúžený |
| požiadavka na `k` v deň `d` je nula | nikto tam netreba |
| `d ∈ z.unavailable_dates` | tvrdá neprítomnosť (dovolenka, PN) |
| `d` koliduje so záväzkom, ktorý už zamestnanec má | viď nižšie |

Záväzok je služba, ktorú už niekomu dlží a model ju nemení: ručne vložená
služba, služba tesne pred alebo za hranicou mesiaca, alebo služba na inej
ambulancii. Kolízia nastáva v troch prípadoch: je to ten istý deň, záväzok
ešte drží deň `d` v regenerácii, alebo by regenerácia po `d` prekryla
záväzok.

Výnimka: **ručne vložená služba dostane premennú vždy**, aj mimo okna a aj
na deň, ktorý inak neprejde filtrami. Rozvrhár už rozhodol.

### Pomocné premenné

Všetky sú **spojité**, nie binárne — a je to zámer, nie nedbalosť. Každá je
v cieľovej funkcii tlačená len jedným smerom, takže v optime aj tak dosadne
na celé číslo. Solver tým pádom nemusí na žiadnej z nich vetviť.

| Premenná | Rozsah | Význam |
|---|---|---|
| `level_<rebrík>_<stupeň>` | ⟨0, 1⟩ | jeden stupeň rebríka záťaže |
| `over_wish_<z>` | ⟨0, ∞) | koľko služieb nad mesačné želanie |
| `close_<z>_<d>_<g>` | ⟨0, 1⟩ | zamestnanec `z` slúži aj `d`, aj `d+g` |

---

## 2. Tvrdé podmienky

Nič ich neprebije. Ak sa nedajú splniť, generovanie skončí chybou so
štruktúrovaným zoznamom konfliktov, nie horším rozpisom.

### 2.1 Pokrytie

Pre každú kompetenciu a každý deň generovacieho okna:

```
Σ_z x[z, k, d] = required_on(d)
```

Rovnosť, nie nerovnosť — presne toľko ľudí, koľko je nastavené. Počet je
per-weekday a deň odpočinku (sviatok) má vlastný, ôsmy slot mimo pondelka
až nedele.

### 2.2 Jedna služba denne a regenerácia

Jedna podmienka pokrýva oboje. Pre každého zamestnanca a každý deň:

```
Σ (služby začaté skôr, ktorých regenerácia siaha na d)  +  Σ x[z, ·, d]  ≤  1
```

Služba začatá v `e` siaha na `d`, ak `e < d ≤ e + recovery_days(k, e)`.
Regenerácia je nastavená per kompetenciu a per weekday, takže víkendová
služba môže dávať iný odpočinok než utorková.

Prečo to ide do jednej podmienky: všetky členy na ľavej strane sa navzájom
vylučujú, takže „dnes nastúpim" a „ešte dobieham" nie sú dve pravidlá, ale
dve strany toho istého.

Služby na **inej ambulancii** sa rátajú rovnako. Koľko odpočinku dávajú, sa
číta z kalendára tej ambulancie; keď tam nič nastavené nie je, použije sa
najdlhší odpočinok, aký by za ten deň dala táto ambulancia.

Podmienka sa vynechá, keď má ľavá strana menej než dva členy — vtedy je
triviálne splnená.

### 2.3 Ručné priradenia

Každé `x` z `fixed_assignments` je pripnuté na 1. Zároveň sa pred
zostavením modelu kontrolujú samy proti sebe (`fixed_assignment_conflict`,
`..._rest_conflict`, `..._over_requirement`) — model, ktorý je nesplniteľný
už zo vstupu, sa ani nezačne riešiť.

---

## 3. Cieľová funkcia

Tu je jadro. Členy sú rozdelené do dvoch skupín a **riešia sa v dvoch
oddelených prechodoch**, nie ako jedna vážená suma.

### Prvý prechod: `balance`

#### 3.1 Mesačné želanie

```
over_wish[z] ≥ Σ x[z, ·, ·] − z.max_shifts_per_month
cena:  1000 · over_wish[z]
```

Želanie je želanie, nie strop. Prekročiť sa dá, ale za cenu, ktorá je rádovo
nad každým krokom vyrovnanosti — takže sa to stane len vtedy, keď sa mesiac
inak obsadiť nedá.

#### 3.2 Vyrovnanosť: štyri konvexné rebríky na zamestnanca

Toto je hlavný člen. Záťaž `L` sa rozloží na stupne po jednom:

```
Σ level[s] · krok = L,     level[s] ∈ ⟨0, 1⟩
cena = Σ jednotka · (2s − 1) · level[s]
```

Súčet po sebe idúcich nepárnych čísel je druhá mocnina, takže cena rastie
kvadraticky so záťažou. Dôsledok: **každá ďalšia služba je drahšia než
predošlá**, a najlacnejší rozpis je ten rovnomerne rozdelený. Rebríky sa
dopĺňajú zdola nahor samy od seba, lebo nižšie stupne sú lacnejšie — preto
netreba celočíselnosť.

Rebríky sú štyri, aby sa nekopilo ani jedno:

| Rebrík | Čo meria | Jednotka |
|---|---|---|
| `total` | všetky služby | 4 |
| `surcharge` | príplatkové služby | 3 alebo 5 |
| `standard` | bežné služby | 5 alebo 3 |
| `hours` | odslúžené hodiny | 4, krok = priemerná dĺžka služby |

Dve čísla pri kindových rebríkoch sú tá istá vec z dvoch strán: kto si pýta
príplatkové, platí za ne 3 a za bežné 5; kto si pýta bežné, naopak; kto
nemá názor, platí 4 za oboje. Rozdiel je presne to, čo spôsobí, že
príplatkovo naladený človek skončí s viac príplatkovými a menej bežnými
službami, **pričom jeho celková záťaž ostane na úrovni ostatných** — lebo
nad tým stále stojí rebrík `total`.

Hodinový rebrík je krokovaný v „jednej priemernej službe" mesiaca, aby
človek so službami bežnej dĺžky stúpal po ňom rovnako rýchlo ako po
rebríku počtov. Kde sú všetky služby rovnako dlhé, obidva rebríky hovoria
to isté; kde sa miešajú štvorhodinové s dvanásťhodinovými, rozpis vyjde
vyrovnaný v oboch.

Výška každého rebríka nie je odhad — je to `_best_spaced_value`, spätný
prechod cez kandidátske dni, ktorý presne spočíta, koľko sa dá maximálne
odslúžiť pri rešpektovaní regenerácií. (Spätný, lebo skoršie dni s dlhým
odpočinkom sa niekedy oplatí preskočiť, takže hladový prechod by dal zlú
odpoveď.)

Pretože sú všetky jednotky celé čísla, je celé číslo aj každý rozdiel medzi
dvoma rozpismi. **Najmenšie možné zhoršenie vyrovnanosti je presne 1.** To
je priestor, ktorý si delia členy druhého prechodu.

### Uzamknutie

Prvý prechod sa vyrieši, odčíta sa dosiahnutá hodnota a zapíše sa späť do
modelu ako tvrdá podmienka:

```
balance ≤ dosiahnuté + tolerancia
```

Toto je to, čo robí sľub presným: **žiadny počet splnených želaní nekúpi
menej vyrovnaný rozpis, lebo menej vyrovnaný rozpis už nie je prípustný.**
Zároveň je to rýchle — ani jeden prechod nemusí vážiť celú hodinu
spravodlivosti proti zlomku niečieho želania.

### Druhý prechod: `wishes`

#### 3.3 Denné želania

```
−10 · Σ x[z, ·, d]   pre d ∈ z.preferred_dates
+10 · Σ x[z, ·, d]   pre d ∈ z.soft_declined_dates
```

Symetricky: deň, ktorý si niekto vypýtal, sa odmení; deň, ktorý by radšej
nemal, sa potrestá. „Radšej nie" nie je neprítomnosť — je to cena, nie
zákaz.

#### 3.4 Rozptyl

Dĺžka medzery **nie je premenná modelu**. Premenné hovoria, ktoré dni sa
slúžia; medzery sú až dôsledok. Cena medzery sa preto účtuje dvojici
služieb, ktorá ju ohraničuje — je to tá istá vec povedaná z druhej strany.

Pre každú dvojicu kandidátskych dní `d` a `d + g`, kde `g ≤ 7`:

```
Σ x[z, ·, d] + Σ x[z, ·, d+g] − 1  ≤  close[z, d, g]
cena:  (jednotka / g) · close[z, d, g]
```

Príznak vyskočí na 1 práve vtedy, keď sa slúžia oba dni, inak klesne na
nulu — a keďže ho cieľová funkcia tlačí len nadol, nemusí byť binárny.

Tvar `1/g` je presne to, o čo tu ide:

| medzera | cena | úspora oproti predošlej |
|---|---|---|
| 1 deň | 1,000 | — |
| 2 dni | 0,500 | **0,500** |
| 3 dni | 0,333 | 0,167 |
| 4 dni | 0,250 | 0,083 |
| 7 dní | 0,143 | 0,024 |

Roztiahnuť jednodňovú medzeru na dvojdňovú je teda trikrát cennejšie než
roztiahnuť dvojdňovú na trojdňovú, a dvadsaťnásobne cennejšie než
roztiahnuť šesťdňovú na sedemdňovú. Model tlačí tam, kde to reálne bolí.

Dve orezania, aby model nenarástol:

- **Dvojice, ktoré tvrdá regenerácia už zakazuje, sa preskakujú.** Ak je
  `g ≤ najkratšia regenerácia` daného dňa, príznak by nikdy nevyskočil.
- **Dvojice ďalej než týždeň sa neúčtujú vôbec.** Ich váha je už tak
  zanedbateľná, a každý ďalší deň dosahu stojí druhý prechod reálny čas —
  je to jeden príznak navyše na zamestnanca a deň.

Účtujú sa aj nesusedné dvojice, nielen susedné. Nie je to chyba — tie sú z
definície ďaleko a platia málo; je to konzervatívny odhad zhora.

#### 3.5 Rozpočet rozptylu

Bez normalizácie by ťažko zaťažený mesiac nazbieral toľko dvojíc, že by
rozptyl prebil denné želania. Preto má každý zamestnanec **vlastnú
jednotku**, škálovanú na jeho vlastný najhorší prípad:

```
najhorší_prípad = kapacita · Σ_{g=1..7} 1/g
jednotka = 1,0 / najhorší_prípad
```

Každá služba ohraničuje najviac jednu účtovanú dvojicu na dĺžku medzery,
takže celý člen nemôže presiahnuť plný rozpis násobený najstrmšími
sadzbami. Vydelením tým vychádza, že **rozptyl jedného zamestnanca nikdy
neprekročí 1,0 — desatinu jedného denného želania** — nech už slúži štyri
alebo pätnásť služieb.

#### 3.6 Kedy sa druhý prechod zastaví

Rozptyl je jemne odstupňovaný člen s veľa takmer rovnocennými riešeniami —
presne ten druh úlohy, kde CBC nájde dobrú odpoveď rýchlo a potom dlhé
minúty dokazuje, že o chlp lepšia neexistuje. Druhý prechod preto dostáva
absolútnu toleranciu optimality:

```
WISH_OPTIMALITY_TOLERANCE = SPREAD_BUDGET = 1,0
```

Riešenie takto blízko optimu **nemôže mať nesplnené denné želanie** — jedno
stojí desať. Čo tolerancia púšťa, je nanajvýš zlomok rozptylu jedného
zamestnanca. Čo za to kupuje, je rádový rozdiel: na testovacom mesiaci
štyroch zamestnancov spadol druhý prechod zo 60 sekúnd (a aj tak
nedokázaný) na pol sekundy, s rovnakým výsledkom.

---

## 4. Celkové poradie síl

| # | Člen | Rádová cena | Prechod |
|---|---|---|---|
| 1 | Pokrytie, dostupnosť, regenerácia, ručné služby | tvrdé | oba |
| 2 | Služba nad mesačné želanie | 1000 | prvý |
| 3 | Vyrovnanosť (najmenší krok) | 1 | prvý |
| 4 | Denné želanie | 10 | druhý |
| 5 | Rozptyl (celkovo na človeka) | ≤ 1 | druhý |

Členy 4 a 5 sa nikdy nemerajú proti členom 2 a 3 — tie sú v čase, keď sa
riešia, už uzamknuté ako podmienka. Rozptyl teda rozhoduje len remízy medzi
rozpismi, ktoré sú **už rovnako dobré vo všetkom ostatnom**.

---

## 5. Priebeh riešenia

1. Zostaví sa model, prebehne detekcia zjavných konfliktov kapacity a
   ručných priradení.
2. **Prvý prechod** minimalizuje `balance` v rámci časového rozpočtu.
   Bez riešenia → `solver_timeout` alebo `constraint_conflict`.
3. Výsledok sa odfotí (`_snapshot`) a dosiahnutá vyrovnanosť sa uzamkne.
4. **Druhý prechod** minimalizuje `wishes` vo zvyšku časového rozpočtu,
   s toleranciou optimality podľa 3.6.
5. Ak druhý prechod nedobehne, obnoví sa snímka prvého. Želania sú láskavosť;
   vyrovnaný rozpis je odpoveď.
6. Výstup sa deterministicky zoradí podľa dňa, kompetencie a zamestnanca.
