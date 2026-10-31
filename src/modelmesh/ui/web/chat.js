/**
 * ModelMesh Chat Client JavaScript Controller
 * Interacts with PyQt6 backend via QWebChannel
 */

let pyBridge = null;
let currentAssistantId = null;
let messageBuffers = {}; // msgId -> { text: '', reasoning: '', isStreaming: true }

/**
 * Escape text for insertion into HTML (element content or quoted attributes).
 */
function escapeHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Close a code fence left open mid-stream (``` / ```` / ~~~ fences).
 */
function closeOpenFence(text) {
  let open = null;
  for (const line of text.split('\n')) {
    const m = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (!m) continue;
    const fence = m[1];
    if (!open) {
      open = fence;
    } else if (fence[0] === open[0] && fence.length >= open.length && line.trim() === fence) {
      open = null;
    }
  }
  return open ? `${text}\n${open}` : text;
}

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
  // Without both the parser and the sanitizer, never insert model output as HTML.
  if (typeof marked === 'undefined' || !marked.parse || typeof DOMPurify === 'undefined' || !DOMPurify.sanitize) {
    return `<p>${escapeHtml(rawText).replace(/\n/g, '<br/>')}</p>`;
  }
  try {
    const textToParse = isStreaming ? closeOpenFence(rawText) : rawText;
    return DOMPurify.sanitize(marked.parse(textToParse), {
      ADD_ATTR: ['target', 'class'],
      FORBID_ATTR: ['style'],
    });
  } catch (err) {
    console.error('Markdown rendering error:', err);
    return `<p>${escapeHtml(rawText).replace(/\n/g, '<br/>')}</p>`;
  }
}

function attachCodeCopyButtons(container, highlight = true) {
  if (!container) return;
  const preElements = container.querySelectorAll('pre');
  preElements.forEach((pre) => {
    const codeEl = pre.querySelector('code');
    // Highlighting is the costly step: do it once the reply is complete, not on every chunk.
    if (highlight && codeEl && typeof hljs !== 'undefined' && !codeEl.dataset.highlighted) {
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
    header.innerHTML = `<span>${escapeHtml(lang)}</span><button class="code-copy-btn">Copy</button>`;

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

      if (buf.renderedReasoning !== reasoning) {
        buf.renderedReasoning = reasoning;
        thinkingContent.innerHTML = renderMarkdown(reasoning, buf.isStreaming);
      }
      attachCodeCopyButtons(thinkingContent, !buf.isStreaming);
    } else {
      thinkingBox.style.display = 'none';
    }
  }

  // Update Main Assistant Content
  const contentEl = document.getElementById(`content-${msgId}`);
  const contentKey = `${buf.isStreaming}|${content}|${reasoning ? 1 : 0}`;
  if (contentEl && buf.renderedContentKey !== contentKey) {
    buf.renderedContentKey = contentKey;
    if (content || !buf.isStreaming) {
      contentEl.innerHTML = renderMarkdown(content, buf.isStreaming) + (buf.isStreaming ? '<span class="streaming-cursor"></span>' : '');
    } else if (buf.isStreaming && reasoning && reasoning.trim()) {
      contentEl.innerHTML = '';
    } else {
      contentEl.innerHTML = '<span class="streaming-cursor"></span>';
    }
    attachCodeCopyButtons(contentEl, !buf.isStreaming);
  }
}

/**
 * Coalesce re-renders while streaming: render at once if the last render was
 * over 50 ms ago, otherwise schedule one trailing render. (Timers alone are
 * throttled by Chromium while the window is hidden.)
 */
const RENDER_INTERVAL_MS = 50;

function scheduleRender(msgId) {
  const buf = messageBuffers[msgId];
  if (!buf) return;
  const now = Date.now();
  if (now - (buf.lastRenderAt || 0) >= RENDER_INTERVAL_MS) {
    buf.lastRenderAt = now;
    updateMessageDisplay(msgId);
    scrollToBottom(false);
    return;
  }
  if (buf.renderPending) return;
  buf.renderPending = true;
  setTimeout(() => {
    buf.renderPending = false;
    buf.lastRenderAt = Date.now();
    updateMessageDisplay(msgId);
    scrollToBottom(false);
  }, RENDER_INTERVAL_MS);
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

  const bubble = document.createElement('div');
  bubble.className = 'user-bubble';
  (parts || []).forEach(p => {
    if (p.media_type && p.data && /^image\/[\w.+-]+$/.test(p.media_type) && /^[A-Za-z0-9+/=]+$/.test(p.data)) {
      const img = document.createElement('img');
      img.src = `data:${p.media_type};base64,${p.data}`;
      img.className = 'user-attachment-image';
      bubble.appendChild(img);
    } else if (p.name) {
      const chip = document.createElement('div');
      chip.className = 'user-attachment-chip';
      chip.textContent = p.name;
      bubble.appendChild(chip);
    }
  });
  // Typed text is shown exactly as typed, never interpreted as HTML.
  const textEl = document.createElement('div');
  textEl.className = 'user-text';
  textEl.textContent = text;
  bubble.appendChild(textEl);

  row.appendChild(bubble);
  container.appendChild(row);
  scrollToBottom(true);
}

/**
 * Start Assistant Message
 */
function start_assistant_message(msgId, modelName = '', providerName = '', strategyName = '', reason = '', metadata = {}) {
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

  const startMeta = { model_id: modelName, provider_id: providerName, strategy: strategyName, reason, metadata };
  footer.innerHTML = buildFooterItems(startMeta).join('<span class="meta-separator">·</span>');
  row.appendChild(footer);

  container.appendChild(row);
  renderRoutingNotices(msgId, metadata);
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
  scheduleRender(msgId);
}

/**
 * Append streamed reasoning chunk
 */
function append_reasoning_chunk(msgId, chunk) {
  const buf = messageBuffers[msgId];
  if (!buf) return;

  buf.reasoning += chunk;
  scheduleRender(msgId);
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
  if (currentAssistantId === msgId) currentAssistantId = null;
  renderFinishedFooter(msgId, meta);
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
 * Clear Chat
 */
function clear_chat() {
  const container = document.getElementById('chat-container');
  if (container) {
    container.innerHTML = '';
  }
  messageBuffers = {};
  currentAssistantId = null;
  for (const key of Object.keys(toolCards)) delete toolCards[key];
  showEmptyState();
}

/**
 * Theme switch
 */
function set_theme(themeName) {
  const isLight = themeName === 'light';
  const cls = isLight ? 'light-theme' : 'dark-theme';
  document.documentElement.className = cls;
  document.documentElement.setAttribute('data-theme', isLight ? 'light' : 'dark');
  document.body.className = cls;
  document.documentElement.style.backgroundColor = isLight ? '#ffffff' : '#141417';
  document.body.style.backgroundColor = isLight ? '#ffffff' : '#141417';
}

// Global window exposures
window.add_user_message = add_user_message;
window.start_assistant_message = start_assistant_message;
window.append_text_chunk = append_text_chunk;
window.append_reasoning_chunk = append_reasoning_chunk;
window.finish_assistant_message = finish_assistant_message;
window.clear_chat = clear_chat;
window.set_theme = set_theme;
window.onSuggestionClick = onSuggestionClick;
window.toggleThinking = toggleThinking;
window.copyMessageText = copyMessageText;
window.regenerateMessage = regenerateMessage;
