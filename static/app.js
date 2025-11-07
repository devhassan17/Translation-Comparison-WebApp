const form = document.getElementById('form');
const out = document.getElementById('out');
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  out.textContent = 'Uploading & analyzing...';
  const fd = new FormData(form);
  try {
    const res = await fetch('/analyze', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { out.textContent = data.error || 'Error'; return; }
    out.textContent = 'Summary\n' + JSON.stringify(data.summary, null, 2) +
      '\n\nIssues\n' + JSON.stringify(data.issues, null, 2);
  } catch (err) {
    out.textContent = 'Request failed: ' + err.message;
  }
});
