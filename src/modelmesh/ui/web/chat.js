/**
 * ModelMesh Chat Client JavaScript Controller
 * Interacts with PyQt6 backend via QWebChannel
 */

let pyBridge = null;
let currentAssistantId = null;
let messageBuffers = {}; // msgId -> { text: '', reasoning: '', isStreaming: true }

// Initialize Qt WebChannel
document.addEventListener('DOMContentLoaded', () => {
  if (typeof QWebChannel !== 'undefined') {
    try {
      new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.pyBridge;
        window.pyBridge = pyBridge;
        if (pyBridge && pyBridge.on_ready) {
          pyBridge.on_ready();
        }
      });
    } catch (err) {
      console.error('QWebChannel initialization error:', err);
    }
  }
});

// Configure marked options
if (typeof marked !== 'undefined' && marked.setOptions) {
  marked.setOptions({
    breaks: true,
    gfm: true,
    headerIds: false,
    mangle: false,
  });
}

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
    if (pyBridge && pyBridge.on_copy) {
      pyBridge.on_copy(text);
    }
  });
}

/**
 * Resilient markdown parser with streaming code-fence auto-completion
 */
function renderMarkdown(rawText, isStreaming = false) {
  if (!rawText) return '';
  try {
    let textToParse = rawText;

    // Resilient fix for unclosed code fence while streaming
    if (isStreaming) {
      const codeFenceMatches = textToParse.match(/```/g);
      if (codeFenceMatches && codeFenceMatches.length % 2 !== 0) {
        textToParse += '\n```';
      }
    }

    if (typeof marked !== 'undefined' && marked.parse) {
      const parsed = marked.parse(textToParse);
      if (typeof DOMPurify !== 'undefined' && DOMPurify.sanitize) {
        return DOMPurify.sanitize(parsed, {
          ADD_ATTR: ['target', 'class', 'style'],
          ADD_TAGS: ['span', 'code', 'pre', 'img', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'ul', 'ol', 'li', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'strong', 'em', 'del', 'a']
        });
      }
      return parsed;
    }
  } catch (err) {
    console.error('Markdown rendering error:', err);
  }
  return rawText;
}

function attachCodeCopyButtons(container) {
  if (!container) return;
  const preElements = container.querySelectorAll('pre');
  preElements.forEach((pre) => {
    const codeEl = pre.querySelector('code');
    if (codeEl && typeof hljs !== 'undefined' && !codeEl.dataset.highlighted) {
      try {
        hljs.highlightElement(codeEl);
        codeEl.dataset.highlighted = 'yes';
      } catch (e) {}
    }

    if (pre.querySelector('.code-header')) return;

    const rawCode = codeEl ? codeEl.innerText : pre.innerText;

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
 * Extract reasoning from <thought> / <think> tags and separate from visible response
 */
function extractThinkingAndContent(rawText, explicitReasoning = '') {
  let reasoning = explicitReasoning || '';
  let content = rawText || '';

  // Extract closed <thought>...</thought> or <think>...</think>
  const fullTagRegex = /<(?:thought|think)>([\s\S]*?)<\/(?:thought|think)>/gi;
  let match;
  while ((match = fullTagRegex.exec(content)) !== null) {
    const thoughtText = match[1].trim();
    if (thoughtText) {
      reasoning = reasoning ? (reasoning + '\n\n' + thoughtText) : thoughtText;
    }
  }
  content = content.replace(fullTagRegex, '').trimStart();

  // Extract unclosed <thought> or <think> (e.g. streaming in progress)
  const openTagMatch = content.match(/<(?:thought|think)>([\s\S]*)$/i);
  if (openTagMatch) {
    const unclosedThought = openTagMatch[1];
    if (unclosedThought) {
      reasoning = reasoning ? (reasoning + '\n\n' + unclosedThought) : unclosedThought;
    }
    content = content.substring(0, openTagMatch.index).trim();
  }

  return { reasoning, content };
}

/**
 * Update message thought disclosure and assistant body
 */
function updateMessageDisplay(msgId) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  const { reasoning, content } = extractThinkingAndContent(buf.text, buf.reasoning);

  // Update Thinking Box
  const thinkingBox = document.getElementById(`thinking-${msgId}`);
  const thinkingContent = document.getElementById(`thinking-content-${msgId}`);
  if (thinkingBox && thinkingContent) {
    if (reasoning && reasoning.trim()) {
      thinkingBox.style.display = 'block';
      thinkingContent.innerHTML = renderMarkdown(reasoning, buf.isStreaming);
      attachCodeCopyButtons(thinkingContent);
    } else {
      thinkingBox.style.display = 'none';
    }
  }

  // Update Main Assistant Content
  const contentEl = document.getElementById(`content-${msgId}`);
  if (contentEl) {
    if (content || !buf.isStreaming) {
      contentEl.innerHTML = renderMarkdown(content, buf.isStreaming) + (buf.isStreaming ? '<span class="streaming-cursor"></span>' : '');
    } else {
      contentEl.innerHTML = '<span class="streaming-cursor"></span>';
    }
    attachCodeCopyButtons(contentEl);
  }
}

/**
 * Add a User Message
 */
function add_user_message(msgId, text, parts = []) {
  hideEmptyState();
  const container = document.getElementById('chat-container');
  if (!container) return;

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
  const cleanText = (typeof DOMPurify !== 'undefined' && DOMPurify.sanitize) ? DOMPurify.sanitize(text) : text;
  bubble.innerHTML = imagesHtml + cleanText;

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
  if (!container) return;

  const row = document.createElement('div');
  row.className = 'message-row assistant-row';
  row.id = `msg-${msgId}`;

  // Thought Process Disclosure (Claude-like minimal disclosure)
  const thoughtBox = document.createElement('div');
  thoughtBox.className = 'thought-box';
  thoughtBox.id = `thinking-${msgId}`;
  thoughtBox.style.display = 'none';
  thoughtBox.innerHTML = `
    <div class="thought-summary" onclick="toggleThinking('${msgId}')">
      <span class="thought-chevron">›</span>
      <span>Thought process</span>
    </div>
    <div class="thought-content" id="thinking-content-${msgId}"></div>
  `;
  row.appendChild(thoughtBox);

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

  let items = [];
  if (modelName) items.push(`<span>${modelName}</span>`);
  if (providerName) items.push(`<span>${providerName}</span>`);
  if (strategyName) {
    const tooltip = reason ? ` title="${reason.replace(/"/g, '&quot;')}"` : '';
    items.push(`<span${tooltip}>${strategyName}</span>`);
  }
  footer.innerHTML = items.join('<span class="meta-separator">·</span>');
  row.appendChild(footer);

  container.appendChild(row);
  scrollToBottom(true);
}

function toggleThinking(msgId) {
  const box = document.getElementById(`thinking-${msgId}`);
  if (box) {
    box.classList.toggle('open');
  }
}

/**
 * Append streamed text chunk
 */
function append_text_chunk(msgId, chunk) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  buf.text += chunk;
  updateMessageDisplay(msgId);
  scrollToBottom(false);
}

/**
 * Append streamed reasoning chunk
 */
function append_reasoning_chunk(msgId, chunk) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  buf.reasoning += chunk;
  updateMessageDisplay(msgId);
  scrollToBottom(false);
}

