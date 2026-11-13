const app = {sessions: [], current: null, detail: null, signature: '', sending: false};
app.openHistory = new Set();
const statusRefreshMs = 2000;
const activeStatuses = ['preparing', 'queued', 'running', 'responding', 'saving', 'retry_wait', 'cancelling'];
const providerNames = {codex: 'Codex', claude: 'Claude'};
app.provider = 'codex';
try { app.provider = localStorage.getItem('mastery-provider') || 'codex'; } catch {}
if (!providerNames[app.provider]) app.provider = 'codex';
let connectionToken = STUDY_TOKEN;
const $ = (selector) => document.querySelector(selector);
const labels = {basic: '기초 확인', explain: '원리 설명', apply: '새 상황 적용',
  boundary: '경계 판단', review: '재검증'};
const statuses = {pending: '풀어볼 문제', answer_saved: '채점 대기', graded: '채점 완료', assisted: '복습 예정'};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function prose(value) {
  return renderMarkdown(value);
}

function percentage(progress) {
  return progress.percent === null ? '미확인' : `${progress.percent}%`;
}

function meter(progress) {
  return `<div class="meter" aria-hidden="true"><span style="width:${progress.percent || 0}%"></span></div>`;
}

function notify(message) {
  $('#toast').textContent = message;
  $('#toast').style.display = 'block';
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { $('#toast').style.display = 'none'; }, 6500);
}

async function requestJson(path, options) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error || '연결을 확인해 주세요.');
      error.status = response.status;
      throw error;
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('8초 동안 응답이 없습니다. 다시 불러와 주세요.');
    throw error;
  } finally { clearTimeout(timeout); }
}

async function api(path, payload) {
  const options = {headers: {'X-Study-Token': connectionToken}};
  if (payload) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  try { return await requestJson(path, options); }
  catch (error) {
    if (error.status !== 403) throw error;
    const connection = await requestJson('/api/connection', {});
    connectionToken = connection.token;
    options.headers['X-Study-Token'] = connectionToken;
    return requestJson(path, options);
  }
}

function draftKey(id) { return `mastery:${app.current}:${id}`; }

function readDraft(id) {
  try { return localStorage.getItem(draftKey(id)) || ''; }
  catch { return ''; }
}

function saveDraft(id, value) {
  try { localStorage.setItem(draftKey(id), value); }
  catch { notify('브라우저 임시 저장이 막혀 있습니다. 페이지를 닫기 전에 답을 제출해 주세요.'); }
}

function renderSessions() {
  const query = $('#search').value.toLocaleLowerCase();
  const visible = app.sessions.filter(session => session.topic.toLocaleLowerCase().includes(query));
  $('#session-count').textContent = app.sessions.filter(s => s.status !== 'complete').length;
  $('#sessions').innerHTML = visible.map(session => {
    const selected = session.id === app.current;
    const status = session.status === 'complete' ? '완료' : `미응답 ${session.pending_count}개`;
    return `<button class="session ${selected ? 'active' : ''}" data-session="${session.id}"
      aria-current="${selected ? 'page' : 'false'}">
      <span class="session-title">${escapeHtml(session.topic)}</span>
      <span class="session-meta"><span>${status}</span><span>${percentage(session.progress)}</span></span>
      ${meter(session.progress)}</button>`;
  }).join('') || '<div class="subtle">검색 결과가 없습니다.</div>';
  document.querySelectorAll('[data-session]').forEach(button => {
    button.addEventListener('click', () => selectSession(button.dataset.session));
  });
}

function renderStats(detail) {
  const p = detail.progress;
  const counts = p.total === null ? '저장된 진척 정보 없음' : `${p.passed} / ${p.total} 항목 통과`;
  return `<div class="stats">
    <div class="stat"><div class="stat-label">전체 검증 진척</div>
      <strong>${percentage(p)}</strong><small>${counts}</small>${meter(p)}</div>
    <div class="stat"><div class="stat-label">지금 풀 문제</div>
      <strong>${detail.pending_count}</strong><small>개</small></div>
    <div class="stat"><div class="stat-label">다시 확인할 내용</div>
      <strong>${detail.review_count}</strong><small>개</small></div></div>`;
}

function renderConcept(concept) {
  const criteria = Object.entries(concept.criteria).map(([key, status]) => {
    const symbol = status === 'passed' ? '✓' : '○';
    return `<div class="${escapeHtml(status)}">${symbol} ${labels[key]}</div>`;
  }).join('');
  const summary = concept.summary ? `<div class="prose">${prose(concept.summary)}</div>` : '';
  return `<details class="concept"><summary>${escapeHtml(concept.title)}
    <span>${percentage(concept.progress)}</span></summary><div class="criteria">${criteria}</div>
    ${summary}</details>`;
}

function renderMap(detail) {
  return `<aside id="learning-map" class="learning-map"><h2>개념별 학습 지도</h2>` + detail.blocks.map(block => {
    return `<section class="block ${block.id === detail.current_block ? 'current' : ''}">
      <div class="block-title">${escapeHtml(block.title)}</div>
      <div class="subtle">${escapeHtml(block.status)} · ${percentage(block.progress)}</div>
      ${block.concepts.map(renderConcept).join('')}</section>`;
  }).join('') + '</aside>';
}

