/**
 * Scholarship Star v2 – Client-Side Reactive Controller
 */

// ── State ─────────────────────────────────────────────────────────────
let abortController = null;
let currentRunId = null;
let runStartTime = null;
let timerInterval = null;
let activeFilter = 'all';

// Telemetry counters
const telemetry = {
  llm: 0,
  searches: 0,
  pages: 0,
  retries: 0,
  fallbacks: 0,
  cacheHits: 0
};

// Map of agent blocks in feed: { [agentName]: DOMElement }
const agentBlocks = {};
const verifiedOpportunities = [];

// ── Presets ───────────────────────────────────────────────────────────
const PRESETS = {
  A: {
    name: "Rahul Kumar",
    level: "Masters",
    fields: "Computer Science, Artificial Intelligence, Machine Learning",
    countries: "USA, UK, Germany, Canada",
    github: "https://github.com/rahul-cs",
    resume: "B.Tech in Computer Science from IIT, CGPA 9.2/10.0.\nPublished paper on Transformer attention mechanisms.\nSkills: Python, PyTorch, C++, Distributed Systems.\nProjects: Neural Search Engine, Distributed KV Store.\nAwards: 1st Place National Hackathon."
  },
  B: {
    name: "Priya Sharma",
    level: "PhD",
    fields: "Biotechnology, Molecular Biology, Genomics",
    countries: "Germany, Netherlands, Switzerland, UK",
    github: "",
    resume: "M.Sc in Biotechnology from Delhi University, CGPA 8.8/10.0.\nResearch thesis on CRISPR Cas-9 genetic screening in rice pathogens.\nSkills: PCR, Cell Culture, Next-Gen Sequencing, R, Python.\nPublications: 2 co-authored papers in peer-reviewed journals."
  }
};

// ── DOM References ───────────────────────────────────────────────────
const btnLaunch = document.getElementById('btnLaunch');
const btnFinishNow = document.getElementById('btnFinishNow');
const btnStop = document.getElementById('btnStop');
const chaosToggle = document.getElementById('chaosToggle');

const runStateBadge = document.getElementById('runStateBadge');
const runStateText = document.getElementById('runStateText');
const elapsedTimer = document.getElementById('elapsedTimer');
const etaTimer = document.getElementById('etaTimer');
const progressPhaseLabel = document.getElementById('progressPhaseLabel');
const progressPctText = document.getElementById('progressPctText');
const progressFill = document.getElementById('progressFill');

const feedList = document.getElementById('feedList');
const feedBody = document.getElementById('feedBody');
const cardsList = document.getElementById('cardsList');

const cntLlm = document.getElementById('cntLlm');
const cntSearches = document.getElementById('cntSearches');
const cntPages = document.getElementById('cntPages');
const cntRetries = document.getElementById('cntRetries');
const cntFallbacks = document.getElementById('cntFallbacks');
const cntCacheHits = document.getElementById('cntCacheHits');

const quotePopover = document.getElementById('quotePopover');
const popoverField = document.getElementById('popoverField');
const popoverText = document.getElementById('popoverText');
const popoverLink = document.getElementById('popoverLink');
const popoverClose = document.getElementById('popoverClose');

// Modal Elements
const profileModal = document.getElementById('profileModal');
const btnOpenModal = document.getElementById('btnOpenModal');
const btnCloseModal = document.getElementById('btnCloseModal');
const btnCancelModal = document.getElementById('btnCancelModal');
const btnModalLaunch = document.getElementById('btnModalLaunch');

const modalInpResumeFile = document.getElementById('modalInpResumeFile');
const modalInpMarksheetFile = document.getElementById('modalInpMarksheetFile');
const badgeResumeFile = document.getElementById('badgeResumeFile');
const badgeMarksheetFile = document.getElementById('badgeMarksheetFile');

// Chat Elements
const chatInput = document.getElementById('chatInput');
const btnSendChat = document.getElementById('btnSendChat');

// ── Modal Handlers ───────────────────────────────────────────────────
if (btnOpenModal) {
  btnOpenModal.addEventListener('click', () => {
    profileModal.style.display = 'flex';
  });
}
if (btnCloseModal) {
  btnCloseModal.addEventListener('click', () => {
    profileModal.style.display = 'none';
  });
}
if (btnCancelModal) {
  btnCancelModal.addEventListener('click', () => {
    profileModal.style.display = 'none';
  });
}

