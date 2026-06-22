document.querySelectorAll('[data-toggle-form]').forEach((form) => {
  const checkbox = form.querySelector('input[type="checkbox"]');
  const wrap = form.closest('#item-' + form.action.split('/').filter(Boolean).pop()) || form.closest('[id^="item-"]');
  const label = form.querySelector('[data-availability-label]');
  if (!checkbox) return;

  checkbox.addEventListener('change', async (event) => {
    event.preventDefault();
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    checkbox.disabled = true;
    try {
      const res = await fetch(form.action, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrf,
          'X-Requested-With': 'XMLHttpRequest',
        },
        credentials: 'same-origin',
      });
      if (!res.ok) {
        if (res.status === 409) {
          const data = await res.json();
          window.alert(data.message);
        } else {
          throw new Error('Toggle failed');
        }
        checkbox.checked = !checkbox.checked;
        return;
      }
      const data = await res.json();
      checkbox.checked = !!data.is_available;
      if (label) label.textContent = data.is_available ? 'Live' : 'Off';
      if (wrap) wrap.style.opacity = data.is_available ? '1' : '.65';
    } catch (error) {
      checkbox.checked = !checkbox.checked;
      window.alert('Could not update item availability.');
    } finally {
      checkbox.disabled = false;
    }
  });
});