function renderChoices(question) {
  let choices = question.choices;
  if (!choices || !Object.keys(choices).length) return '';
  if (!Array.isArray(choices)) choices = Object.entries(choices).map(([key, text]) => ({key, text}));
  return '<div class="choices">' + choices.map((choice, index) => {
    const object = typeof choice === 'object' && choice !== null;
    const key = object ? (choice.key || choice.id || String(index + 1)) : String(index + 1);
    const text = object ? (choice.text || choice.label || choice.value || '') : choice;
    const checked = readDraft(question.id) === String(key) ? 'checked' : '';
    return `<label class="choice"><input type="radio" name="choice-${escapeHtml(question.id)}"
      data-choice="${escapeHtml(question.id)}" value="${escapeHtml(key)}" ${checked}>
      <span>${escapeHtml(key)}. ${prose(text)}</span></label>`;
  }).join('') + '</div>';
}

function questionStatus(question, detail) {
  if (question.status !== 'answer_saved') return statuses[question.status] || question.status;
  if (app.statusError) return '채점 대기 · 연결 확인 필요';
  if (questionJob(question, detail)?.resolved_by) return '다음 채점 대기';
  const labels = {preparing: '요청 준비 중', queued: '요청 대기 중', running: '응답 대기',
    responding: '응답 수신 중', saving: '결과 저장 중', retry_wait: '자동 재시도 대기',
    failed: '채점 대기 · 요청 실패', cancelling: '답변 취소 중'};
  return labels[questionJob(question, detail)?.status] || '다음 채점 대기';
}

function questionJob(question, detail) {
  const job = detail?.job;
  if (job?.answer_ids?.includes(question.id)) return job;
  const related = (detail?.conversation || []).findLast(item => item.answer_ids?.includes(question.id));
  return detail?.question_jobs?.[question.id] || related || (job?.answer_ids?.length ? undefined : job);
}

function renderQuestionRetry(question, detail) {
  const job = questionJob(question, detail);
  if (question.status !== 'answer_saved' || !job?.answer_ids?.includes(question.id)) return '';
  if (job.status === 'retry_wait') return `<div class="subtle">${escapeHtml(retryStatus(job))}</div>`;
  if (job.status !== 'failed' || job.resolved_by) return '';
  const count = job.answer_ids.length;
  const shared = count > 1 ? `함께 보낸 ${count}개 답안을 같은 요청으로 다시 보냅니다.` : '';
  return `<div class="actions"><button class="secondary" data-retry-job="${escapeHtml(job.id)}"
    >요청 재시도</button></div><div class="subtle">${shared}</div>`;
}

function activityText(job) {
  if (!job || !activeStatuses.includes(job.status)) return '';
  const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(job.created_at)) / 1000));
  const duration = Number.isFinite(elapsed) ? `${elapsed}초 경과` : '시간 확인 중';
  if (app.statusError) return `${duration}\n연결 확인 필요`;
  const since = Math.max(0, Math.floor((Date.now() - Date.parse(job.last_activity_at)) / 1000));
  const receipt = job.activity_count === 0 ? '아직 수신 없음' : '수신 시점 미확인';
  return Number.isFinite(since) ? `${duration}\n마지막 수신 ${since}초 전` : `${duration}\n${receipt}`;
}

function questionPreview(question, detail) {
  const job = questionJob(question, detail);
  const active = activeStatuses.includes(job?.status);
  if (question.status !== 'answer_saved' || !active || !job.reply_preview) return '';
  return `<div class="live-preview"><span>도착한 답변 · 저장 전</span>
    <div>${escapeHtml(job.reply_preview.slice(-240))}</div></div>`;
}

function renderQuestion(question, detail = app.detail) {
  const pending = question.status === 'pending';
  const activity = question.status === 'answer_saved' ? activityText(questionJob(question, detail)) : '';
  const content = pending ? renderAnswerInput(question) :
    `<div class="answer-label">제출한 답</div>
      <div class="submitted-text">${escapeHtml(question.answer || '')}</div>
      ${renderSavedImages(question.images)}`;
  return `<article class="question" data-question-card="${escapeHtml(question.id)}"><div class="qtop">
    <span class="qnum">QUESTION ${escapeHtml(question.number)}</span>
    <div class="question-status"><span class="pill" data-question-status="${escapeHtml(question.id)}"
      >${escapeHtml(questionStatus(question, detail))}</span>
      <small data-question-activity="${escapeHtml(question.id)}"
        >${escapeHtml(activity)}</small></div>
    </div>
    <div class="question-text prose">${prose(question.prompt)}</div>${content}
    <div data-question-retry="${escapeHtml(question.id)}">
      ${renderQuestionRetry(question, detail)}${renderQuestionCancel(question, detail)}</div>
    <div data-question-preview="${escapeHtml(question.id)}">
      ${questionPreview(question, detail)}</div></article>`;
}