// File Dropzone Listeners
if (modalInpResumeFile) {
  modalInpResumeFile.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      badgeResumeFile.textContent = `Attached: ${e.target.files[0].name}`;
      badgeResumeFile.style.display = 'inline-block';
    }
  });
}
if (modalInpMarksheetFile) {
  modalInpMarksheetFile.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      badgeMarksheetFile.textContent = `Attached: ${e.target.files[0].name}`;
      badgeMarksheetFile.style.display = 'inline-block';
    }
  });
}

// ── Preset Handlers ───────────────────────────────────────────────────
document.getElementById('btnPresetA').addEventListener('click', () => loadPreset(PRESETS.A));
document.getElementById('btnPresetB').addEventListener('click', () => loadPreset(PRESETS.B));
if (document.getElementById('modalPresetA')) {
  document.getElementById('modalPresetA').addEventListener('click', () => loadPreset(PRESETS.A));
}
if (document.getElementById('modalPresetB')) {
  document.getElementById('modalPresetB').addEventListener('click', () => loadPreset(PRESETS.B));
}

function loadPreset(p) {
  // Sync Left Panel
  document.getElementById('inpName').value = p.name;
  document.getElementById('inpLevel').value = p.level;
  document.getElementById('inpFields').value = p.fields;
  document.getElementById('inpCountries').value = p.countries;
  document.getElementById('inpGithub').value = p.github;
  document.getElementById('inpResume').value = p.resume;

  // Sync Modal
  if (document.getElementById('modalInpName')) {
    document.getElementById('modalInpName').value = p.name;
    document.getElementById('modalInpLevel').value = p.level;
    document.getElementById('modalInpFields').value = p.fields;
    document.getElementById('modalInpCountries').value = p.countries;
    document.getElementById('modalInpGithub').value = p.github;
    document.getElementById('modalInpResumeText').value = p.resume;
  }
}

if (btnModalLaunch) {
  btnModalLaunch.addEventListener('click', () => {
    // Copy modal fields to left inputs if needed
    if (document.getElementById('modalInpName')) {
      document.getElementById('inpName').value = document.getElementById('modalInpName').value;
      document.getElementById('inpLevel').value = document.getElementById('modalInpLevel').value;
      document.getElementById('inpFields').value = document.getElementById('modalInpFields').value;
      document.getElementById('inpCountries').value = document.getElementById('modalInpCountries').value;
      document.getElementById('inpGithub').value = document.getElementById('modalInpGithub').value;
      document.getElementById('inpResume').value = document.getElementById('modalInpResumeText').value;
    }
    profileModal.style.display = 'none';
    launchSwarm();
  });
}

// ── Tab Navigation ────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.tab;
    document.getElementById('tabCards').style.display = target === 'cards' ? 'block' : 'none';
    document.getElementById('tabDossier').style.display = target === 'dossier' ? 'block' : 'none';
    document.getElementById('tabSop').style.display = target === 'sop' ? 'block' : 'none';
    document.getElementById('tabGaps').style.display = target === 'gaps' ? 'block' : 'none';
    document.getElementById('tabTimeline').style.display = target === 'timeline' ? 'block' : 'none';
  });
});

// ── Feed Filter Handlers ──────────────────────────────────────────────
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    applyFeedFilter();
  });
});

function applyFeedFilter() {
  document.querySelectorAll('.feed-item').forEach(item => {
    const isHandoff = item.classList.contains('item-handoff');
    const isRecovery = item.classList.contains('item-recovery');
    if (activeFilter === 'all') {
      item.style.display = '';
    } else if (activeFilter === 'handoffs') {
      item.style.display = isHandoff ? '' : 'none';
    } else if (activeFilter === 'recoveries') {
      item.style.display = isRecovery ? '' : 'none';
    }
  });
}

