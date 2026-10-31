/**
 * ModelMesh chat: tool cards, routing notices, message footer and insights panel.
 * Every value that came from a model, tool, provider or config goes through escapeHtml.
 */

const toolCards = {}; // `${msgId}\u0000${toolId}` -> { card, status, body, done }

const SOURCE_BADGES = {
  clef: ['badge-source', 'Clef', 'Routing decided by the Clef decision model'],
  cache: ['badge-source', 'Cached', 'Routing decision served from the local decision cache'],
  heuristic: ['badge-source', 'Heuristic', 'Routing decided by the local heuristic'],
  heuristic_fallback: ['badge-warning', 'Heuristic fallback', 'Decision service unavailable; the local heuristic decided instead'],
  mock: ['badge-source', 'Mock', 'Deterministic mock decision provider'],
};

const STRATEGY_LABELS = {
  smart_clef: 'Auto · Smart',
  cheapest_first: 'Cheapest first',
  expensive_first: 'Strongest first',
  random: 'Random',
  manual: 'Manual',
};

function fmtNum(val, digits = 2) {
  return (val === null || val === undefined || isNaN(Number(val))) ? '-' : Number(val).toFixed(digits);
}

function messageRow(msgId) {
  return document.getElementById(`msg-${msgId}`);
}

/**
 * Footer items shared by the streaming and finished states.
 */
function buildFooterItems(meta) {
  const routing = meta.metadata || {};
  const items = [];
  const model = meta.model_id || meta.model_name || '';
  const prov = meta.provider_id || meta.provider_name || '';
  const stratKey = meta.strategy || meta.strategy_name || routing.strategy || '';
  const strat = STRATEGY_LABELS[stratKey] || stratKey;
  const reason = meta.reason || routing.reason || '';

  if (model) items.push(`<span>${escapeHtml(model)}</span>`);
  if (prov) items.push(`<span>${escapeHtml(prov)}</span>`);
  if (strat) items.push(`<span title="${escapeHtml(reason)}">${escapeHtml(strat)}</span>`);

  const badge = SOURCE_BADGES[routing.decision_source];
  if (badge) {
    items.push(`<span class="badge ${badge[0]}" title="${escapeHtml(badge[2])}">${escapeHtml(badge[1])}</span>`);
  }
  return items;
}

/**
 * Visible routing notices for a message: heuristic fallback (Rule 17), below-bar
 * fallback, and selector notices (e.g. no scored models). Re-rendered on finish.
 */
function renderRoutingNotices(msgId, routing) {
  const row = messageRow(msgId);
  if (!row || !routing) return;
  const lines = [];
  if (routing.decision_source === 'heuristic_fallback') {
    const why = routing.decision_error ? ` (${routing.decision_error})` : '';
    lines.push(`Smart routing's decision service was unavailable${why}; the local heuristic chose the model instead.`);
  }
  if (routing.below_bar) {
    lines.push('Answered by a lower-tier fallback model.');
  }
  (routing.notices || []).forEach(n => lines.push(n));

  let box = document.getElementById(`notices-${msgId}`);
  if (!lines.length) {
    if (box) box.remove();
    return;
  }
  if (!box) {
    box = document.createElement('div');
    box.className = 'fallback-banner routing-notices';
    box.id = `notices-${msgId}`;
    const contentEl = document.getElementById(`content-${msgId}`);
    row.insertBefore(box, contentEl || null);
  }
  box.innerHTML = '<span class="fallback-tag">Routing</span>' +
    lines.map(l => `<span>${escapeHtml(l)}</span>`).join('<br/>');
}

/**
 * Failover between candidates within the current reply.
 */
function show_fallback_notice(fromCandId, toCandId, reason = '') {
  const row = currentAssistantId ? messageRow(currentAssistantId) : null;
  const target = row || document.getElementById('chat-container');
  if (!target) return;
  const banner = document.createElement('div');
  banner.className = 'fallback-banner';
  banner.innerHTML = `
    <span class="fallback-tag">Failover</span>
    <span>Switched from <code>${escapeHtml(fromCandId)}</code> to <code>${escapeHtml(toCandId)}</code>${reason ? ` (${escapeHtml(reason)})` : ''}</span>
  `;
  const contentEl = row ? document.getElementById(`content-${currentAssistantId}`) : null;
  target.insertBefore(banner, contentEl || null);
  scrollToBottom(true);
}