function renderAnswerInput(question) {
  const id = escapeHtml(question.id);
  return `${renderChoices(question)}<label class="answer-label" for="answer-${id}">나의 답</label>
    <textarea id="answer-${id}" data-answer="${id}" aria-keyshortcuts="Meta+Enter"
      placeholder="내 말로 차근차근 설명해 보세요."
    >${escapeHtml(readDraft(question.id))}</textarea>
    ${renderImageInput(question.id)}
    <div class="draft-hint">Enter 줄바꿈 · ⌘+Enter 답변하기 · 초안 자동 저장</div>
    <div class="actions"><button class="primary" data-submit-answer="${id}"
      aria-label="${escapeHtml(question.number)}번 답변하기">답변하기</button></div>`;
}

function renderJob(detail) {
  const job = detail.job;
  if (job?.status === 'cancelled') return '<div class="subtle">답변을 취소했습니다. 수정한 뒤 다시 답변해 주세요.</div>';
  if (!job || job.status === 'complete') {
    if (!detail.grading_count) return '';
    return `<div class="job-banner" role="status">미채점 답안 ${detail.grading_count}개 · 다음 채점 대기
      <div class="subtle">다음 답을 보내거나 이어서 공부하기를 누르면 채점을 이어갑니다.</div>
      <div class="subtle">${escapeHtml(statusCheckText())}</div></div>`;
  }
  if (job.status === 'failed') {
    const stopped = job.attempt > 1 ? `자동 재시도 ${job.attempt - 1}회 후 중단했습니다.` : '';
    const inQuestion = detail.questions.some(question =>
      question.status === 'answer_saved' && job.answer_ids?.includes(question.id));
    const retry = inQuestion ? '해당 문제의 요청 재시도 버튼으로 다시 요청할 수 있습니다.' :
      '<button id="retry" class="secondary">같은 요청 다시 시도</button>';
    return `<div class="job-banner failed" role="status">${escapeHtml(job.error)}
      <div class="subtle">${stopped}</div>
      <br>${retry}</div>`;
  }
  if (detail.questions.some(question => question.status === 'answer_saved' &&
      job.answer_ids?.includes(question.id))) return '';
  return `<div class="job-inline" role="status">${providerBadge(job.provider)} ${jobStatus(job)}
    ${job.status === 'retry_wait' ? `<div class="subtle">${escapeHtml(job.error)}</div>` : ''}
    <span class="subtle activity-time">${escapeHtml(activityText(job))}</span></div>`;
}

function retryStatus(job) {
  const seconds = Math.max(0, Math.ceil((Date.parse(job.retry_at) - Date.now()) / 1000));
  const wait = seconds > 0 ? `${seconds}초 뒤 자동 재시도합니다.` : '자동 재시도를 준비하고 있습니다.';
  return `${wait} (${(job.attempt || 1) + 1}/${job.max_attempts || 3}번째 시도)`;
}

function statusCheckText() {
  const checked = app.statusCheckedAt ? new Date(app.statusCheckedAt).toLocaleTimeString('ko-KR') : '미확인';
  const state = app.statusError ? '연결 확인 필요' : `${statusRefreshMs / 1000}초마다 상태 확인`;
  return `${state} · 마지막 확인 ${checked}`;
}

function providerBadge(provider) {
  const value = providerNames[provider] ? provider : 'codex';
  return `<span class="provider-badge provider-${value}">${providerNames[value]}</span>`;
}

function jobStatus(job) {
  if (job.cancelled_by) return '이후 취소된 요청';
  if (job.resolved_by) return '이전 시도 · 이후 재시도 완료';
  if (job.status === 'retry_wait') return retryStatus(job);
  const labels = {preparing: '입력을 준비하고 있습니다.', queued: '입력 전달을 기다리고 있습니다.',
    running: 'AI가 요청을 처리하고 있습니다.', responding: '답변이 도착하고 있습니다.',
    saving: '답변을 받았습니다. 학습 기록을 반영하고 있습니다.', complete: '답변 완료', failed: '처리 실패',
    cancelling: '답변을 취소하고 있습니다.', cancelled: '답변 취소됨'};
  return labels[job.status] || job.status;
}

function renderJobReply(job) {
  if (job.status === 'cancelled' || job.status === 'cancelling' || job.cancelled_by) {
    return '<div class="subtle">취소한 요청의 결과는 학습에 반영하지 않습니다. 내용을 수정해 다시 보낼 수 있습니다.</div>';
  }
  const text = job.reply || job.reply_preview || '';
  const partial = activeStatuses.includes(job.status) && Boolean(text);
  const body = `<div class="prose ${partial ? 'streaming' : ''}">${prose(text)}</div>`;
  if (job.resolved_by) {
    return `<div class="subtle">이 요청은 이후 재시도로 처리됐습니다. 최신 응답에서 이어가세요.</div>
      ${historyDisclosure(job, '이전 실패 기록 보기', body +
        `<div class="subtle">${escapeHtml(job.error || '')}</div>`)}`;
  }
  if (job.status === 'failed') {
    return `<div class="prose">${prose(job.error || '요청을 완료하지 못했습니다.')}</div>
      <div class="actions"><button class="secondary" data-retry-job="${escapeHtml(job.id)}"
        >요청 재시도</button></div>
      ${text ? historyDisclosure(job, '저장되지 않은 응답 보기', body) : ''}`;
  }
  return body;
}

