/**
 * Seedovaný náhľad obrazovky „Rozpis pracoviska“ — bez backendu a bez
 * prihlásenia. Vykreslí skutočný SchedulePlannerView so zabudovanými dátami
 * (7 kompetencií, 22 ľudí, vygenerovaný mesiac s pár zámernými konfliktmi).
 *
 * Len pre vývoj: Vite ho servíruje na /preview.html, produkčný build ho
 * neobsahuje (zostavuje sa iba index.html).
 *   ?state=dirty         – neuložené zmeny (tlačidlá)
 *   ?toast=1 / ?error=1  – ukáže toast / chybové okno
 *   ?conflicts=0         – mesiac bez konfliktov
 */
/* eslint-disable react-refresh/only-export-components */
import { StrictMode, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import '../index.css';
import '../styles/ui.css';
import '../i18n';
import '../theme';
import '../views/AmbulanceScheduleEditView.css';
import SchedulePlannerView from '../components/SchedulePlannerView';
import PeriodStepper from '../components/PeriodStepper';
import Toast from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import { ResetIcon, SaveIcon, SealIcon } from '../components/NavIcons';
import { analyzeScheduleConflicts } from '../utils/scheduleConflicts';

const params = new URLSearchParams(window.location.search);
const dirty = params.get('state') === 'dirty';
const withConflicts = params.get('conflicts') !== '0';

const COLORS = ['#6e56cf', '#e5484d', '#0091ff', '#30a46c', '#f76b15', '#12a594', '#d6409f'];
const NAMES = [
  'Detská anestéziológia',
  'Kardiochirurgia',
  'Pohotovosť',
  'Operačná sála',
  'Pooperačná starostlivosť',
  'Intenzívna jednotka',
  'Ambulancia',
];
const competences = NAMES.map((name, i) => ({
  id: i + 1,
  name,
  color: COLORS[i],
  description: name,
  weekday_requirements: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
    weekday,
    required_count: i === 2 ? (weekday >= 5 ? 2 : 1) : weekday >= 5 && i > 3 ? 0 : 1,
  })),
}));

const SURNAMES = [
  'Novák', 'Kováč', 'Horváth', 'Varga', 'Tóth', 'Nagy', 'Baláž', 'Szabó', 'Molnár', 'Lukáč',
  'Kollár', 'Polák', 'Hudák', 'Marek', 'Jurák', 'Sedláček', 'Urban', 'Fico', 'Hrnčiar',
  'Dubovský', 'Šimko', 'Králik',
];
const employees = SURNAMES.map((surname, i) => ({
  user_id: i + 1,
  full_name: `${'ABCDEFGHJKLMNOPRSTUVZ'[i]}. ${surname}`,
  email: `osoba${i + 1}@example.test`,
  competences: competences
    .filter((c) => (i + c.id) % 3 !== 0 || c.id === 3)
    .map((c) => ({ id: c.id, name: c.name })),
}));

const year = 2026;
const month = 9;
const days = new Date(year, month + 1, 0).getDate();
const pad = (n) => String(n).padStart(2, '0');
const iso = (day) => `${year}-${pad(month + 1)}-${pad(day)}`;

const buildShifts = () => {
  const out = [];
  let id = 1;
  for (let day = 1; day <= days; day += 1) {
    const weekday = (new Date(year, month, day).getDay() + 6) % 7;
    competences.forEach((c) => {
      const need = c.weekday_requirements[weekday].required_count;
      for (let n = 0; n < need; n += 1) {
        // diery v obsadení, aby bolo čo dopĺňať
        if (withConflicts && (day * 7 + c.id * 3) % 11 === 0) continue;
        const pool = employees.filter((e) => e.competences.some((k) => k.id === c.id));
        const person = pool[(day * 3 + c.id * 5 + n * 7) % pool.length];
        out.push({
          id: id++,
          work_date: iso(day),
          user_id: person.user_id,
          competence_id: c.id,
          competence_name: c.name,
          user_full_name: person.full_name,
          user_email: person.email,
        });
      }
    });
  }
  if (withConflicts) {
    // dve roly v jeden deň + služba bez kompetencie
    [[6, 1, 2], [7, 3, 6], [9, 5, 1]].forEach(([day, userId, competenceId]) => {
      const e = employees[userId - 1];
      out.push({
        id: id++,
        work_date: iso(day),
        user_id: userId,
        competence_id: competenceId,
        competence_name: NAMES[competenceId - 1],
        user_full_name: e.full_name,
        user_email: e.email,
      });
    });
  }
  return out;
};