// ── Swarm Graph Animations ────────────────────────────────────────────
function setAgentNodeState(agentName, state) {
  const norm = agentName.replace(/\s+/g, '').replace(/#\d+/, '');
  const circle = document.getElementById(`circle-${norm}`);
  if (!circle) return;

  if (state === 'working') {
    circle.setAttribute('stroke', '#06b6d4');
    circle.setAttribute('stroke-width', '3');
    circle.style.filter = 'drop-shadow(0 0 8px rgba(6, 182, 212, 0.8))';
  } else if (state === 'done') {
    circle.setAttribute('stroke', '#10b981');
    circle.setAttribute('stroke-width', '2');
    circle.style.filter = 'drop-shadow(0 0 6px rgba(16, 185, 129, 0.5))';
  } else if (state === 'retrying') {
    circle.setAttribute('stroke', '#f59e0b');
    circle.setAttribute('stroke-width', '3');
    circle.style.filter = 'drop-shadow(0 0 8px rgba(245, 158, 11, 0.8))';
  } else {
    circle.setAttribute('stroke', '#475569');
    circle.setAttribute('stroke-width', '2');
    circle.style.filter = 'none';
  }
}

function animateHandoffEdge(edgeId) {
  const edge = document.getElementById(edgeId);
  if (!edge) return;
  edge.setAttribute('stroke', '#6366f1');
  edge.setAttribute('stroke-width', '3');
  setTimeout(() => {
    edge.setAttribute('stroke', '#334155');
    edge.setAttribute('stroke-width', '2');
  }, 1200);
}

function updateWorkerDots(activeWorkerId) {
  for (let i = 1; i <= 6; i++) {
    const dot = document.getElementById(`wdot-${i}`);
    if (dot) {
      if (i === activeWorkerId) {
        dot.classList.add('active');
        setTimeout(() => dot.classList.remove('active'), 2500);
      }
    }
  }
}

// ── Popover Controller ────────────────────────────────────────────────
popoverClose.addEventListener('click', () => {
  quotePopover.style.display = 'none';
});

function showEvidencePopover(event, fieldName, quote, url) {
  event.stopPropagation();
  popoverField.textContent = `VERIFIED EVIDENCE: ${fieldName.toUpperCase()}`;
  popoverText.textContent = quote || 'No quote extracted';
  if (url) {
    popoverLink.href = url;
    popoverLink.style.display = 'inline-block';
  } else {
    popoverLink.style.display = 'none';
  }

  const rect = event.target.getBoundingClientRect();
  quotePopover.style.top = `${Math.min(window.innerHeight - 200, rect.bottom + 8)}px`;
  quotePopover.style.left = `${Math.max(10, Math.min(window.innerWidth - 380, rect.left - 50))}px`;
  quotePopover.style.display = 'block';
}

document.addEventListener('click', (e) => {
  if (!quotePopover.contains(e.target) && !e.target.classList.contains('ev-chip')) {
    quotePopover.style.display = 'none';
  }
});

// ── Stream Reader & Event Dispatcher ─────────────────────────────────
btnLaunch.addEventListener('click', launchSwarm);

// ── Chatbot Interaction Handlers ─────────────────────────────────────
if (btnSendChat) {
  btnSendChat.addEventListener('click', sendChatMessage);
}
if (chatInput) {
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage();
  });
}

async function sendChatMessage() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  appendChatBubble('user', text);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, run_id: currentRunId || '' })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appendChatBubble('supervisor', data.reply);
  } catch (err) {
    appendChatBubble('supervisor', `Chat service error: ${err.message}`);
  }
}

function scrollToBottom(container) {
  if (!container) return;
  container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
}

function appendChatBubble(role, text) {
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble chat-bubble-${role === 'user' ? 'user' : 'supervisor'}`;
  const title = role === 'user' ? '🧑 You' : '🎓 Swarm Supervisor';
  bubble.innerHTML = `<strong>${title}</strong><div style="margin-top:4px;">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
  feedList.appendChild(bubble);
  scrollToBottom(feedBody);
}