function historyDisclosure(job, title, body) {
  const open = app.openHistory.has(job.id) ? 'open' : '';
  return `<details data-job-history="${escapeHtml(job.id)}" ${open}>
    <summary>${title}</summary>${body}</details>`;
}

function renderMessage(job) {
  const message = job.answer_count ? `답안 ${job.answer_count}개를 제출했습니다.` : job.message;
  const failed = job.status === 'failed' && !job.resolved_by && !job.cancelled_by;
  const submitted = (job.submitted_answers || []).map(answer =>
    `<div class="submitted-answer">
      <div class="answer-label">QUESTION ${escapeHtml(answer.number)} · 제출한 답</div>
      <div class="submitted-text">${escapeHtml(answer.answer)}</div>
      ${renderSavedImages(answer.images)}</div>`).join('');
  return `<article class="message user"><div class="message-heading">나 → ${providerBadge(job.provider)}</div>
      ${submitted || `<div class="prose">${prose(message || '저장된 위치에서 이어서 공부합니다.')}</div>`}
      ${job.answer_count ? '' : renderSavedImages(job.images)}
      ${renderCancelAnswer(job)}</article>
    <article class="message assistant ${failed ? 'failed' : ''}">
      <div class="message-heading">${providerBadge(job.provider)}
        <span class="message-state">${escapeHtml(jobStatus(job))}</span></div>
      ${renderJobReply(job)}</article>`;
}

function renderCancelAnswer(job) {
  if (!job?.can_cancel) return '';
  const shared = job.answer_ids?.length > 1 ?
    `<div class="subtle">함께 제출한 ${job.answer_ids.length}개 답안을 모두 취소합니다.</div>` : '';
  return `<div class="actions"><button class="secondary" data-cancel-job="${escapeHtml(job.id)}"
    >답변 취소하기</button></div>${shared}`;
}

function renderQuestionCancel(question, detail) {
  const job = questionJob(question, detail);
  return job?.answer_ids?.includes(question.id) ? renderCancelAnswer(job) : '';
}

function renderConversation(detail) {
  const conversation = detail.conversation || [];
  if (conversation.length) return conversation.map(renderMessage).join('');
  if (detail.reply) return `<article class="message assistant">${providerBadge(detail.reply_provider)}
    <div class="prose">${prose(detail.reply)}</div></article>`;
  return '<div class="subtle">AI를 선택하고 답안이나 궁금한 점을 보내면 여기에서 대화가 이어집니다.</div>';
}

function mergeConversation(detail) {
  let state = app.conversationState;
  if (!state || state.sessionId !== detail.id) {
    state = {sessionId: detail.id, items: [], expanded: false, loading: false, before: null};
    app.conversationState = state;
  }
  const incoming = detail.conversation || [];
  const items = state.expanded || state.loading ? [...state.items, ...incoming] : incoming.slice(-1);
  const unique = new Map(items.map(job => [job.id, job]));
  state.items = [...unique.values()].sort((a, b) =>
    (a.created_at || '').localeCompare(b.created_at || '') || a.id.localeCompare(b.id));
  state.items = state.items.map(job => ({...job,
    resolved_by: detail.resolved_jobs?.[job.id] || job.resolved_by}));
  if (!state.expanded) state.before = detail.older_before || null;
  detail.conversation = state.expanded ? state.items : state.items.slice(-1);
  detail.older_before = state.before;
}

function renderConversationTools(detail) {
  const state = app.conversationState;
  const older = detail.older_before ? `<button id="load-older" class="secondary"
    ${state?.loading ? 'disabled' : ''}>${state?.loading ? '불러오는 중…' : '1개 불러오기'}</button>
    <button id="load-all-older" class="secondary" ${state?.loading ? 'disabled' : ''}>전부 불러오기</button>` : '';
  const collapse = state?.expanded ?
    '<button id="collapse-history" class="secondary">최신 대화만 보기</button>' : '';
  return older + collapse;
}

function bindConversationTools(detail) {
  const tools = $('#conversation-tools');
  if (!tools) return;
  tools.innerHTML = renderConversationTools(detail);
  $('#load-older')?.addEventListener('click', loadOlderConversation);
  $('#load-all-older')?.addEventListener('click', loadAllConversation);
  $('#collapse-history')?.addEventListener('click', collapseConversation);
}

async function loadOlderConversation() {
  await loadConversationPage('');
}

async function loadAllConversation() {
  await loadConversationPage('&all=1');
}

async function loadConversationPage(query) {
  const state = app.conversationState;
  if (!state?.before || state.loading) return;
  state.loading = true;
  bindConversationTools(app.detail);
  try {
    const path = `/api/conversations/${encodeURIComponent(state.sessionId)}?before=`;
    const page = await api(path + encodeURIComponent(state.before) + query);
    if (state !== app.conversationState || state.sessionId !== app.current) return;
    const messages = $('#conversation');
    const height = messages.scrollHeight;
    const top = messages.scrollTop;
    state.expanded = true;
    state.before = page.older_before;
    state.items = [...page.conversation, ...state.items];
    mergeConversation(app.detail);
    updateConversation(app.detail);
    messages.scrollTop = top + messages.scrollHeight - height;
  } catch (error) {
    if (state === app.conversationState) notify(error.message);
  } finally {
    state.loading = false;
    if (state === app.conversationState) bindConversationTools(app.detail);
  }
}