const Preview = () => {
  const [shifts, setShifts] = useState(buildShifts);
  const [budget, setBudget] = useState(30);
  const today = useMemo(() => new Date(year, month, 12), []);

  const shiftsByDate = useMemo(() => {
    const map = {};
    shifts.forEach((s) => {
      (map[s.work_date] = map[s.work_date] || []).push(s);
    });
    return map;
  }, [shifts]);

  const conflictReport = useMemo(
    () =>
      analyzeScheduleConflicts({
        year,
        month,
        ambulanceId: 1,
        shifts,
        employees,
        competences,
        restDays: new Set(),
        context: null,
      }),
    [shifts]
  );

  const identity = (
    <div className="schedule-edit-identity">
      <h1 className="page-title">Rozpis pracoviska</h1>
      <div className="schedule-edit-state">
        <span className={`badge badge-dot ${dirty ? 'badge-warning' : ''}`}>
          {dirty ? 'Neuložené zmeny' : 'Uložené'}
        </span>
        <span className="badge badge-dot">Neschválený</span>
      </div>
    </div>
  );
  const actions = (
    <div className="schedule-edit-topbar-actions">
      {dirty && (
        <button type="button" className="btn btn-ghost">
          <ResetIcon />
          Zrušiť zmeny
        </button>
      )}
      <button type="button" className="btn btn-primary schedule-edit-save" disabled={!dirty}>
        <SaveIcon />
        Uložiť
      </button>
      <button type="button" className="btn schedule-edit-approve" disabled={dirty}>
        <SealIcon />
        Schváliť
      </button>
    </div>
  );
  const period = (
    <PeriodStepper
      label="október 2026"
      onPrevious={() => {}}
      onNext={() => {}}
      previousLabel="Predchádzajúci mesiac"
      nextLabel="Nasledujúci mesiac"
      todayLabel="Aktuálny mesiac"
      onToday={() => {}}
      compactToday
      todayDisabled
      todaySide="end"
      groupLabel="Mesiac"
    />
  );

  const assign = (dateStr, competenceId, userId) => {
    const e = employees.find((x) => x.user_id === userId);
    setShifts((cur) => [
      ...cur,
      {
        id: `n${cur.length}-${dateStr}-${userId}`,
        work_date: dateStr,
        user_id: userId,
        competence_id: competenceId,
        competence_name: NAMES[competenceId - 1],
        user_full_name: e.full_name,
        user_email: e.email,
      },
    ]);
  };

  return (
    <div className="schedule-edit" style={{ padding: 20 }}>
      <SchedulePlannerView
        identity={identity}
        actions={actions}
        period={period}
        year={year}
        month={month}
        today={today}
        locale="sk-SK"
        weekdayLabels={['Po', 'Ut', 'St', 'Št', 'Pi', 'So', 'Ne']}
        competences={competences}
        employees={employees}
        shiftsByDate={shiftsByDate}
        restDays={new Set()}
        competenceColor={(id) => COLORS[id - 1]}
        conflictReport={conflictReport}
        loading={false}
        onAssign={assign}
        onRemoveShift={(shiftId) => setShifts((cur) => cur.filter((s) => s.id !== shiftId))}
        onGenerate={() => {}}
        generateLabel="Generovať rozvrh"
        generateHint="Vytvorí optimalizovaný návrh."
        timeBudget={budget}
        timeBudgetOptions={[
          { value: 30, label: '30 s' },
          { value: 120, label: '2 min' },
          { value: 600, label: '10 min' },
        ]}
        onTimeBudgetChange={setBudget}
        generateDisabled={false}
        onClear={() => setShifts([])}
        clearLabel="Vyčistiť rozvrh"
        clearDisabled={false}
      />
      {params.get('toast') && (
        <Toast
          message="Vygenerovaný návrh obsahuje 183 služieb. Skontrolujte ho a potom ho uložte."
          tone="success"
          onClose={() => {}}
          closeLabel="Zavrieť"
        />
      )}
      <ConfirmDialog
        open={!!params.get('error')}
        tone="danger"
        title="Niečo sa nepodarilo"
        message={'1. 10. – Pohotovosť: dostupných 1, potrebných 2.\n2. 10. – celková kapacita: dostupných 5, potrebných 7.'}
        confirmLabel="Zavrieť"
        hideCancel
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    </div>
  );
};

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Preview />
  </StrictMode>
);
