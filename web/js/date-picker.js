// web/js/date-picker.js

let _days    = [];
let _daySet  = new Set();
let _onSelect = null;
let _currentDay = '';
let _viewYear  = 0;
let _viewMonth = 0;

const MONTHS = ['January','February','March','April','May','June',
                 'July','August','September','October','November','December'];

function _pad(n) { return String(n).padStart(2, '0'); }

function _hasDataBefore(y, m) {
  // Is there any day before the first day of (y, m)?
  const cutoff = `${y}-${_pad(m + 1)}-01`;
  return _days.length > 0 && _days[0] < cutoff;
}

function _hasDataAfter(y, m) {
  // Is there any day after the last day of (y, m)?
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const cutoff = `${y}-${_pad(m + 1)}-${_pad(daysInMonth)}`;
  return _days.length > 0 && _days[_days.length - 1] > cutoff;
}

function _renderGrid() {
  const label   = document.getElementById('dp-month-label');
  const grid    = document.getElementById('dp-grid');
  const prevY   = document.getElementById('dp-prev-year');
  const prevM   = document.getElementById('dp-prev-month');
  const nextM   = document.getElementById('dp-next-month');
  const nextY   = document.getElementById('dp-next-year');

  label.textContent = `${MONTHS[_viewMonth]} ${_viewYear}`;

  // Nav button disabled states
  const prevYearDis  = !_hasDataBefore(_viewYear, 0);
  const prevMonthDis = !_hasDataBefore(_viewYear, _viewMonth);
  const nextMonthDis = !_hasDataAfter(_viewYear, _viewMonth);
  const nextYearDis  = !_hasDataAfter(_viewYear, 11);

  prevY.disabled = prevYearDis;
  prevM.disabled = prevMonthDis;
  nextM.disabled = nextMonthDis;
  nextY.disabled = nextYearDis;

  // Build grid cells (keep the 7 weekday headers, replace day cells)
  const headers = Array.from(grid.querySelectorAll('.dp-wday'));
  grid.innerHTML = '';
  headers.forEach(h => grid.appendChild(h));

  // Weekday of the 1st
  const startDow    = new Date(_viewYear, _viewMonth, 1).getDay();
  const daysInMonth = new Date(_viewYear, _viewMonth + 1, 0).getDate();

  for (let i = 0; i < startDow; i++) {
    const blank = document.createElement('div');
    blank.className = 'dp-day dp-blank';
    grid.appendChild(blank);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${_viewYear}-${_pad(_viewMonth + 1)}-${_pad(d)}`;
    const cell    = document.createElement('div');
    cell.textContent = d;

    const isSelected  = dateStr === _currentDay;
    const isAvailable = _daySet.has(dateStr);

    if (isSelected) {
      cell.className = 'dp-day dp-selected';
    } else if (isAvailable) {
      cell.className = 'dp-day dp-available';
      cell.addEventListener('click', () => {
        closeDatePicker();
        _onSelect(dateStr);
      });
    } else {
      cell.className = 'dp-day dp-unavailable';
    }

    grid.appendChild(cell);
  }
}

function _navigate(deltaYear, deltaMonth) {
  let y = _viewYear;
  let m = _viewMonth + deltaMonth + deltaYear * 12;
  y += Math.floor(m / 12);
  m = ((m % 12) + 12) % 12;
  _viewYear  = y;
  _viewMonth = m;
  _renderGrid();
}

export function initDatePicker(days, onSelect) {
  _days     = days.slice().sort();
  _daySet   = new Set(_days);
  _onSelect = onSelect;

  // Wire nav buttons
  document.getElementById('dp-prev-year') .addEventListener('click', () => _navigate(-1, 0));
  document.getElementById('dp-prev-month').addEventListener('click', () => _navigate(0, -1));
  document.getElementById('dp-next-month').addEventListener('click', () => _navigate(0, 1));
  document.getElementById('dp-next-year') .addEventListener('click', () => _navigate(1, 0));

  // Close on backdrop click
  document.getElementById('date-picker').addEventListener('click', e => {
    if (e.target === document.getElementById('date-picker')) closeDatePicker();
  });
}

export function openDatePicker(currentDay) {
  _currentDay = currentDay;
  const [y, m] = currentDay.split('-').map(Number);
  _viewYear  = y;
  _viewMonth = m - 1;
  _renderGrid();
  const el = document.getElementById('date-picker');
  el.style.display = 'flex';
}

export function closeDatePicker() {
  document.getElementById('date-picker').style.display = 'none';
}

export function updatePickerCurrentDay(dateStr) {
  _currentDay = dateStr;
}
