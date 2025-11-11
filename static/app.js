const form = document.getElementById('form');
const out = document.getElementById('out');
const dl = document.getElementById('download');
const progressBox = document.getElementById('progress');
const bar = document.getElementById('bar');
const plabel = document.getElementById('plabel');

function setProgress(pct, label) {
  progressBox.classList.remove('hidden');
  bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
  plabel.textContent = label || (pct + '%');
}
function hideProgress() {
  progressBox.classList.add('hidden');
  bar.style.width = '0%';
  plabel.textContent = '';
}

async function poll(runId) {
  let done = false;
  while (!done) {
    const r = await fetch(`/progress/${runId}`);
    const p = await r.json();
    setProgress(p.percent || 0, p.status || '');
    if ((p.status || '').startsWith('error')) {
      out.textContent = 'Analyze failed: ' + p.status;
      return null;
    }
    if ((p.status || '') === 'done' || (p.percent || 0) >= 100) {
      done = true;
      break;
    }
    await new Promise(res => setTimeout(res, 600));
  }
  const res = await fetch(`/result/${runId}`);
  if (!res.ok) { out.textContent = 'Failed to fetch result'; return null; }
  const data = await res.json();
  return data;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  out.textContent = '';
  dl.innerHTML = '';
  hideProgress();

  const fd = new FormData(form);
  try {
    // Start job
    const startRes = await fetch('/start', { method: 'POST', body: fd });
    const startData = await startRes.json();
    if (!startRes.ok) { out.textContent = startData.error || 'Start failed'; return; }

    const runId = startData.run_id;
    // Poll progress
    const data = await poll(runId);
    if (!data) return;

    out.textContent = 'Summary\n' + JSON.stringify(data.summary, null, 2) +
      '\n\nIssues\n' + JSON.stringify(data.issues, null, 2);

    const links = [];
    if (data.download) links.push(`<a class="button" href="${data.download}">Download highlighted translation (.docx)</a>`);
    if (data.edit_url) links.push(`<a class="button" href="${data.edit_url}">Edit & Fix in the app</a>`);
    dl.innerHTML = links.map(x => `<p>${x}</p>`).join("");

    hideProgress();
  } catch (err) {
    out.textContent = 'Request failed: ' + err.message;
    hideProgress();
  }
});
