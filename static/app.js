const form = document.getElementById('upload');
const summaryEl = document.getElementById('summary');
const issuesEl = document.getElementById('issues');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(form);
  const res = await fetch('/analyze', { method: 'POST', body: fd });
  if (!res.ok) {
    const err = await res.json().catch(()=>({error:'Upload failed'}));
    alert(err.error || 'Something went wrong');
    return;
  }
  const data = await res.json();

  summaryEl.innerHTML = `
    <div class="card">
      <h2>Summary</h2>
      <ul>
        <li>Segments: ${data.summary.segments}</li>
        <li>High: ${data.summary.high}</li>
        <li>Medium: ${data.summary.medium}</li>
        <li>Low: ${data.summary.low}</li>
      </ul>
    </div>
    <p><a href="/report/${data.run_id}">Open full HTML report</a></p>
  `;

  issuesEl.innerHTML = `<h2>Issues</h2>` + data.issues.map(it => `
    <div class="card ${it.severity}">
      <div><strong>[${it.severity.toUpperCase()}] ${it.type}</strong> — Segment ${it.segment}</div>
      <div><em>Source:</em> ${escapeHtml(it.src || '')}</div>
      <div><em>Target:</em> ${escapeHtml(it.tgt || '')}</div>
      ${it.detail ? `<pre>${escapeHtml(JSON.stringify(it.detail, null, 2))}</pre>` : ``}
    </div>
  `).join('');
});

function escapeHtml(s){return s.replace(/[&<>"']/g,m=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