function collapseConversation() {
  const state = app.conversationState;
  if (!state || !app.detail) return;
  const latest = state.items.at(-1);
  app.conversationState = null;
  app.detail.conversation = latest ? [latest] : [];
  app.detail.older_before = state.items.length > 1 ? latest.id : state.before;
  mergeConversation(app.detail);
  updateConversation(app.detail);
  $('#conversation').scrollTop = 0;
}

function renderActions(detail) {
  if (detail.status === 'complete') return '<div class="note">정한 범위의 검증을 모두 마쳤습니다.</div>';
  const busy = app.sending || activeStatuses.includes(detail.job?.status);
  const disabled = busy ? 'disabled' : '';
  const button = `<button id="submit" class="secondary" ${disabled}>작성한 답 모두 보내기</button>`;
  const submit = detail.pending_count > 1 ? button : '';
  const hint = detail.web_owned ? '한 문제씩 답을 보내면 남은 질문을 검토해 이 화면에 반영합니다.' :
    '답을 보내거나 이어서 공부하기를 누르면 이 공부를 HTML에서 이어갑니다.';
  return `<div class="actions">${submit}
    <button id="continue" class="secondary" ${disabled}>이어서 공부하기</button></div>
    <p class="subtle">${hint}</p>`;
}

function render(detail) {
  rememberOpenHistory();
  const reply = `<section id="conversation-thread" class="conversation"><h2>AI의 응답</h2>
    <div id="job-status">${renderJob(detail)}</div>
    <div id="conversation-tools" class="conversation-tools"></div>
    <div id="conversation" class="messages" aria-live="polite">${renderConversation(detail)}</div></section>`;
  const pending = detail.questions.map(question => renderQuestion(question, detail)).join('') ||
    '<div class="empty">지금 공개된 문제가 없습니다.<br>이어서 공부하기를 누르면 다음 단계부터 준비합니다.</div>';
  $('#content').innerHTML = `<div class="eyebrow">KEEP LEARNING, AT YOUR PACE</div>
    <h1>${escapeHtml(detail.topic)}</h1><div class="scope">${escapeHtml(detail.scope)}</div>
    ${renderStats(detail)}<div class="workspace"><div>
    <div class="section-heading"><h2>이어서 공부하기</h2>
    <span class="subtle">채점 대기 ${detail.grading_count}개</span></div>${pending}
    <div id="question-replies"></div>
    ${renderActions(detail)}<section id="ask-box" class="ask-box"><h2>AI에게 보내기</h2>
    <textarea id="ask" aria-label="튜터에게 질문" aria-keyshortcuts="Meta+Enter"
      placeholder="헷갈리는 부분을 편하게 물어보세요.">${escapeHtml(readDraft('ask'))}</textarea>
    <div class="draft-hint">Enter 줄바꿈 · ⌘+Enter 답변하기</div>
    ${renderImageInput('ask')}
    <button id="ask-submit" class="secondary">답변하기</button>
    </section>${reply}<details class="notes"><summary>지금까지의 학습 정리</summary>
    <div class="prose">${prose(detail.notes || '아직 저장된 정리가 없습니다.')}</div></details></div>
    ${renderMap(detail)}</div>`;
  bindDetailEvents();
  positionConversation(detail);
  mountStudyDiagrams();
  hydrateStoredImages();
  syncControls(detail);
}

function positionConversation(detail) {
  const thread = document.getElementById('conversation-thread');
  if (!thread?.parentElement) return;
  const answerIds = detail.job?.answer_ids || [];
  const cards = [...document.querySelectorAll('[data-question-card]')];
  const question = cards.findLast(card => answerIds.includes(card.dataset.questionCard));
  const fallback = answerIds.length ? 'question-replies' : 'ask-box';
  const source = question || document.getElementById(fallback);
  if (source && source.nextElementSibling !== thread) source.after(thread);
}

function bindDetailEvents() {
  bindQuestionRetryEvents();
  bindConversationTools(app.detail || {});
  bindImageControls();
  document.querySelectorAll('[data-answer]').forEach(input => {
    input.addEventListener('input', () => saveDraft(input.dataset.answer, input.value));
    bindSubmitShortcut(input, () => submitAnswer(input.dataset.answer));
    bindImagePaste(input, input.dataset.answer);
  });
  document.querySelectorAll('[data-choice]').forEach(input => {
    input.addEventListener('change', () => {
      const target = document.getElementById(`answer-${input.dataset.choice}`);
      target.value = input.value;
      saveDraft(input.dataset.choice, input.value);
    });
  });
  document.querySelectorAll('[data-submit-answer]').forEach(button => {
    button.addEventListener('click', () => submitAnswer(button.dataset.submitAnswer));
  });
  $('#submit')?.addEventListener('click', submitAnswers);
  $('#continue')?.addEventListener('click', () => send({}, '현재 저장된 위치에서 이어서 공부합니다.'));
  $('#retry')?.addEventListener('click', () => send({}, '', app.detail.job.id));
  $('#ask').addEventListener('input', event => saveDraft('ask', event.target.value));
  bindSubmitShortcut($('#ask'), submitQuestion);
  bindImagePaste($('#ask'), 'ask');
  $('#ask-submit').addEventListener('click', submitQuestion);
}

