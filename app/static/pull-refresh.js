// A deliberate pull at the top refreshes mobile pages. Recipe forms stay intact.
(() => {
  if (!matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints < 1) return;

  document.documentElement.classList.add('pull-refresh-enabled');
  const indicator = document.createElement('div');
  indicator.className = 'pull-refresh';
  indicator.hidden = true;
  indicator.setAttribute('role', 'status');
  indicator.setAttribute('aria-live', 'polite');
  indicator.innerHTML = '<span class="pull-refresh-icon" aria-hidden="true">↓</span><span class="pull-refresh-label"></span>';
  document.body.prepend(indicator);
  const label = indicator.querySelector('.pull-refresh-label');
  const threshold = 64;
  let gesture = null;
  let refreshing = false;

  function reset() {
    gesture = null;
    if (!refreshing) {
      indicator.hidden = true;
      indicator.classList.remove('ready');
      label.textContent = '';
    }
  }

  function blocked(target) {
    if (document.querySelector('#edit-form')) return true;
    if (target.closest('input, textarea, select, button, a, form, [contenteditable]')) return true;
    if (document.activeElement?.matches('input, textarea, select, [contenteditable]')) return true;
    if (window.visualViewport && window.visualViewport.scale !== 1) return true;
    for (let node = target; node && node !== document.body; node = node.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) return true;
    }
    return false;
  }

  document.addEventListener('touchstart', event => {
    reset();
    if (refreshing || event.touches.length !== 1 || window.scrollY > 0 || blocked(event.target)) return;
    const touch = event.touches[0];
    gesture = {id: touch.identifier, x: touch.clientX, y: touch.clientY, distance: 0, engaged: false};
  }, {passive: true});

  document.addEventListener('touchmove', event => {
    if (!gesture) return;
    if (event.touches.length !== 1 || window.scrollY > 0 || document.querySelector('#edit-form')) return reset();
    const touch = event.touches[0];
    const dy = touch.clientY - gesture.y;
    const dx = Math.abs(touch.clientX - gesture.x);
    if (touch.identifier !== gesture.id || dy < 0 || dx > Math.max(16, dy)) return reset();
    if (dy < 8) {
      if (gesture.engaged && event.cancelable) event.preventDefault();
      gesture.distance = 0;
      indicator.hidden = true;
      indicator.classList.remove('ready');
      return;
    }
    if (!event.cancelable) return reset();
    event.preventDefault();
    gesture.engaged = true;
    gesture.distance = Math.min(92, dy * .5);
    const ready = gesture.distance >= threshold;
    indicator.style.setProperty('--pull-distance', `${gesture.distance}px`);
    indicator.hidden = false;
    indicator.classList.toggle('ready', ready);
    const text = ready ? 'Loslassen zum Aktualisieren' : 'Zum Aktualisieren ziehen';
    if (label.textContent !== text) label.textContent = text;
  }, {passive: false});

  document.addEventListener('touchend', event => {
    if (!gesture) return;
    if (event.touches.length || gesture.distance < threshold || document.querySelector('#edit-form')) return reset();
    refreshing = true;
    gesture = null;
    indicator.classList.add('refreshing');
    indicator.style.setProperty('--pull-distance', `${threshold}px`);
    label.textContent = 'Wird aktualisiert…';
    // Let the browser paint the feedback before navigating.
    setTimeout(() => location.reload(), 120);
  }, {passive: true});
  document.addEventListener('touchcancel', reset, {passive: true});
  window.addEventListener('pagehide', reset);
})();