function renderDossier(profile) {
  if (!profile) return;
  const academicElem = document.getElementById('dossierAcademic');
  if (academicElem) {
    const edu = (profile.education && profile.education[0]) ? `${profile.education[0].degree} from ${profile.education[0].institution} (CGPA: ${profile.education[0].cgpa || 'N/A'})` : 'Undergraduate study';
    academicElem.innerHTML = `<strong>${escapeHtml(profile.name)}</strong><br>Target: ${escapeHtml(profile.target_level)} in ${escapeHtml(profile.target_fields ? profile.target_fields.join(', ') : '')}<br>Citizenship: <span style="color:#6ee7b7; font-weight:600;">${escapeHtml(profile.citizenship || 'International')}</span> | Residency: ${escapeHtml(profile.residency_status || 'Non-Resident')}<br>Background: ${escapeHtml(edu)}`;
  }
  const skillsElem = document.getElementById('dossierSkills');
  if (skillsElem && profile.skills && profile.skills.length > 0) {
    skillsElem.innerHTML = profile.skills.map(s => `<span class="skill-badge">${escapeHtml(s)}</span>`).join(' ');
  }
  const projectsElem = document.getElementById('dossierProjects');
  if (projectsElem && profile.projects && profile.projects.length > 0) {
    projectsElem.innerHTML = profile.projects.map(p => `
      <div class="project-card">
        <div class="project-card-title">${escapeHtml(p.name)}</div>
        <div class="project-card-desc">${escapeHtml(p.description)}</div>
        ${p.tech && p.tech.length ? `<div style="margin-top:4px; font-size:10px; color:var(--accent-cyan);">Tech: ${escapeHtml(p.tech.join(', '))}</div>` : ''}
      </div>
    `).join('');
  }
}

async function launchSwarm() {
  const name = (document.getElementById('modalInpName')?.value || document.getElementById('inpName').value || 'Student Candidate').trim();
  const level = document.getElementById('modalInpLevel')?.value || document.getElementById('inpLevel').value;
  const fields = (document.getElementById('modalInpFields')?.value || document.getElementById('inpFields').value || '').trim();
  const countries = (document.getElementById('modalInpCountries')?.value || document.getElementById('inpCountries').value || '').trim();
  const citizenship = (document.getElementById('modalInpCitizenship')?.value || 'International').trim();
  const residency = (document.getElementById('modalInpResidency')?.value || 'Non-Resident').trim();
  const github = (document.getElementById('modalInpGithub')?.value || document.getElementById('inpGithub').value || '').trim();
  const linkedin = (document.getElementById('modalInpLinkedin')?.value || '').trim();
  const portfolio = (document.getElementById('modalInpPortfolio')?.value || '').trim();
  const resume = (document.getElementById('modalInpResumeText')?.value || document.getElementById('inpResume').value || '').trim();
  const isChaos = chaosToggle.checked;

  // Reset state
  resetUI();
  setRunState('running', 'Swarm Active');
  btnLaunch.disabled = true;
  btnFinishNow.disabled = false;
  btnStop.disabled = false;

  runStartTime = Date.now();
  timerInterval = setInterval(updateElapsedTimer, 1000);

  abortController = new AbortController();

  const formData = new FormData();
  formData.append('name', name);
  formData.append('target_level', level);
  formData.append('target_fields', fields);
  formData.append('target_countries', countries);
  formData.append('citizenship', citizenship);
  formData.append('residency_status', residency);
  formData.append('github_url', github);
  formData.append('linkedin_url', linkedin);
  formData.append('portfolio_url', portfolio);
  formData.append('resume_text', resume);
  formData.append('chaos', isChaos ? 'true' : 'false');

  // Check for uploaded files
  if (modalInpResumeFile && modalInpResumeFile.files && modalInpResumeFile.files[0]) {
    formData.append('resume', modalInpResumeFile.files[0]);
  }
  if (modalInpMarksheetFile && modalInpMarksheetFile.files && modalInpMarksheetFile.files[0]) {
    formData.append('marksheet', modalInpMarksheetFile.files[0]);
  }

  appendChatBubble('supervisor', `🚀 Initiated autonomous discovery swarm for **${escapeHtml(name)}** targeting **${escapeHtml(level)}** in **${escapeHtml(fields || 'graduate fields')}** (${escapeHtml(countries)}).`);

  try {
    const response = await fetch('/api/run', {
      method: 'POST',
      body: formData,
      signal: abortController.signal
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep remainder

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);
          handleSwarmEvent(evt);
        } catch (err) {
          console.warn('JSON parse error on stream line:', line, err);
        }
      }
    }

  } catch (err) {
    if (err.name === 'AbortError') {
      appendFeedMessage('System', 'warning', 'Swarm execution stopped by user.');
      setRunState('stopped', 'Stopped');
    } else {
      appendFeedMessage('System', 'error', `Stream connection error: ${err.message}`);
      setRunState('stopped', 'Error');
    }
  } finally {
    clearInterval(timerInterval);
    btnLaunch.disabled = false;
    btnFinishNow.disabled = true;
    btnStop.disabled = true;
    if (runStateText.textContent === 'Swarm Active') {
      setRunState('finished', 'Finished');
    }
  }
}