function bindSubmitShortcut(input, submit) {
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || !event.metaKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!event.repeat) submit();
  });
}

function submitQuestion() {
  const message = $('#ask').value.trim();
  if (!message && !hasImages('ask')) return notify('궁금한 점이나 이미지를 입력해 주세요.');
  return send({}, message);
}

function bindQuestionRetryEvents() {
  document.querySelectorAll('[data-retry-job]').forEach(button => {
    button.onclick = () => send({}, '', button.dataset.retryJob);
  });
  document.querySelectorAll('[data-cancel-job]').forEach(button => {
    button.onclick = () => cancelAnswer(button.dataset.cancelJob);
  });
}

async function cancelAnswer(jobId) {
  if (app.sending || app.detail?.job?.status === 'cancelling') return;
  app.sending = true;
  const sessionId = app.current;
  syncControls(app.detail);
  try {
    const result = await api('/api/cancel', {session_id: sessionId, job_id: jobId,
      revision: app.detail.revision});
    for (const answer of result.submitted_answers || []) {
      localStorage.setItem(`mastery:${sessionId}:${answer.id}`, answer.answer);
      restoreImageDrafts(sessionId, answer.id, answer.images || []);
    }
    if (result.answer_ids?.length === 0) {
      localStorage.setItem(`mastery:${sessionId}:ask`, result.message || '');
      restoreImageDrafts(sessionId, 'ask', result.images || []);
    }
    notify('답변을 취소했습니다. 원래 답안을 수정해 다시 보낼 수 있습니다.');
  } catch (error) { notify(error.message); }
  finally { app.sending = false; await refresh(); if (app.detail) syncControls(app.detail); }
}

function submitAnswer(questionId) {
  const input = document.getElementById(`answer-${questionId}`);
  if (!input?.value.trim() && !hasImages(questionId)) return notify('이 문제의 답이나 이미지를 입력해 주세요.');
  return send({[questionId]: input.value}, '이 답을 제출합니다. 남은 질문을 검토하고 필요한 수정·제거를 바로 반영해 주세요.');
}

function submitAnswers() {
  const answers = {};
  document.querySelectorAll('[data-answer]').forEach(input => {
    if (input.value.trim() || hasImages(input.dataset.answer)) answers[input.dataset.answer] = input.value;
  });
  if (!Object.keys(answers).length) return notify('답을 하나 이상 입력해 주세요.');
  send(answers, '입력한 답을 제출합니다. 남은 질문을 검토하고 필요한 수정·제거를 바로 반영해 주세요.');
}

async function send(answers, message, retryJobId = null) {
  if (app.sending || activeStatuses.includes(app.detail.job?.status)) {
    return notify('현재 답을 확인하고 있습니다. 잠시 기다려 주세요.');
  }
  const targets = Object.keys(answers).length ? Object.keys(answers) : ['ask'];
  if (targets.some(target => imageReads.has(imageDraftKey(target)))) {
    return notify('이미지를 읽고 있습니다. 미리보기가 나타나면 보내 주세요.');
  }
  app.sending = true;
  const sessionId = app.current;
  const provider = app.provider;
  const images = retryJobId ? [] : imagePayload(targets);
  syncControls(app.detail);
  try {
    await api('/api/submit', {request_id: crypto.randomUUID(), session_id: sessionId,
      revision: app.detail.revision, answers, message, take_over: !app.detail.web_owned,
      retry_job_id: retryJobId, provider, images});
    Object.keys(answers).forEach(id => localStorage.removeItem(`mastery:${sessionId}:${id}`));
    if (!retryJobId) targets.forEach(id => imageDrafts.delete(`${sessionId}:${id}`));
    notify(`${providerNames[provider]}에 보냈습니다. 답변은 이 화면에 표시됩니다.`);
  } catch (error) { notify(error.message); }
  finally { app.sending = false; await refresh(); if (app.detail) syncControls(app.detail); }
}

async function selectSession(id) {
  app.events?.abort();
  app.current = id;
  app.detail = null;
  app.conversationState = null;
  app.openHistory.clear();
  app.statusCheckedAt = null;
  app.statusError = false;
  app.signature = '';
  history.replaceState(null, '', `#${id}`);
  renderSessions();
  $('#content').innerHTML = '<div class="empty">학습 기록을 불러오고 있습니다.</div>';
  try { await refreshDetail(); if (id === app.current) watchSession(id); }
  catch (error) {
    if (id === app.current) showLoadError(error);
  }
}

