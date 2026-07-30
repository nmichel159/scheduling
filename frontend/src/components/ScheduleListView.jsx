import './ScheduleListView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) =>
  `${year}-${pad(month + 1)}-${pad(day)}`;

/**
 * Alternative monthly schedule view.
 * Each calendar day occupies one row and uses the same shift data and editing
 * callbacks as the classic calendar grid.
 */
const ScheduleListView = ({
  year,
  month,
  locale,
  today,
  shiftsByDate,
  competenceColor,
  loading,
  dragOverDate,
  onDragStart,
  onDragOver,
  onDragEnter,
  onDragLeave,
  onDrop,
  onShiftClick,
  onShiftRemove,
  removeShiftLabel,
}) => {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
  });
  const weekdayFormatter = new Intl.DateTimeFormat(locale, {
    weekday: 'long',
  });

  return (
    <div className={`schedule-list-view ${loading ? 'is-loading' : ''}`}>
      {Array.from({ length: daysInMonth }, (_, index) => index + 1).map((day) => {
        const date = new Date(year, month, day);
        const dateStr = isoDate(year, month, day);
        const dayShifts = shiftsByDate[dateStr] || [];
        const isToday =
          day === today.getDate() &&
          month === today.getMonth() &&
          year === today.getFullYear();
        const isDragOver = dragOverDate === dateStr;

        return (
          <div
            key={dateStr}
            className={`schedule-list-row ${isToday ? 'is-today' : ''} ${
              isDragOver ? 'is-drag-over' : ''
            }`}
            onDragOver={onDragOver}
            onDragEnter={(event) => onDragEnter(event, dateStr)}
            onDragLeave={onDragLeave}
            onDrop={(event) => onDrop(event, dateStr)}
          >
            <div className="schedule-list-date">
              <span className="schedule-list-weekday">
                {weekdayFormatter.format(date)}
              </span>
              <span className="schedule-list-day">
                {dateFormatter.format(date)}
              </span>
            </div>

            <div className="schedule-list-shifts">
              {dayShifts.map((shift) => {
                const color = competenceColor(shift.competence_id);
                return (
                  <div
                    key={shift.id}
                    className="schedule-list-shift"
                    style={{
                      borderLeftColor: color,
                      backgroundColor: `${color}26`,
                    }}
                    draggable
                    onDragStart={(event) => onDragStart(event, shift, dateStr)}
                    onClick={() => onShiftClick(shift)}
                    title={shift.competence_name || ''}
                  >
                    <span className="schedule-list-shift-name">
                      {shift.user_full_name || shift.user_email}
                    </span>
                    <button
                      type="button"
                      className="schedule-list-shift-remove"
                      onClick={(event) => {
                        event.stopPropagation();
                        onShiftRemove(shift.id);
                      }}
                      title={removeShiftLabel}
                    >
                      ×
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default ScheduleListView;