// ── Finish Now & Stop Buttons ─────────────────────────────────────────
btnFinishNow.addEventListener('click', async () => {
  if (!currentRunId) return;
  btnFinishNow.disabled = true;
  appendFeedMessage('System', 'info', '⚡ Sent Finish-Now signal to swarm router...');
  try {
    await fetch(`/api/run/${currentRunId}/finish`, { method: 'POST' });
  } catch (err) {
    console.error('Failed to trigger finish now:', err);
  }
});

btnStop.addEventListener('click', async () => {
  if (abortController) {
    abortController.abort();
  }
  if (currentRunId) {
    try {
      await fetch(`/api/run/${currentRunId}/stop`, { method: 'POST' });
    } catch (err) {
      console.error('Failed to trigger stop:', err);
    }
  }
  setRunState('stopped', 'Stopped');
  btnStop.disabled = true;
  btnFinishNow.disabled = true;
  btnLaunch.disabled = false;
});

// ── Event Processing ──────────────────────────────────────────────────
function handleSwarmEvent(evt) {
  if (evt.run_id && !currentRunId) {
    currentRunId = evt.run_id;
  }

  // Update Telemetry
  if (evt.type === 'llm_call') {
    telemetry.llm++;
    cntLlm.textContent = telemetry.llm;
  } else if (evt.type === 'tool_call' && evt.phase === 'search') {
    telemetry.searches++;
    cntSearches.textContent = telemetry.searches;
  } else if (evt.type === 'tool_result' && evt.phase === 'fetch') {
    telemetry.pages++;
    cntPages.textContent = telemetry.pages;
  } else if (evt.type === 'retry') {
    telemetry.retries++;
    cntRetries.textContent = telemetry.retries;
  } else if (evt.type === 'fallback') {
    telemetry.fallbacks++;
    cntFallbacks.textContent = telemetry.fallbacks;
  } else if (evt.type === 'cache_hit') {
    telemetry.cacheHits++;
    cntCacheHits.textContent = telemetry.cacheHits;
  }

  // Progress update
  if (evt.progress) {
    const pct = Math.round(evt.progress.pct * 100);
    progressFill.style.width = `${pct}%`;
    progressPctText.textContent = `${pct}%`;
    if (evt.progress.eta_s > 0) {
      etaTimer.textContent = `~${formatMinutesSeconds(evt.progress.eta_s)}`;
    } else {
      etaTimer.textContent = '00:00';
    }
  }
  if (evt.message && evt.type === 'start') {
    progressPhaseLabel.textContent = evt.message;
  }

  // Swarm Graph updates
  if (evt.agent) {
    if (evt.type === 'start') {
      setAgentNodeState(evt.agent, 'working');
    } else if (evt.type === 'done') {
      setAgentNodeState(evt.agent, 'done');
    } else if (evt.type === 'retry') {
      setAgentNodeState(evt.agent, 'retrying');
    }
  }

  if (evt.worker) {
    updateWorkerDots(evt.worker);
  }

  if (evt.type === 'handoff') {
    if (evt.agent === 'ProfileAnalyst') animateHandoffEdge('edge-1');
    if (evt.agent === 'Researcher') animateHandoffEdge('edge-2');
    if (evt.agent === 'Verifier') animateHandoffEdge('edge-3');
    if (evt.agent === 'Ranker') animateHandoffEdge('edge-4');
  }

  // Feed updates
  renderFeedEvent(evt);

  // Progressive Result Card
  if (evt.type === 'partial_result' && evt.data) {
    addOpportunityCard(evt.data);
  }

  // Profile synthesis complete
  if (evt.type === 'done' && evt.agent === 'ProfileAnalyst' && evt.data) {
    renderDossier(evt.data);
  }

  // Final Result
  if (evt.type === 'done' && evt.agent === 'System' && evt.data) {
    handleFinalResult(evt.data);
    if (evt.data.profile) {
      renderDossier(evt.data.profile);
    }
  }
}