async function refreshDetail() {
  if (!app.current) return;
  const selected = app.current;
  const detail = await api(`/api/sessions/${encodeURIComponent(selected)}`);
  if (selected !== app.current) return;
  app.statusCheckedAt = Date.now();
  app.statusError = false;
  mergeConversation(detail);
  const signature = JSON.stringify([detail.id, detail.revision]);
  if (signature !== app.signature) {
    render(detail);
    app.signature = signature;
  } else {
    updateConversation(detail);
  }
  app.detail = detail;
  bindConversationTools(detail);
  syncControls(detail);
  $('#connection').textContent = '● 학습 기록 연결됨';
}

function syncControls(detail) {
  const busy = app.sending || activeStatuses.includes(detail.job?.status);
  for (const selector of ['#submit', '#continue', '#ask-submit', '#retry']) {
    const button = $(selector);
    if (button) button.disabled = busy;
  }
  document.querySelectorAll('[data-submit-answer]').forEach(button => { button.disabled = busy; });
  document.querySelectorAll('[data-retry-job]').forEach(button => { button.disabled = busy; });
  document.querySelectorAll('[data-cancel-job]').forEach(button => {
    button.disabled = app.sending || detail.job?.status === 'cancelling';
  });
  document.querySelectorAll('[data-image-add], [data-image-remove]').forEach(button => {
    button.disabled = app.sending;
  });
}

function rememberOpenHistory() {
  document.querySelectorAll('[data-job-history]').forEach(history => {
    if (history.open) app.openHistory.add(history.dataset.jobHistory);
    else app.openHistory.delete(history.dataset.jobHistory);
  });
}

function updateConversation(detail) {
  const messages = $('#conversation');
  if (!messages) return;
  positionConversation(detail);
  const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
  rememberOpenHistory();
  const html = renderConversation(detail);
  if (messages.studyHtml !== html) {
    messages.innerHTML = html;
    messages.studyHtml = html;
    mountStudyDiagrams();
    hydrateStoredImages();
  }
  if (atBottom) messages.scrollTop = messages.scrollHeight;
  bindConversationTools(detail);
  updateJobStatus(detail);
}

function updateJobStatus(detail) {
  $('#job-status').innerHTML = renderJob(detail);
  $('#retry')?.addEventListener('click', () => send({}, '', detail.job.id));
  const questions = new Map(detail.questions.map(question => [question.id, question]));
  document.querySelectorAll('[data-question-status]').forEach(badge => {
    const question = questions.get(badge.dataset.questionStatus);
    if (question) badge.textContent = questionStatus(question, detail);
  });
  document.querySelectorAll('[data-question-activity]').forEach(label => {
    const question = questions.get(label.dataset.questionActivity);
    const pending = question?.status === 'answer_saved';
    label.textContent = pending ? activityText(questionJob(question, detail)) : '';
  });
  document.querySelectorAll('[data-question-preview]').forEach(area => {
    const question = questions.get(area.dataset.questionPreview);
    area.innerHTML = question ? questionPreview(question, detail) : '';
  });
  document.querySelectorAll('[data-question-retry]').forEach(area => {
    const question = questions.get(area.dataset.questionRetry);
    area.innerHTML = question ? renderQuestionRetry(question, detail) +
      renderQuestionCancel(question, detail) : '';
  });
  bindQuestionRetryEvents();
  syncControls(detail);
}

function receiveJob(sessionId, job) {
  if (sessionId !== app.current || app.detail?.id !== sessionId || !job) return;
  app.statusCheckedAt = Date.now();
  app.statusError = false;
  const previous = app.detail.job;
  app.detail.job = job;
  const conversation = (app.detail.conversation || []).filter(item => item.id !== job.id);
  if (previous && previous.id !== job.id) app.detail.older_before = job.id;
  app.detail.conversation = [...conversation, job];
  mergeConversation(app.detail);
  updateConversation(app.detail);
  syncControls(app.detail);
  if (['complete', 'cancelled'].includes(job.status) &&
      (previous?.id !== job.id || previous?.status !== job.status)) {
    refresh();
  }
}

function consumeEvents(buffer, sessionId) {
  const packets = buffer.split('\n\n');
  const unfinished = packets.pop();
  for (const packet of packets) {
    const line = packet.split('\n').find(value => value.startsWith('data: '));
    if (line) receiveJob(sessionId, JSON.parse(line.slice(6)).job);
  }
  return unfinished;
}

async function readEvents(sessionId, controller) {
  const url = `/api/events/${encodeURIComponent(sessionId)}`;
  const response = await fetch(url, {headers: {'X-Study-Token': connectionToken}, signal: controller.signal});
  if (!response.ok) {
    if (response.status === 403) await api('/api/sessions');
    throw new Error('응답 연결을 다시 시도합니다.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (!controller.signal.aborted) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, {stream: true});
      buffer = consumeEvents(buffer, sessionId);
    }
  } finally { reader.releaseLock(); }
}