function toolKey(msgId, toolId) {
  return `${msgId}\u0000${toolId || ''}`;
}

/**
 * Add a tool card. Cards are keyed per message, so reused or empty tool ids
 * from a provider never update another message's card.
 */
function add_tool_card(msgId, toolId, toolName, argsJson = '{}') {
  const row = messageRow(msgId);
  if (!row) return;
  const key = toolKey(msgId, toolId);
  let entry = toolCards[key];
  if (!entry || entry.done) {
    const card = document.createElement('div');
    card.className = 'tool-card open';
    const contentEl = document.getElementById(`content-${msgId}`);
    row.insertBefore(card, contentEl || null);
    entry = { card, done: false };
    toolCards[key] = entry;
  }

  entry.card.innerHTML = `
    <div class="tool-header">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="tool-chevron">›</span>
        <span>Tool: <strong>${escapeHtml(toolName)}</strong></span>
      </div>
      <span class="tool-status running">Running...</span>
    </div>
    <div class="tool-body">
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Arguments:</div>
      <pre style="margin:0;padding:6px;background:var(--code-bg);border:none;"><code>${escapeHtml(argsJson)}</code></pre>
    </div>
  `;
  entry.card.querySelector('.tool-header').addEventListener('click', () => entry.card.classList.toggle('open'));
  entry.status = entry.card.querySelector('.tool-status');
  entry.body = entry.card.querySelector('.tool-body');
  scrollToBottom(false);
}

function update_tool_result(msgId, toolId, toolName, resultStr, errorStr, success = true, durationMs = 0) {
  const entry = toolCards[toolKey(msgId, toolId)];
  if (!entry || entry.done) return;
  entry.done = true;

  entry.status.className = success ? 'tool-status success' : 'tool-status error';
  entry.status.textContent = `${success ? 'Success' : 'Failed'} (${Number(durationMs) || 0}ms)`;

  const outcome = document.createElement('div');
  outcome.style.marginTop = '8px';
  outcome.style.borderTop = '1px solid var(--border-color)';
  outcome.style.paddingTop = '6px';
  if (success) {
    outcome.innerHTML = `
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Result:</div>
      <pre style="margin:0;padding:6px;background:var(--code-bg);border:none;max-height:180px;overflow:auto;"><code>${escapeHtml(resultStr)}</code></pre>
    `;
  } else {
    outcome.innerHTML = `
      <div class="tool-error-label" style="font-size:11px;margin-bottom:4px;">Error:</div>
      <div class="tool-error-text" style="font-size:12px;">${escapeHtml(errorStr)}</div>
    `;
  }
  entry.body.appendChild(outcome);
}

