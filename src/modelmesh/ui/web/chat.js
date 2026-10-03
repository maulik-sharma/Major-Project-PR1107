/**
 * ModelMesh Chat Client JavaScript Controller
 * Interacts with PyQt6 backend via QWebChannel
 */

let pyBridge = null;
let currentAssistantId = null;
let messageBuffers = {}; // msgId -> { text: '', reasoning: '', isStreaming: true }

// Configure marked with highlight.js
marked.setOptions({
  highlight: function(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch (err) {}
    }
    try {
      return hljs.highlightAuto(code).value;
    } catch (err) {}
    return code;
  },
  breaks: true,
  gfm: true
});

// Initialize Qt WebChannel
document.addEventListener('DOMContentLoaded', () => {
  if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
      pyBridge = channel.objects.pyBridge;
      window.pyBridge = pyBridge;
      if (pyBridge && pyBridge.on_ready) {
        pyBridge.on_ready();
      }
    });
  }
});

function scrollToBottom(force = false) {
  const threshold = 120;
  const isNearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - threshold;
  if (force || isNearBottom) {
    window.scrollTo({
      top: document.body.scrollHeight,
      behavior: 'smooth'
    });
  }
}

function hideEmptyState() {
  const emptyState = document.getElementById('empty-state');
  if (emptyState) {
    emptyState.style.display = 'none';
  }
}

function showEmptyState() {
  const emptyState = document.getElementById('empty-state');
  if (emptyState) {
    emptyState.style.display = 'flex';
  }
}

function onSuggestionClick(promptText) {
  if (pyBridge && pyBridge.on_suggestion_clicked) {
    pyBridge.on_suggestion_clicked(promptText);
  }
}

function copyTextToClipboard(text, btnElement) {
  navigator.clipboard.writeText(text).then(() => {
    if (btnElement) {
      const orig = btnElement.innerText;
      btnElement.innerText = 'Copied!';
      btnElement.style.borderColor = 'var(--accent-green)';
      btnElement.style.color = 'var(--accent-green)';
      setTimeout(() => {
        btnElement.innerText = orig;
        btnElement.style.borderColor = '';
        btnElement.style.color = '';
      }, 1500);
    }
  }).catch(err => {
    console.error('Failed to copy text:', err);
    if (pyBridge && pyBridge.on_copy) {
      pyBridge.on_copy(text);
    }
  });
}

function renderMarkdown(rawText) {
  const dirtyHtml = marked.parse(rawText);
  const cleanHtml = DOMPurify.sanitize(dirtyHtml);
  return cleanHtml;
}

function attachCodeCopyButtons(container) {
  const preElements = container.querySelectorAll('pre');
  preElements.forEach((pre) => {
    if (pre.querySelector('.code-header')) return;

    const codeEl = pre.querySelector('code');
    const rawCode = codeEl ? codeEl.innerText : pre.innerText;

    // Detect language class
    let lang = 'code';
    if (codeEl && codeEl.className) {
      const match = codeEl.className.match(/language-(\w+)/);
      if (match) lang = match[1];
    }

    const header = document.createElement('div');
    header.className = 'code-header';
    header.innerHTML = `<span>${lang}</span><button class="code-copy-btn">Copy</button>`;

    const copyBtn = header.querySelector('.code-copy-btn');
    copyBtn.addEventListener('click', () => copyTextToClipboard(rawCode, copyBtn));

    pre.insertBefore(header, pre.firstChild);
  });
}

/**
 * Add a User Message
 */
function add_user_message(msgId, text, parts = []) {
  hideEmptyState();
  const container = document.getElementById('chat-container');

  const row = document.createElement('div');
  row.className = 'message-row user-row';
  row.id = `msg-${msgId}`;

  let imagesHtml = '';
  if (parts && parts.length > 0) {
    parts.forEach(p => {
      if (p.media_type && p.data) {
        imagesHtml += `<img src="data:${p.media_type};base64,${p.data}" style="max-width:240px;max-height:180px;border-radius:8px;margin-bottom:8px;display:block;" />`;
      }
    });
  }

  const bubble = document.createElement('div');
  bubble.className = 'user-bubble';
  bubble.innerHTML = imagesHtml + DOMPurify.sanitize(text);

  row.appendChild(bubble);
  container.appendChild(row);
  scrollToBottom(true);
}

