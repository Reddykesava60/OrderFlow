document.querySelectorAll('[data-permission-toggle]').forEach((form) => {
  const checkbox = form.querySelector('input[type="checkbox"]');
  if (!checkbox) return;

  checkbox.addEventListener('change', async (event) => {
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    const permission = form.querySelector('[name=permission]').value;
    
    checkbox.disabled = true;
    
    const formData = new FormData();
    formData.append('csrfmiddlewaretoken', csrf);
    formData.append('permission', permission);

    try {
      const res = await fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
        },
        credentials: 'same-origin',
      });
      
      if (!res.ok) throw new Error('Update failed');
      
      const data = await res.json();
      checkbox.checked = !!data.value;
    } catch (error) {
      checkbox.checked = !checkbox.checked;
      window.alert('Could not update permission.');
    } finally {
      checkbox.disabled = false;
    }
  });
});