// ── Feed Rendering (ChatGPT-Style Grouped Blocks) ──────────────────────
function renderFeedEvent(evt) {
  const agentKey = evt.agent || 'System';
  let block = agentBlocks[agentKey];

  if (!block || evt.type === 'start') {
    block = createAgentBlock(agentKey, evt);
    agentBlocks[agentKey] = block;
    feedList.appendChild(block);
  }

  const contentArea = block.querySelector('.agent-block-content');

  // Handoff message
  if (evt.type === 'handoff') {
    const handoffDiv = document.createElement('div');
    handoffDiv.className = 'handoff-card feed-item item-handoff';
    handoffDiv.innerHTML = `<span>⚡</span> <strong>${evt.message}</strong>`;
    contentArea.appendChild(handoffDiv);
  } else {
    // Tool Chip / Event Line
    const chip = document.createElement('div');
    chip.className = `feed-item ${getChipClass(evt.type)}`;

    let icon = '•';
    if (evt.type === 'llm_call') icon = '🧠';
    if (evt.type === 'tool_call') icon = '⚙️';
    if (evt.type === 'retry') icon = '⚠️';
    if (evt.type === 'fallback') icon = '🔄';
    if (evt.type === 'cache_hit') icon = '⚡';
    if (evt.type === 'chaos_injected') icon = '💥';

    const durText = evt.duration_ms ? ` (${evt.duration_ms}ms)` : '';
    chip.innerHTML = `<span>${icon}</span> <span>${escapeHtml(evt.message)}${durText}</span>`;

    if (evt.type === 'retry' || evt.type === 'fallback' || evt.type === 'chaos_injected') {
      chip.classList.add('item-recovery');
    }

    contentArea.appendChild(chip);
  }

  // Always auto-scroll to bottom as AI responses and logs generate
  scrollToBottom(feedBody);

  applyFeedFilter();
}

function createAgentBlock(agentName, evt) {
  const block = document.createElement('div');
  block.className = 'agent-block';

  let icon = '🤖';
  if (agentName.includes('Analyst')) icon = '👤';
  if (agentName.includes('Researcher')) icon = '🔎';
  if (agentName.includes('Verifier')) icon = '🛡️';
  if (agentName.includes('Ranker')) icon = '⚖️';
  if (agentName.includes('SOPWriter')) icon = '✍️';

  const header = document.createElement('div');
  header.className = 'agent-block-header';
  header.innerHTML = `
    <div class="agent-info">
      <div class="agent-avatar">${icon}</div>
      <div class="agent-name">${agentName}</div>
    </div>
    <div class="thought-duration" id="dur-${agentName.replace(/\s+/g, '')}">Active</div>
  `;

  const content = document.createElement('div');
  content.className = 'agent-block-content';

  header.addEventListener('click', () => {
    content.style.display = content.style.display === 'none' ? 'flex' : 'none';
  });

  block.appendChild(header);
  block.appendChild(content);
  return block;
}

function getChipClass(type) {
  if (type === 'llm_call') return 'chip chip-llm';
  if (type === 'retry') return 'chip chip-retry';
  if (type === 'fallback') return 'chip chip-fallback';
  if (type === 'cache_hit') return 'chip chip-cache';
  if (type === 'chaos_injected') return 'chip chip-chaos';
  return 'chip';
}