async function watchSession(sessionId) {
  app.events?.abort();
  const controller = new AbortController();
  app.events = controller;
  while (sessionId === app.current && !controller.signal.aborted) {
    try { await readEvents(sessionId, controller); }
    catch (error) { if (controller.signal.aborted) return; }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

async function loadProviders() {
  $('#provider').value = app.provider;
  try {
    const data = await api('/api/providers');
    $('#provider').innerHTML = data.providers.map(provider => {
      const disabled = provider.available ? '' : 'disabled';
      const suffix = provider.available ? '' : ' (설치 필요)';
      return `<option value="${provider.id}" ${disabled}>${provider.name}${suffix}</option>`;
    }).join('');
    $('#provider').value = app.provider;
  } catch { notify('AI 목록을 확인하지 못했습니다. 연결을 다시 확인해 주세요.'); }
}

function showLoadError(error) {
  $('#connection').textContent = `연결 확인 필요 · ${error.message}`;
  app.statusError = true;
  if (app.detail?.id === app.current) return updateJobStatus(app.detail);
  $('#content').innerHTML = `<div class="empty">기록을 불러오지 못했습니다.<br>${escapeHtml(error.message)}
    <div class="actions"><button id="reload-records" class="secondary">다시 불러오기</button></div></div>`;
  $('#reload-records').addEventListener('click', () => {
    if (app.current) selectSession(app.current);
    else refresh();
  });
}

async function refresh() {
  try {
    const data = await api('/api/sessions');
    app.sessions = data.sessions;
    renderSessions();
    if (!app.current && data.sessions.length) {
      const requested = location.hash.slice(1);
      const session = data.sessions.find(s => s.id === requested) || data.sessions[0];
      await selectSession(session.id);
    } else { await refreshDetail(); }
    if (!data.sessions.length) $('#content').innerHTML = '<div class="empty">저장된 공부가 없습니다.</div>';
    if (!data.sessions.length) $('#connection').textContent = '● 학습 기록 연결됨';
  } catch (error) {
    showLoadError(error);
  }
}

async function poll() {
  await refresh();
  setTimeout(poll, statusRefreshMs);
}

const displayDefaults = {fontSize: 22, sidebarCollapsed: false, mapCollapsed: false};
const displayStorageKey = 'mastery-display';
let displaySettings = {...displayDefaults};

function restoreDisplaySettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(displayStorageKey));
    if (!saved || typeof saved !== 'object') return;
    if (Number.isInteger(saved.fontSize) && saved.fontSize >= 18 && saved.fontSize <= 36) {
      displaySettings.fontSize = saved.fontSize;
    }
    for (const key of ['sidebarCollapsed', 'mapCollapsed']) {
      if (typeof saved[key] === 'boolean') displaySettings[key] = saved[key];
    }
  } catch {}
}

function applyDisplaySettings() {
  const root = document.documentElement;
  root.style.fontSize = `${displaySettings.fontSize}px`;
  root.classList.toggle('sidebar-collapsed', displaySettings.sidebarCollapsed);
  root.classList.toggle('map-collapsed', displaySettings.mapCollapsed);
  for (const [id, key, label] of [
    ['sidebar', 'sidebarCollapsed', '공부 목록'], ['map', 'mapCollapsed', '학습 지도'],
  ]) {
    const button = $(`#toggle-${id}`);
    button.textContent = `${label} ${displaySettings[key] ? '펼치기' : '접기'}`;
    button.setAttribute('aria-expanded', String(!displaySettings[key]));
  }
  $('#font-size').value = displaySettings.fontSize;
  $('#font-size').setAttribute('aria-valuetext', `${displaySettings.fontSize}픽셀`);
  $('#font-size-value').textContent = `${displaySettings.fontSize}px`;
  $('#font-smaller').disabled = displaySettings.fontSize <= 18;
  $('#font-larger').disabled = displaySettings.fontSize >= 36;
}

function saveDisplaySettings() {
  applyDisplaySettings();
  try { localStorage.setItem(displayStorageKey, JSON.stringify(displaySettings)); }
  catch { notify('화면 설정은 적용됐지만 저장하지 못했습니다. 다음에 열면 기본값으로 표시됩니다.'); }
}

function changeFontSize(size) {
  displaySettings.fontSize = Math.max(18, Math.min(36, size));
  saveDisplaySettings();
}

function initDisplaySettings() {
  restoreDisplaySettings();
  applyDisplaySettings();
  for (const [id, key] of [['sidebar', 'sidebarCollapsed'], ['map', 'mapCollapsed']]) {
    $(`#toggle-${id}`).addEventListener('click', () => {
      displaySettings[key] = !displaySettings[key];
      saveDisplaySettings();
    });
  }
  $('#font-size').addEventListener('input', event => changeFontSize(Number(event.target.value)));
  $('#font-smaller').addEventListener('click', () => changeFontSize(displaySettings.fontSize - 2));
  $('#font-larger').addEventListener('click', () => changeFontSize(displaySettings.fontSize + 2));
  $('#font-reset').addEventListener('click', () => changeFontSize(displayDefaults.fontSize));
}

initDisplaySettings();
$('#search').addEventListener('input', renderSessions);
window.addEventListener('hashchange', () => selectSession(location.hash.slice(1)));
$('#provider').addEventListener('change', event => {
  app.provider = event.target.value;
  try { localStorage.setItem('mastery-provider', app.provider); } catch {}
  if (app.detail) syncControls(app.detail);
});
loadProviders();
poll();