/**
 * Start Assistant Message
 */
function start_assistant_message(msgId, modelName = '', providerName = '', strategyName = '', reason = '') {
  hideEmptyState();
  currentAssistantId = msgId;
  messageBuffers[msgId] = { text: '', reasoning: '', isStreaming: true };

  const container = document.getElementById('chat-container');

  const row = document.createElement('div');
  row.className = 'message-row assistant-row';
  row.id = `msg-${msgId}`;

  // Reasoning / Thinking Box
  const thinkingBox = document.createElement('div');
  thinkingBox.className = 'thinking-box';
  thinkingBox.id = `thinking-${msgId}`;
  thinkingBox.style.display = 'none';
  thinkingBox.innerHTML = `
    <div class="thinking-header" onclick="toggleThinking('${msgId}')">
      <span>💭 Thinking Process</span>
    </div>
    <div class="thinking-content" id="thinking-content-${msgId}"></div>
  `;
  row.appendChild(thinkingBox);

  // Content Area
  const content = document.createElement('div');
  content.className = 'assistant-content';
  content.id = `content-${msgId}`;
  content.innerHTML = '<span class="streaming-cursor"></span>';
  row.appendChild(content);

  // Meta Footer
  const footer = document.createElement('div');
  footer.className = 'meta-footer';
  footer.id = `meta-${msgId}`;

  let chips = '';
  if (modelName) chips += `<span class="chip chip-model">🤖 ${modelName}</span>`;
  if (providerName) chips += `<span class="chip chip-provider">⚡ ${providerName}</span>`;
  if (strategyName) {
    const tooltip = reason ? ` title="${DOMPurify.sanitize(reason)}"` : '';
    chips += `<span class="chip chip-strategy"${tooltip}>🎯 ${strategyName}</span>`;
  }
  footer.innerHTML = chips;
  row.appendChild(footer);

  container.appendChild(row);
  scrollToBottom(true);
}

function toggleThinking(msgId) {
  const content = document.getElementById(`thinking-content-${msgId}`);
  if (content) {
    content.style.display = content.style.display === 'none' ? 'block' : 'none';
  }
}

/**
 * Append streamed text chunk
 */
function append_text_chunk(msgId, chunk) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  buf.text += chunk;

  const contentEl = document.getElementById(`content-${msgId}`);
  if (contentEl) {
    contentEl.innerHTML = renderMarkdown(buf.text) + (buf.isStreaming ? '<span class="streaming-cursor"></span>' : '');
    attachCodeCopyButtons(contentEl);
  }
  scrollToBottom(false);
}

/**
 * Append streamed reasoning chunk
 */
function append_reasoning_chunk(msgId, chunk) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  buf.reasoning += chunk;

  const thinkingBox = document.getElementById(`thinking-${msgId}`);
  const thinkingContent = document.getElementById(`thinking-content-${msgId}`);
  if (thinkingBox && thinkingContent) {
    thinkingBox.style.display = 'block';
    thinkingContent.innerText = buf.reasoning;
  }
  scrollToBottom(false);
}

/**
 * Show Failover Notice
 */
function show_fallback_notice(fromCandId, toCandId, reason = '') {
  const container = document.getElementById('chat-container');
  const banner = document.createElement('div');
  banner.className = 'fallback-banner';
  banner.innerHTML = `
    <span class="fallback-icon">⚡</span>
    <div>
      <strong>Failover:</strong> Endpoint <code>${fromCandId}</code> failed → Seamlessly falling back to <code>${toCandId}</code>
      ${reason ? `<div style="font-size:11px;opacity:0.85;margin-top:2px;">Reason: ${reason}</div>` : ''}
    </div>
  `;
  container.appendChild(banner);
  scrollToBottom(true);
}

/**
 * Add Tool Card
 */