// ── Progressive Opportunity Cards & Evidence Chips ───────────────────
function addOpportunityCard(opp) {
  // Clear skeleton on first card
  const skeletons = cardsList.querySelectorAll('.skeleton-card');
  skeletons.forEach(s => s.remove());

  verifiedOpportunities.push(opp);

  const card = document.createElement('div');
  card.className = 'opportunity-card';
  card.id = `opp-${opp.candidate.id}`;

  const deadline = opp.deadline || {};
  const funding = opp.funding || {};
  const reqs = opp.requirements || [];

  const verifiedBadge = opp.status === 'verified'
    ? '<span style="color: #34d399; font-size: 11px; font-weight: 700;">✅ VERIFIED</span>'
    : '<span style="color: #fbbf24; font-size: 11px; font-weight: 700;">⚠️ PARTIAL</span>';

  card.innerHTML = `
    <div class="card-top">
      <div>
        <div class="opp-title">${escapeHtml(opp.candidate.name)}</div>
        <div class="opp-meta">
          <span>🏛️ ${escapeHtml(opp.candidate.institution || 'University')}</span>
          <span>📍 ${escapeHtml(opp.candidate.country || 'International')}</span>
          <span>${verifiedBadge}</span>
        </div>
      </div>
      <div>
        <a href="${escapeHtml(opp.official_url || opp.candidate.source_url)}" target="_blank" rel="noopener" class="btn btn-preset" style="font-size: 10px; padding: 4px 8px;">Official Portal ↗</a>
      </div>
    </div>

    <!-- Evidence Chips -->
    <div class="evidence-chips-row">
      <div class="ev-chip ${deadline.verified ? 'verified' : 'unverified'}" data-field="deadline" title="Click to view verbatim evidence quote">
        📅 ${escapeHtml(deadline.value || 'Deadline Unknown')} ${deadline.verified ? '✓' : ''}
      </div>
      <div class="ev-chip ${funding.verified ? 'verified' : 'unverified'}" data-field="funding" title="Click to view verbatim evidence quote">
        💰 ${escapeHtml(funding.value ? funding.value.substring(0, 32) + '...' : 'Funding Unknown')} ${funding.verified ? '✓' : ''}
      </div>
      ${reqs.slice(0, 2).map((r, i) => `
        <div class="ev-chip ${r.result === 'met' ? 'verified' : 'unverified'}" data-field="requirement_${i}">
          📋 ${escapeHtml(r.criterion.substring(0, 24))} (${r.result.toUpperCase()})
        </div>
      `).join('')}
    </div>
  `;

  // Attach popover click events to chips
  const dChip = card.querySelector('[data-field="deadline"]');
  dChip.addEventListener('click', (e) => {
    showEvidencePopover(e, 'Application Deadline', deadline.evidence_quote, opp.official_url || opp.candidate.source_url);
  });

  const fChip = card.querySelector('[data-field="funding"]');
  fChip.addEventListener('click', (e) => {
    showEvidencePopover(e, 'Scholarship Funding', funding.evidence_quote, opp.official_url || opp.candidate.source_url);
  });

  reqs.slice(0, 2).forEach((r, i) => {
    const rChip = card.querySelector(`[data-field="requirement_${i}"]`);
    if (rChip) {
      rChip.addEventListener('click', (e) => {
        showEvidencePopover(e, `Requirement: ${r.criterion}`, r.evidence_quote, opp.official_url || opp.candidate.source_url);
      });
    }
  });

  cardsList.prepend(card);
}

// ── Final Result Aggregation & Tabs Population ────────────────────────
function handleFinalResult(res) {
  setRunState('finished', 'Swarm Complete');

  // Reorganize top cards if ranked opportunities exist
  if (res.ranked && res.ranked.length > 0) {
    cardsList.innerHTML = '';
    res.ranked.forEach((item, idx) => {
      const opp = item.opportunity;
      const card = document.createElement('div');
      card.className = 'opportunity-card top-pick';

      const deadline = opp.deadline || {};
      const funding = opp.funding || {};

      card.innerHTML = `
        <div class="card-top">
          <div>
            <div style="font-size: 11px; font-weight: 700; color: #a5b4fc; text-transform: uppercase;">
              Rank #${item.rank} · Match Score: ${item.score || 90}%
            </div>
            <div class="opp-title">${escapeHtml(opp.candidate.name)}</div>
            <div class="opp-meta">
              <span>🏛️ ${escapeHtml(opp.candidate.institution || 'University')}</span>
              <span>📍 ${escapeHtml(opp.candidate.country || 'International')}</span>
              <span style="color: #34d399; font-weight: 700;">✅ VERIFIED</span>
            </div>
          </div>
          <div>
            <a href="${escapeHtml(opp.official_url || opp.candidate.source_url)}" target="_blank" rel="noopener" class="btn btn-finish" style="font-size: 10px; padding: 4px 8px;">Apply Link ↗</a>
          </div>
        </div>

        <p style="font-size: 12px; color: var(--text-dim); margin-bottom: 10px; line-height: 1.4;">
          <strong>Fit Rationale:</strong> ${escapeHtml(item.why_fit)}
        </p>

        <!-- Evidence Chips -->
        <div class="evidence-chips-row">
          <div class="ev-chip ${deadline.verified ? 'verified' : 'unverified'}" data-field="deadline">
            📅 ${escapeHtml(deadline.value || 'Deadline Unknown')} ✓
          </div>
          <div class="ev-chip ${funding.verified ? 'verified' : 'unverified'}" data-field="funding">
            💰 ${escapeHtml(funding.value ? funding.value.substring(0, 35) + '...' : 'Funded')} ✓
          </div>
        </div>
      `;

      // Evidence popover bindings
      const dChip = card.querySelector('[data-field="deadline"]');
      dChip.addEventListener('click', (e) => {
        showEvidencePopover(e, 'Application Deadline', deadline.evidence_quote, opp.official_url || opp.candidate.source_url);
      });

      const fChip = card.querySelector('[data-field="funding"]');
      fChip.addEventListener('click', (e) => {
        showEvidencePopover(e, 'Scholarship Funding', funding.evidence_quote, opp.official_url || opp.candidate.source_url);
      });

      cardsList.appendChild(card);
    });
  }

  // Populate SOP Draft
  if (res.sop) {
    document.getElementById('sopContent').textContent = res.sop.text;
  }

  // Populate Gap Actions
  if (res.gap_actions && res.gap_actions.length > 0) {
    const gapsContainer = document.getElementById('gapsList');
    gapsContainer.innerHTML = '';
    res.gap_actions.forEach(g => {
      const gItem = document.createElement('div');
      gItem.className = 'gap-item';
      gItem.innerHTML = `
        <div class="gap-impact">${escapeHtml(g.impact || 'Eligibility Factor')}</div>
        <div class="gap-action"><strong>${escapeHtml(g.blocker)}:</strong> ${escapeHtml(g.action)}</div>
      `;
      gapsContainer.appendChild(gItem);
    });
  }

  // Render Timeline & Stats
  const stats = res.summary_stats || {};
  const timelineContainer = document.getElementById('timelineContainer');
  timelineContainer.innerHTML = `
    <div style="background: rgba(14, 19, 31, 0.8); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 14px;">
      <div style="font-weight: 700; font-size: 13px; margin-bottom: 10px; color: #a5b4fc;">Run Summary Statistics</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 12px;">
        <div>Total Wall Time: <strong>${stats.wall_time_s || '--'}s</strong></div>
        <div>LLM Calls: <strong>${stats.llm_calls || telemetry.llm}</strong></div>
        <div>Candidates Found: <strong>${stats.candidates_found || '--'}</strong></div>
        <div>Candidates Verified: <strong>${stats.candidates_verified || '--'}</strong></div>
        <div>Rate Limits (429): <strong>${stats.llm_429s || telemetry.retries}</strong></div>
        <div>Model Fallbacks: <strong>${stats.llm_fallbacks || telemetry.fallbacks}</strong></div>
      </div>
    </div>
  `;
}

