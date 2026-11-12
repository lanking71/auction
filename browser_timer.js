// This function body is executed by WebDriver with (action, options).
// Receipts are written BEFORE click so navigation cannot turn an uncertain
// command response into permission to submit again.
const action = arguments[0], o = arguments[1];
const page = String(performance.timeOrigin);
const key = 'aucton.bid.' + o.id;
window.__auctonTimers = window.__auctonTimers || Object.create(null);
const timers = window.__auctonTimers;
function save(t) {
  const copy = Object.assign({}, t); delete copy.handle; delete copy.button;
  sessionStorage.setItem(key, JSON.stringify(copy));
  return copy;
}
function read() {
  return timers[o.id] || JSON.parse(sessionStorage.getItem(key) || 'null');
}
if (action === 'clock') return {page:page, now:performance.now()};
if (action === 'arm') {
  const old = read();
  if (old) {
    if (old.state === 'armed' && (old.page !== page || !timers[o.id]))
      return {state:'unknown', error:'page_changed', page:old.page};
    return save(old); // Same ID can never schedule a second click.
  }
  if (o.page !== page) return {state:'not_armed', error:'page_changed'};
  const button = document.querySelector(o.selector || 'input#buttonBid');
  if (!button || button.disabled) return {state:'not_armed', error:'button_unavailable'};
  if (!Number.isFinite(o.target) || o.target <= performance.now())
    return {state:'expired', page:page};
  const t = {id:o.id, page:page, target:o.target, state:'armed', enabled:false,
             late_limit:o.late_limit, armed:performance.now(), button:button};
  timers[o.id] = t;
  save(t); // Fail before scheduling if durable receipt storage is unavailable.
  function tick() {
    if (t.state !== 'armed') return;
    let remaining = t.target - performance.now();
    if (remaining > 2) {
      t.handle = setTimeout(tick, Math.max(0, remaining - 2)); return;
    }
    t.callback = performance.now();
    // No event-loop cancellation can execute inside this final <=2ms span.
    while (performance.now() < t.target) {}
    if (t.state !== 'armed') return;
    if (!t.enabled || performance.now() - t.target > t.late_limit) {
      t.state = 'expired'; t.expired = performance.now();
      t.error = !t.enabled ? 'not_enabled_before_deadline' : 'late_fire';
      save(t); return;
    }
    if (!t.button.isConnected || t.button.disabled) {
      t.state = 'failed'; t.error = 'button_detached'; save(t); return;
    }
    t.state = 'fired'; t.fired = performance.now();
    save(t); // Never retry once this transition has occurred.
    try {
      t.clicked = performance.now();
      t.button.click();
    } catch (e) {
      t.state = 'unknown'; t.error = 'click_exception';
    }
    save(t);
  }
  t.handle = setTimeout(tick, Math.max(0, t.target - performance.now() - 20));
  return save(t); // Immediate arm acknowledgement, not click completion.
}
const t = read();
if (!t) return {state:'missing', page:page};
if (t.state === 'armed' && (t.page !== page || !timers[o.id]))
  return {state:'unknown', error:'page_changed', page:t.page};
if (action === 'cancel') {
  if (t.state === 'armed' && t.page === page && timers[o.id]) {
    clearTimeout(t.handle); t.state = 'cancelled'; t.cancelled = performance.now();
    return save(t);
  }
  return save(t);
}
if (action === 'enable') {
  if (t.page !== page || !timers[o.id]) return {state:'unknown', error:'page_changed'};
  if (t.state === 'armed') {
    t.enabled = true; t.enabled_at = performance.now(); return save(t);
  }
}
return save(t);
