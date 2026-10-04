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

const REASONING_TAG_NAMES = ['thought', 'think', 'reasoning', 'reflection', 'scratchpad'];

const TRANSITION_PATTERNS = [
  /\n\s*(?:---|===|\*\*\*)\s*\n+/i,
  /\n\s*(?:Here is (?:the|my) (?:response|answer|evaluation|score|summary|analysis|review|breakdown)|Let's write (?:the|a) (?:response|answer)|I will format (?:the|my) (?:output|response)|Final (?:Response|Answer|Verdict|Evaluation|Score):|Response:|Answer:)\s*[:\n]+/i,
  /\n\s*(?:#{1,4}\s+|\*\*(?:ATS Score|Executive Summary|Summary|Evaluation|Overview|Verdict|Final|Result|Score|Answer|Solution|Breakdown))/i
];

function findTransitionSplit(text) {
  if (!text) return -1;
  for (let i = 0; i < TRANSITION_PATTERNS.length; i++) {
    const match = TRANSITION_PATTERNS[i].exec(text);
    if (match && (match.index > 20 || match[0].includes('---') || match[0].includes('==='))) {
      return match.index;
    }
  }
  return -1;
}

/**
 * Robust extraction of reasoning/scratchpad notes vs user-facing content
 */
function extractThinkingAndContent(rawText, explicitReasoning = '', isStreaming = false) {
  let reasoningParts = [];
  if (explicitReasoning && explicitReasoning.trim()) {
    reasoningParts.push(explicitReasoning.trim());
  }
  let content = rawText || '';

  // 1. Extract closed tags
  const tagListStr = REASONING_TAG_NAMES.join('|');
  const closedTagRegex = new RegExp(`<(${tagListStr})>([\\s\\S]*?)<\\/\\1>`, 'gi');
  let match;
  while ((match = closedTagRegex.exec(content)) !== null) {
    const thoughtBody = match[2].trim();
    if (thoughtBody) {
      reasoningParts.push(thoughtBody);
    }
  }
  content = content.replace(closedTagRegex, '').trim();

  // 2. Extract unclosed tag (<thought>... without matching </thought>)
  const unclosedTagRegex = new RegExp(`<(${tagListStr})>([\\s\\S]*)$`, 'i');
  const unclosedMatch = unclosedTagRegex.exec(content);

  if (unclosedMatch) {
    const prefix = content.substring(0, unclosedMatch.index).trim();
    const unclosedBody = unclosedMatch[2].trim();

    const splitIdx = findTransitionSplit(unclosedBody);
    if (splitIdx !== -1) {
      const thoughtPart = unclosedBody.substring(0, splitIdx).trim();
      let ansPart = unclosedBody.substring(splitIdx).trim();
      ansPart = ansPart.replace(/^(?:---|===|\*\*\*)\s*/, '').trim();
      if (thoughtPart) reasoningParts.push(thoughtPart);
      content = prefix ? (prefix + '\n\n' + ansPart) : ansPart;
    } else {
      if (isStreaming) {
        if (unclosedBody) reasoningParts.push(unclosedBody);
        content = prefix;
      } else {
        if (prefix) {
          if (unclosedBody) reasoningParts.push(unclosedBody);
          content = prefix;
        } else {
          content = unclosedBody;
        }
      }
    }
  }

  // 3. Final safety check on completion: if content is empty but reasoning exists, extract answer
  if (!isStreaming && (!content || !content.trim()) && reasoningParts.length > 0) {
    const allReasoning = reasoningParts.join('\n\n').trim();
    const splitIdx = findTransitionSplit(allReasoning);
    if (splitIdx !== -1) {
      const thoughtPart = allReasoning.substring(0, splitIdx).trim();
      let ansPart = allReasoning.substring(splitIdx).trim();
      ansPart = ansPart.replace(/^(?:---|===|\*\*\*)\s*/, '').trim();
      return { reasoning: thoughtPart, content: ansPart };
    } else {
      return { reasoning: '', content: allReasoning };
    }
  }

  return {
    reasoning: reasoningParts.join('\n\n').trim(),
    content: content.trim()
  };
}

/**
 * Update message thought disclosure and assistant body
 */
function updateMessageDisplay(msgId) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  const { reasoning, content } = extractThinkingAndContent(buf.text, buf.reasoning, buf.isStreaming);

  // Update Thinking Box
  const thinkingBox = document.getElementById(`thinking-${msgId}`);
  const thinkingContent = document.getElementById(`thinking-content-${msgId}`);
  if (thinkingBox && thinkingContent) {
    if (reasoning && reasoning.trim()) {
      thinkingBox.style.display = 'block';
      const labelSpan = thinkingBox.querySelector('.thought-summary span:nth-child(2)');

      if (buf.isStreaming && (!content || !content.trim())) {
        if (labelSpan) labelSpan.innerText = 'Thinking...';
        if (!thinkingBox.dataset.manualToggle) {
          thinkingBox.classList.add('open');
        }
      } else {
        if (labelSpan) labelSpan.innerText = 'Thought process';
        if (buf.isStreaming && content && content.trim() && !thinkingBox.dataset.manualToggle) {
          thinkingBox.classList.remove('open');
        }
      }

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
    } else if (buf.isStreaming && reasoning && reasoning.trim()) {
      contentEl.innerHTML = '';
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
    box.dataset.manualToggle = 'true';
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

  let card = document.getElementById(`tool-${toolId}`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'tool-card open';
    card.id = `tool-${toolId}`;

    const contentEl = document.getElementById(`content-${msgId}`);
    if (contentEl) {
      row.insertBefore(card, contentEl);
    } else {
      row.appendChild(card);
    }
  }

  card.innerHTML = `
    <div class="tool-header" onclick="this.parentElement.classList.toggle('open')">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="tool-chevron">›</span>
        <span>Tool: <strong>${toolName}</strong></span>
      </div>
      <span class="tool-status running" id="tool-status-${toolId}">Running...</span>
    </div>
    <div class="tool-body" id="tool-body-${toolId}">
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Arguments:</div>
      <pre style="margin:0;padding:6px;background:var(--code-bg);border:none;"><code>${argsJson}</code></pre>
    </div>
  `;
  scrollToBottom(false);
}

/**
 * Update Tool Result
 */
function update_tool_result(msgId, toolId, toolName, resultStr, errorStr, success = true, durationMs = 0) {
  const statusEl = document.getElementById(`tool-status-${toolId}`);
  const bodyEl = document.getElementById(`tool-body-${toolId}`);

  if (statusEl) {
    statusEl.className = success ? 'tool-status success' : 'tool-status error';
    statusEl.innerText = success ? `Success (${durationMs}ms)` : `Failed (${durationMs}ms)`;
  }

  if (bodyEl) {
    const outcomeDiv = document.createElement('div');
    outcomeDiv.style.marginTop = '8px';
    outcomeDiv.style.borderTop = '1px solid var(--border-color)';
    outcomeDiv.style.paddingTop = '6px';

    if (success) {
      outcomeDiv.innerHTML = `
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Result:</div>
        <pre style="margin:0;padding:6px;background:var(--code-bg);border:none;max-height:180px;overflow:auto;"><code>${resultStr}</code></pre>
      `;
    } else {
      outcomeDiv.innerHTML = `
        <div style="font-size:11px;color:#fca5a5;margin-bottom:4px;">Error:</div>
        <div style="color:#fca5a5;font-size:12px;">${errorStr}</div>
      `;
    }
    bodyEl.appendChild(outcomeDiv);
  }
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
window.update_tool_result = update_tool_result;
window.finish_assistant_message = finish_assistant_message;
window.set_error = set_error;
window.clear_chat = clear_chat;
window.set_theme = set_theme;
window.onSuggestionClick = onSuggestionClick;
window.toggleThinking = toggleThinking;
window.copyMessageText = copyMessageText;
window.regenerateMessage = regenerateMessage;