function add_tool_card(msgId, toolId, toolName, argsJson = '{}') {
  const row = document.getElementById(`msg-${msgId}`);
  if (!row) return;

  const card = document.createElement('div');
  card.className = 'tool-card';
  card.id = `tool-${toolId}`;
  card.innerHTML = `
    <div class="tool-header">
      <span>🛠️ Tool Call: <strong>${toolName}</strong></span>
      <span style="font-size:11px;opacity:0.8;">Running...</span>
    </div>
    <div class="tool-body">${DOMPurify.sanitize(argsJson)}</div>
  `;

  // Insert before content element
  const contentEl = document.getElementById(`content-${msgId}`);
  if (contentEl) {
    row.insertBefore(card, contentEl);
  } else {
    row.appendChild(card);
  }
  scrollToBottom(false);
}

/**
 * Finish Assistant Message & Finalize Chips
 */
function finish_assistant_message(msgId, meta = {}) {
  const buf = messageBuffers[msgId];
  if (buf) {
    buf.isStreaming = false;
  }

  const contentEl = document.getElementById(`content-${msgId}`);
  if (contentEl && buf) {
    contentEl.innerHTML = renderMarkdown(buf.text);
    attachCodeCopyButtons(contentEl);
  }

  const footer = document.getElementById(`meta-${msgId}`);
  if (footer) {
    let chips = '';
    const model = meta.model_id || meta.model_name || '';
    const prov = meta.provider_id || meta.provider_name || '';
    const strat = meta.strategy || meta.strategy_name || '';
    const reason = meta.reason || '';

    if (model) chips += `<span class="chip chip-model">🤖 ${model}</span>`;
    if (prov) chips += `<span class="chip chip-provider">⚡ ${prov}</span>`;
    if (strat) {
      const tooltip = reason ? ` title="${DOMPurify.sanitize(reason)}"` : '';
      chips += `<span class="chip chip-strategy"${tooltip}>🎯 ${strat}</span>`;
    }

    if (meta.tokens_in !== undefined && meta.tokens_out !== undefined) {
      chips += `<span class="chip">📊 ${meta.tokens_in} in / ${meta.tokens_out} out</span>`;
    }
    if (meta.cost_usd !== undefined) {
      chips += `<span class="chip chip-cost">💰 $${Number(meta.cost_usd).toFixed(5)} est.</span>`;
    }
    if (meta.latency_sec !== undefined) {
      chips += `<span class="chip">⏱️ ${Number(meta.latency_sec).toFixed(2)}s</span>`;
    }

    chips += `<button class="action-btn" onclick="copyMessageText('${msgId}')" title="Copy reply">📋 Copy</button>`;
    chips += `<button class="action-btn" onclick="regenerateMessage('${msgId}')" title="Regenerate reply">🔄 Regenerate</button>`;

    footer.innerHTML = chips;
  }

  scrollToBottom(false);
}

function copyMessageText(msgId) {
  const buf = messageBuffers[msgId];
  if (buf && buf.text) {
    copyTextToClipboard(buf.text);
  }
}

function regenerateMessage(msgId) {
  if (pyBridge && pyBridge.on_regenerate) {
    pyBridge.on_regenerate(msgId);
  }
}

/**
 * Display Error Banner
 */
function set_error(msgId, errorMsg, category = 'unknown') {
  const row = document.getElementById(`msg-${msgId}`) || document.getElementById('chat-container');
  const errorBanner = document.createElement('div');
  errorBanner.className = 'error-banner';
  errorBanner.innerHTML = `
    <div class="error-title">⚠️ Error (${category})</div>
    <div>${DOMPurify.sanitize(errorMsg)}</div>
  `;
  row.appendChild(errorBanner);
  scrollToBottom(true);
}

/**
 * Clear Chat
 */
function clear_chat() {
  const container = document.getElementById('chat-container');
  if (container) {
    container.innerHTML = '';
  }
  messageBuffers = {};
  showEmptyState();
}

/**
 * Theme switch
 */
function set_theme(themeName) {
  if (themeName === 'light') {
    document.body.className = 'light-theme';
  } else {
    document.body.className = 'dark-theme';
  }
}