function buildInsightsHtml(meta) {
  const r = meta.metadata || {};
  const badge = SOURCE_BADGES[r.decision_source];
  const source = badge ? badge[1] : (r.decision_source || '-');
  const latency = r.router_latency_ms !== undefined && r.router_latency_ms !== null
    ? `${fmtNum(r.router_latency_ms, 0)} ms` : '-';

  const cards = [
    ['Task', r.task || '-'],
    ['Difficulty', `${fmtNum(r.difficulty)}/4`],
    ['Precision', `${fmtNum(r.precision)}/3`],
    ['Need / Bar', `${fmtNum(r.need)} / ${fmtNum(r.bar)}`],
    ['Metric', r.metric_used || 'none'],
    ['Quality (q)', fmtNum(r.chosen_q)],
  ].map(([label, value]) => `
      <div class="insights-card">
        <div class="insights-card-label">${escapeHtml(label)}</div>
        <div class="insights-card-value">${escapeHtml(value)}</div>
      </div>`).join('');

  let table = '';
  if (Array.isArray(r.candidates) && r.candidates.length) {
    const rows = r.candidates.map(c => {
      const chosen = c.model_id === meta.model_id;
      const status = chosen ? '✓ Selected' : (c.admitted ? 'Admitted' : 'Below bar');
      return `<tr class="${chosen ? 'chosen-row' : ''}"><td>${escapeHtml(c.model_id)}</td>` +
        `<td>${escapeHtml(fmtNum(c.q))}</td><td>${escapeHtml(status)}</td></tr>`;
    }).join('');
    table = `
      <div class="insights-section-label">Evaluated Candidates</div>
      <table class="insights-table">
        <thead><tr><th>Model</th><th>Quality (q)</th><th>Status</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  const extra = [];
  if (r.stickiness_outcome) extra.push(`Stickiness: ${r.stickiness_outcome}`);
  if (r.profile) extra.push(`Profile: ${r.profile}`);

  return `
    <div class="insights-header">
      <span>⚡ Smart Routing Insights</span>
      <span class="insights-subtle">${escapeHtml(source)} · ${escapeHtml(latency)}</span>
    </div>
    <div class="insights-grid">${cards}</div>
    ${extra.length ? `<div class="insights-subtle">${escapeHtml(extra.join(' · '))}</div>` : ''}
    ${table}
    <div class="insights-attribution">Model scores: Artificial Analysis</div>
  `;
}

function toggleInsights(msgId) {
  const panel = document.getElementById(`insights-${msgId}`);
  if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

/**
 * Rebuild the footer when a reply finishes (or stops/fails) and attach actions.
 */
function renderFinishedFooter(msgId, meta) {
  const footer = document.getElementById(`meta-${msgId}`);
  const row = messageRow(msgId);
  if (!footer || !row) return;
  const r = meta.metadata || {};
  const items = buildFooterItems(meta);

  if (meta.latency_sec !== undefined) items.push(`<span>${fmtNum(meta.latency_sec)}s</span>`);
  if (meta.cost_usd !== undefined && Number(meta.cost_usd) > 0) items.push(`<span>$${fmtNum(meta.cost_usd, 5)}</span>`);
  if (meta.tokens_in !== undefined && meta.tokens_out !== undefined) {
    items.push(`<span>${Number(meta.tokens_in) || 0} in / ${Number(meta.tokens_out) || 0} out</span>`);
  }
  if (meta.stopped) items.push('<span class="badge badge-warning">Stopped</span>');

  footer.innerHTML = items.join('<span class="meta-separator">·</span>') +
    '<span class="meta-separator" style="margin: 0 4px;"></span>';

  const hasInsights = r.strategy === 'smart_clef' && r.need !== undefined && r.need !== null;
  const addButton = (cls, label, title, handler) => {
    const btn = document.createElement('button');
    btn.className = cls;
    btn.textContent = label;
    btn.title = title;
    btn.addEventListener('click', handler);
    footer.appendChild(btn);
  };
  if (hasInsights) addButton('insights-btn', '⚡ Insights', 'Toggle Smart Routing Insights', () => toggleInsights(msgId));
  addButton('action-btn', 'Copy', 'Copy reply', () => copyMessageText(msgId));
  addButton('action-btn', 'Retry', 'Retry generation', () => regenerateMessage(msgId));

  let panel = document.getElementById(`insights-${msgId}`);
  if (hasInsights) {
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'insights-panel';
      panel.id = `insights-${msgId}`;
      panel.style.display = 'none';
      row.appendChild(panel);
    }
    panel.innerHTML = buildInsightsHtml(meta);
  } else if (panel) {
    panel.remove();
  }
  renderRoutingNotices(msgId, r);
}

/**
 * Display an error banner (message text is shown as plain text).
 */
function set_error(msgId, errorMsg, category = 'unknown') {
  const row = messageRow(msgId) || document.getElementById('chat-container');
  if (!row) return;
  const banner = document.createElement('div');
  banner.className = 'error-banner';
  const title = document.createElement('div');
  title.style.fontWeight = '600';
  title.style.marginBottom = '2px';
  title.textContent = `Error (${category})`;
  const body = document.createElement('div');
  body.textContent = errorMsg;
  banner.append(title, body);
  row.appendChild(banner);
  scrollToBottom(true);
}

window.show_fallback_notice = show_fallback_notice;
window.add_tool_card = add_tool_card;
window.update_tool_result = update_tool_result;
window.set_error = set_error;
window.toggleInsights = toggleInsights;