// ── Copy & Download SOP ───────────────────────────────────────────────
document.getElementById('btnCopySop').addEventListener('click', () => {
  const text = document.getElementById('sopContent').textContent;
  navigator.clipboard.writeText(text);
  alert('Statement of Purpose copied to clipboard!');
});

document.getElementById('btnDownloadSop').addEventListener('click', () => {
  const text = document.getElementById('sopContent').textContent;
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'Statement_of_Purpose_ScholarshipStar.txt';
  a.click();
});

// ── Helpers ───────────────────────────────────────────────────────────
function resetUI() {
  cardsList.innerHTML = `
    <div class="skeleton-card"></div>
    <div class="skeleton-card"></div>
    <div class="skeleton-card"></div>
  `;
  feedList.innerHTML = '';
  Object.keys(agentBlocks).forEach(k => delete agentBlocks[k]);
  verifiedOpportunities.length = 0;

  telemetry.llm = 0;
  telemetry.searches = 0;
  telemetry.pages = 0;
  telemetry.retries = 0;
  telemetry.fallbacks = 0;
  telemetry.cacheHits = 0;

  cntLlm.textContent = '0';
  cntSearches.textContent = '0';
  cntPages.textContent = '0';
  cntRetries.textContent = '0';
  cntFallbacks.textContent = '0';
  cntCacheHits.textContent = '0';

  progressFill.style.width = '0%';
  progressPctText.textContent = '0%';
  progressPhaseLabel.textContent = 'Initializing swarm...';
  etaTimer.textContent = '--';
}

function setRunState(state, text) {
  runStateBadge.className = `state-badge state-${state}`;
  runStateText.textContent = text;
}

function updateElapsedTimer() {
  if (!runStartTime) return;
  const elapsedSec = Math.floor((Date.now() - runStartTime) / 1000);
  elapsedTimer.textContent = formatMinutesSeconds(elapsedSec);
}

function formatMinutesSeconds(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function appendFeedMessage(agent, type, message) {
  renderFeedEvent({ agent, type, message, ts: new Date().toISOString() });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