/**
 * Show Failover Notice
 */
function show_fallback_notice(fromCandId, toCandId, reason = '') {
  const container = document.getElementById('chat-container');
  if (!container) return;
  const banner = document.createElement('div');
  banner.className = 'fallback-banner';
  banner.innerHTML = `
    <span class="fallback-tag">Failover</span>
    <span>Switched from <code>${fromCandId}</code> to <code>${toCandId}</code>${reason ? ` (${reason})` : ''}</span>
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
      <span>Tool Call: <strong>${toolName}</strong></span>
      <span style="font-size:11px;opacity:0.7;">Executed</span>
    </div>
    <div class="tool-body">${argsJson}</div>
  `;

  const contentEl = document.getElementById(`content-${msgId}`);
  if (contentEl) {
    row.insertBefore(card, contentEl);
  } else {
    row.appendChild(card);
  }
  scrollToBottom(false);
}

/**
 * Finish Assistant Message & Finalize Metadata
 */
function finish_assistant_message(msgId, meta = {}) {
  const buf = messageBuffers[msgId];
  if (buf) {
    buf.isStreaming = false;
    updateMessageDisplay(msgId);
  }

  const footer = document.getElementById(`meta-${msgId}`);
  if (footer) {
    let items = [];
    const model = meta.model_id || meta.model_name || '';
    const prov = meta.provider_id || meta.provider_name || '';
    const strat = meta.strategy || meta.strategy_name || '';
    const reason = meta.reason || '';

    if (model) items.push(`<span>${model}</span>`);
    if (prov) items.push(`<span>${prov}</span>`);
    if (strat) {
      const tooltip = reason ? ` title="${reason.replace(/"/g, '&quot;')}"` : '';
      items.push(`<span${tooltip}>${strat}</span>`);
    }

    if (meta.latency_sec !== undefined) {
      items.push(`<span>${Number(meta.latency_sec).toFixed(2)}s</span>`);
    }
    if (meta.cost_usd !== undefined && Number(meta.cost_usd) > 0) {
      items.push(`<span>$${Number(meta.cost_usd).toFixed(5)}</span>`);
    }
    if (meta.tokens_in !== undefined && meta.tokens_out !== undefined) {
      items.push(`<span>${meta.tokens_in} in / ${meta.tokens_out} out</span>`);
    }

    let metaHtml = items.join('<span class="meta-separator">·</span>');
    metaHtml += `
      <span class="meta-separator" style="margin: 0 4px;"></span>
      <button class="action-btn" onclick="copyMessageText('${msgId}')" title="Copy reply">Copy</button>
      <button class="action-btn" onclick="regenerateMessage('${msgId}')" title="Retry generation">Retry</button>
    `;

    footer.innerHTML = metaHtml;
  }

  scrollToBottom(false);
}

function copyMessageText(msgId) {
  const buf = messageBuffers[msgId];
  if (buf) {
    const { content } = extractThinkingAndContent(buf.text, buf.reasoning);
    copyTextToClipboard(content || buf.text);
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
  if (!row) return;
  const errorBanner = document.createElement('div');
  errorBanner.className = 'error-banner';
  errorBanner.innerHTML = `
    <div style="font-weight:600;margin-bottom:2px;">Error (${category})</div>
    <div>${errorMsg}</div>
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

// Global window exposures
window.add_user_message = add_user_message;
window.start_assistant_message = start_assistant_message;
window.append_text_chunk = append_text_chunk;
window.append_reasoning_chunk = append_reasoning_chunk;
window.show_fallback_notice = show_fallback_notice;
window.add_tool_card = add_tool_card;
window.finish_assistant_message = finish_assistant_message;
window.set_error = set_error;
window.clear_chat = clear_chat;
window.set_theme = set_theme;
window.onSuggestionClick = onSuggestionClick;
window.toggleThinking = toggleThinking;
window.copyMessageText = copyMessageText;
window.regenerateMessage = regenerateMessage;
