const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../assets/study.js');
const source = fs.readFileSync(sourcePath, 'utf8').replace(/\nloadProviders\(\);/, '')
  .replace(/poll\(\);\s*$/, '');
const detail = {
  id: 'next', revision: 1, topic: '시험 공부', scope: '', status: 'active',
  progress: {percent: 25, passed: 1, total: 4}, pending_count: 0, review_count: 0,
  grading_count: 0, questions: [], blocks: [], web_owned: false, job: null,
};

function response(status, body) {
  return {status, ok: status < 400, json: async () => JSON.parse(JSON.stringify(body))};
}

function browser(fetch) {
  const elements = new Map();
  const timers = new Map();
  const collections = new Map();
  const eventSignals = [];
  const drafts = new Map([['mastery:old:q1', '작성 중인 답']]);
  const element = selector => {
    if (!elements.has(selector)) {
      elements.set(selector, {textContent: '', innerHTML: '', value: '', style: {},
        addEventListener() {}, setAttribute() {}});
    }
    return elements.get(selector);
  };
  const context = vm.createContext({
    STUDY_TOKEN: 'expired', AbortController, TextDecoder, crypto: require('node:crypto'),
    marked: require('../assets/vendor/marked/marked.umd.js'), DOMPurify: {isSupported: false},
    fetch: (url, options) => {
      if (!url.startsWith('/api/events/')) return fetch(url, options);
      eventSignals.push(options.signal);
      return new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new Error('aborted')));
      });
    },
    document: {querySelector: element, querySelectorAll: selector => collections.get(selector) || [],
      getElementById: id => element(`#${id}`),
      documentElement: {style: {}, classList: {toggle() {}}}},
    window: {addEventListener() {}}, history: {replaceState() {}}, location: {hash: ''},
    localStorage: {getItem: key => drafts.get(key), setItem: (key, value) => drafts.set(key, value),
      removeItem: key => drafts.delete(key)},
    setTimeout: (callback, delay) => { const id = Symbol(); timers.set(id, {callback, delay}); return id; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../assets/study_markdown.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../assets/study_images.js'), 'utf8'), context);
  vm.runInContext(source, context);
  return {context, element, timers, drafts, collections, eventSignals,
    run: code => vm.runInContext(code, context)};
}

test('each unanswered question has its own submission control', () => {
  const page = browser(async () => response(200, {}));
  const html = page.run(`renderQuestion({id: 'q1', number: 1, prompt: '질문', status: 'pending'})`);
  assert.match(html, /data-submit-answer="q1"/);
  const answered = page.run(`renderQuestion({id: 'q1', number: 1, status: 'answer_saved', answer: '답'})`);
  assert.doesNotMatch(answered, /data-submit-answer/);
});

test('sending one answer preserves the other draft and disables all submit buttons while busy', async () => {
  const payloads = [];
  let finish;
  const page = browser(async (url, options) => {
    if (url === '/api/submit') {
      payloads.push(JSON.parse(options.body));
      return new Promise(resolve => { finish = resolve; });
    }
    return response(200, url === '/api/sessions' ? {sessions: [detail]} : detail);
  });
  page.run(`app.current = 'next'; app.detail = ${JSON.stringify(detail)}`);
  page.element('#answer-q1').value = '  첫 답\n그대로  ';
  page.element('#answer-q2').value = '다른 답 초안';
  page.drafts.set('mastery:next:q1', '  첫 답\n그대로  ');
  page.drafts.set('mastery:next:q2', '다른 답 초안');
  const buttons = [{disabled: false}, {disabled: false}];
  page.collections.set('[data-submit-answer]', buttons);
  const sending = page.run("submitAnswer('q1')");
  assert.ok(buttons.every(button => button.disabled));
  await page.run("submitAnswer('q2')");
  assert.equal(payloads.length, 1);
  assert.deepEqual(payloads[0].answers, {q1: '  첫 답\n그대로  '});
  finish(response(202, {id: 'one-answer', status: 'queued'}));
  await sending;
  assert.equal(page.drafts.has('mastery:next:q1'), false);
  assert.equal(page.drafts.get('mastery:next:q2'), '다른 답 초안');
});

test('an empty individual answer does not submit other filled answers', async () => {
  const page = browser(async () => { throw new Error('must not send'); });
  page.element('#answer-q1').value = '  ';
  page.element('#answer-q2').value = '다른 답';
  await page.run("submitAnswer('q1')");
  assert.match(page.element('#toast').textContent, /이 문제의 답/);
});

test('revised question gets a fresh draft while unrelated draft survives refresh', async () => {
  const updated = {...detail, revision: 2, pending_count: 2, questions: [
    {id: 'q1-revised', number: 3, prompt: '바꾼 질문', status: 'pending'},
    {id: 'q2', number: 2, prompt: '유지한 질문', status: 'pending'},
  ]};
  const page = browser(async () => response(200, updated));
  page.drafts.set('mastery:next:q1', '원래 질문의 초안');
  page.drafts.set('mastery:next:q2', '다른 답 초안');
  await page.run("selectSession('next')");
  const html = page.element('#content').innerHTML;
  assert.match(html, /바꾼 질문/);
  assert.match(html, /다른 답 초안/);
  assert.doesNotMatch(html, /원래 질문의 초안/);
  assert.equal(page.drafts.get('mastery:next:q1'), '원래 질문의 초안');
});

test('expired connection recovers while opening a different topic', async () => {
  const calls = [];
  const page = browser(async (url, options) => {
    calls.push(url);
    if (url === '/api/connection') return response(200, {token: 'current'});
    if (options.headers['X-Study-Token'] !== 'current') return response(403, {error: '연결 만료'});
    return response(200, detail);
  });
  await page.run("app.detail = {id: 'old'}; selectSession('next')");
  assert.match(page.element('#content').innerHTML, /시험 공부/);
  assert.doesNotMatch(page.element('#content').innerHTML, /불러오고 있습니다/);
  assert.deepEqual(calls, ['/api/sessions/next', '/api/connection', '/api/sessions/next']);
  assert.equal(page.drafts.get('mastery:old:q1'), '작성 중인 답');
});

test('failed topic selection replaces loading with an actionable error', async () => {
  const page = browser(async () => response(503, {error: '연결 실패'}));
  await page.run("app.detail = {id: 'old'}; selectSession('next')");
  assert.match(page.element('#content').innerHTML, /연결 실패/);
  assert.match(page.element('#content').innerHTML, /다시 불러오기/);
  assert.doesNotMatch(page.element('#content').innerHTML, /불러오고 있습니다/);
});

test('a stalled request stops loading after the timeout', async () => {
  const page = browser((url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    });
  }));
  const pending = page.run("selectSession('next')");
  const timer = [...page.timers.values()].find(item => item.delay === 8000);
  timer.callback();
  await pending;
  assert.match(page.element('#content').innerHTML, /8초 동안 응답이 없습니다/);
  assert.equal(page.timers.size, 0);
});

test('render failures do not cache a revision that has never been shown', async () => {
  const page = browser(async () => response(200, detail));
  page.run(`const originalRender = render;
    let attempts = 0;
    render = value => { if (++attempts === 1) throw new Error('표시 실패'); originalRender(value); };`);
  await page.run("selectSession('next')");
  assert.match(page.element('#content').innerHTML, /표시 실패/);
  await page.run('refreshDetail()');
  assert.match(page.element('#content').innerHTML, /시험 공부/);
  assert.equal(page.run('attempts'), 2);
});

test('poll waits for a response before scheduling another refresh', async () => {
  let finish;
  const page = browser(() => new Promise(resolve => { finish = resolve; }));
  const pending = page.run('poll()');
  assert.equal([...page.timers.values()].filter(timer => timer.delay === 2000).length, 0);
  finish(response(200, {sessions: []}));
  await pending;
  assert.equal([...page.timers.values()].filter(timer => timer.delay === 2000).length, 1);
});

test('elapsed time and question status refresh without replacing an unfinished answer', async () => {
  const started = Date.parse('2026-11-06T00:00:00Z');
  const pending = {...detail, grading_count: 1,
    questions: [{id: 'q1', status: 'answer_saved', answer: '제출 답'}],
    job: {id: 'live-1', status: 'running', provider: 'codex', created_at: new Date(started).toISOString()},
  };
  const page = browser(async () => response(200, pending));
  page.run(`Date.now = () => ${started + 10000}`);
  await page.run("selectSession('next')");
  const content = page.element('#content').innerHTML;
  page.element('#answer-q2').value = '작성 중인 다른 답';
  const badge = {dataset: {questionStatus: 'q1'}, textContent: ''};
  page.collections.set('[data-question-status]', [badge]);
  page.run(`Date.now = () => ${started + 12000}`);
  await page.run('refreshDetail()');
  assert.match(page.element('#job-status').innerHTML, /12초 경과/);
  assert.match(page.element('#job-status').innerHTML, /수신 시점 미확인/);
  assert.equal(page.run('app.statusCheckedAt'), started + 12000);
  assert.equal(badge.textContent, '응답 대기');
  pending.job.status = 'saving';
  await page.run('refreshDetail()');
  assert.equal(badge.textContent, '결과 저장 중');
  assert.equal(page.element('#content').innerHTML, content);
  assert.equal(page.element('#answer-q2').value, '작성 중인 다른 답');
});

test('completed request with ungraded answers is waiting rather than still running', () => {
  const page = browser(async () => response(200, {}));
  const pending = {...detail, grading_count: 2, job: {status: 'complete'}};
  const html = page.run(`renderJob(${JSON.stringify(pending)})`);
  assert.match(html, /미채점 답안 2개 · 다음 채점 대기/);
  assert.match(html, /이어서 공부하기/);
  assert.doesNotMatch(html, /경과|AI가 요청을 처리/);
  assert.equal(page.run(`questionStatus({status: 'answer_saved'}, ${JSON.stringify(pending)})`),
    '다음 채점 대기');
});

test('failed refresh keeps the last confirmation time and recovery clears the warning', async () => {
  const pending = {...detail, grading_count: 1, job: {id: 'live-1', status: 'running'},
    questions: [{id: 'q1', status: 'answer_saved'}]};
  let offline = false;
  const page = browser(async (url) => {
    if (offline) throw new Error('연결 실패');
    return response(200, url === '/api/sessions' ? {sessions: [pending]} : pending);
  });
  page.run('Date.now = () => 10000');
  await page.run("selectSession('next')");
  offline = true;
  page.run('Date.now = () => 12000');
  await page.run('refresh()');
  assert.equal(page.run('app.statusCheckedAt'), 10000);
  assert.match(page.element('#job-status').innerHTML, /연결 확인 필요/);
  offline = false;
  await page.run('refresh()');
  assert.equal(page.run('app.statusCheckedAt'), 12000);
  assert.doesNotMatch(page.element('#job-status').innerHTML, /연결 확인 필요/);
});

test('provider selection does not relabel an earlier response', () => {
  const page = browser(async () => response(200, {}));
  page.run("app.provider = 'codex'");
  const html = page.run(`renderMessage({id: 'job-1', provider: 'claude', status: 'complete',
    message: '질문입니다.', reply: '답변입니다.'})`);
  assert.match(html, /provider-claude/);
  assert.doesNotMatch(html, /provider-codex/);
});

test('failed answer retry controls belong only to the associated question', () => {
  const page = browser(async () => response(200, {}));
  const failed = {...detail, questions: [{id: 'q1', status: 'answer_saved'}],
    job: {id: 'failed-q1', status: 'failed', error: 'timeout', answer_ids: ['q1'], attempt: 3}};
  const first = page.run(`renderQuestion({id: 'q1', status: 'answer_saved'}, ${JSON.stringify(failed)})`);
  const other = page.run(`renderQuestion({id: 'q2', status: 'answer_saved'}, ${JSON.stringify(failed)})`);
  assert.match(first, /data-retry-job="failed-q1"/);
  assert.match(first, /요청 재시도/);
  assert.doesNotMatch(other, /data-retry-job/);
  assert.doesNotMatch(page.run(`renderJob(${JSON.stringify(failed)})`), /id="retry"/);
});

test('automatic retry countdown updates in the question while duplicate controls stay disabled', () => {
  const page = browser(async () => response(200, {}));
  const retry = {...detail, questions: [{id: 'q1', status: 'answer_saved'}],
    job: {id: 'retry-q1', status: 'retry_wait', answer_ids: ['q1'],
      attempt: 1, max_attempts: 3, retry_at: new Date(15000).toISOString()}};
  const button = {disabled: false};
  page.collections.set('[data-submit-answer]', [button]);
  page.run(`Date.now = () => 10000; app.detail = ${JSON.stringify(retry)}; syncControls(app.detail)`);
  assert.equal(button.disabled, true);
  const before = page.run(`renderQuestionRetry({id: 'q1', status: 'answer_saved'}, app.detail)`);
  assert.match(before, /5초 뒤 자동 재시도/);
  assert.match(before, /2\/3번째 시도/);
  assert.doesNotMatch(before, /data-retry-job/);
  page.run('Date.now = () => 13000');
  assert.match(page.run(`renderQuestionRetry({id: 'q1', status: 'answer_saved'}, app.detail)`), /2초 뒤/);
});

test('an unrelated general question does not hide a failed answer retry', () => {
  const page = browser(async () => response(200, {}));
  const failed = {id: 'failed-q1', status: 'failed', answer_ids: ['q1'], error: '통신 오류'};
  const general = {id: 'general-question', status: 'complete', answer_ids: []};
  const updated = {...detail, job: general, conversation: [failed, general]};
  const html = page.run(`renderQuestion({id: 'q1', status: 'answer_saved'}, ${JSON.stringify(updated)})`);
  assert.match(html, /data-retry-job="failed-q1"/);
  assert.match(html, /요청 실패/);
});

test('question retry sends the saved request ID without resubmitting answers', async () => {
  const payloads = [];
  const page = browser(async (url, options) => {
    if (url === '/api/submit') {
      payloads.push(JSON.parse(options.body));
      return response(202, {id: 'retry-new', status: 'queued'});
    }
    return response(200, url === '/api/sessions' ? {sessions: [detail]} : detail);
  });
  page.run(`app.current = 'next'; app.detail = ${JSON.stringify(detail)}`);
  const button = {dataset: {retryJob: 'failed-q1'}};
  page.collections.set('[data-retry-job]', [button]);
  page.run('bindQuestionRetryEvents()');
  page.run('bindQuestionRetryEvents()');
  await button.onclick();
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].retry_job_id, 'failed-q1');
  assert.deepEqual(payloads[0].answers, {});
});

test('request failure adds a retry control to the question without replacing other drafts', async () => {
  const pending = {...detail, questions: [{id: 'q1', status: 'answer_saved'}],
    job: {id: 'job-q1', status: 'running', answer_ids: ['q1']}};
  const page = browser(async () => response(200, pending));
  await page.run("selectSession('next')");
  const area = {dataset: {questionRetry: 'q1'}, innerHTML: ''};
  page.collections.set('[data-question-retry]', [area]);
  page.element('#answer-q2').value = '다른 답 초안';
  page.run(`receiveJob('next', {id: 'job-q1', status: 'failed', answer_ids: ['q1'], error: '실패'})`);
  assert.match(area.innerHTML, /data-retry-job="job-q1"/);
  assert.equal(page.element('#answer-q2').value, '다른 답 초안');
});

test('recovered historical failure is collapsed and has no failure styling or retry button', () => {
  const page = browser(async () => response(200, {}));
  const html = page.run(`renderMessage({id: 'old-failure', status: 'failed',
    resolved_by: 'later-success', reply_preview: '이전 응답', error: '이전 저장 오류'})`);
  assert.match(html, /이전 시도 · 이후 재시도 완료/);
  assert.match(html, /<details[^>]*>\s*<summary>이전 실패 기록 보기/);
  assert.doesNotMatch(html, /assistant failed|data-retry-job|<details[^>]*\bopen/);
});

test('unresolved failed response puts its reason and retry before the uncommitted reply', () => {
  const page = browser(async () => response(200, {}));
  const html = page.run(`renderMessage({id: 'real-failure', status: 'failed',
    error: '연결 실패', reply_preview: '미반영 응답'})`);
  assert.match(html, /data-retry-job="real-failure"/);
  assert.ok(html.indexOf('연결 실패') < html.indexOf('미반영 응답'));
  assert.match(html, /<details[^>]*>\s*<summary>저장되지 않은 응답 보기/);
});

test('opened historical records survive polling and new replies', () => {
  const page = browser(async () => response(200, {}));
  const history = {dataset: {jobHistory: 'old'}, open: true};
  page.collections.set('[data-job-history]', [history]);
  const current = {...detail, conversation: [{id: 'old', status: 'failed', resolved_by: 'new'}]};
  page.run(`app.detail = ${JSON.stringify(current)}; updateConversation(app.detail)`);
  page.run('updateConversation(app.detail)');
  assert.match(page.element('#conversation').innerHTML, /data-job-history="old" open/);
  page.run('render(app.detail)');
  assert.match(page.element('#content').innerHTML, /data-job-history="old" open/);
  page.run("app.detail.conversation.push({id: 'new', status: 'responding', reply_preview: '새 응답'});");
  page.run('updateConversation(app.detail)');
  assert.match(page.element('#conversation').innerHTML, /data-job-history="old" open/);
  history.open = false;
  page.run('updateConversation(app.detail)');
  assert.doesNotMatch(page.element('#conversation').innerHTML, /data-job-history="old" open/);
});

test('activity uses actual receipt time rather than the last page refresh', () => {
  const page = browser(async () => response(200, {}));
  page.run('Date.now = () => 43000; app.statusCheckedAt = 43000');
  const job = {status: 'running', created_at: new Date(0).toISOString(), activity_count: 2,
    last_activity_at: new Date(31000).toISOString()};
  assert.equal(page.run(`activityText(${JSON.stringify(job)})`), '43초 경과\n마지막 수신 12초 전');
  page.run('Date.now = () => 45000; app.statusCheckedAt = 45000');
  assert.match(page.run(`activityText(${JSON.stringify(job)})`), /마지막 수신 14초 전/);
});

test('active answer shows compact receipt info and public preview without a duplicate banner', () => {
  const page = browser(async () => response(200, {}));
  const question = {id: 'q11', number: 11, status: 'answer_saved', answer: '내 답'};
  const active = {...detail, questions: [question], job: {id: 'live', status: 'responding',
    answer_ids: ['q11'], reply_preview: '공개 답변', state_json: 'SECRET'}};
  const html = page.run(`renderQuestion(${JSON.stringify(question)}, ${JSON.stringify(active)})`);
  assert.match(html, /data-question-activity="q11"/);
  assert.match(html, /도착한 답변 · 저장 전/);
  assert.match(html, /공개 답변/);
  assert.doesNotMatch(html, /SECRET/);
  assert.equal(page.run(`renderJob(${JSON.stringify(active)})`), '');
});

test('conversation retains the submitted answer even after the question has moved on', () => {
  const page = browser(async () => response(200, {}));
  const html = page.run(`renderMessage({id: 'saved', status: 'complete', answer_count: 1,
    submitted_answers: [{id: 'q11', number: 11, answer: '2번이야. 아직 잘 모르겠어. <script>'}]})`);
  assert.match(html, /QUESTION 11 · 제출한 답/);
  assert.match(html, /2번이야. 아직 잘 모르겠어./);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /답안 1개를 제출했습니다/);
});

test('streamed replies update only the conversation and preserve the input', async () => {
  const page = browser(async () => response(200, detail));
  await page.run("selectSession('next')");
  page.element('#ask').value = '작성 중인 질문';
  page.run(`receiveJob('next', {id: 'live-1', provider: 'claude', status: 'responding',
    message: '직전 질문', reply_preview: '도착한 답변'})`);
  assert.match(page.element('#conversation').innerHTML, /도착한 답변/);
  assert.match(page.element('#conversation').innerHTML, /Claude/);
  assert.equal(page.element('#ask').value, '작성 중인 질문');
  assert.equal(page.element('#ask-submit').disabled, true);
});

test('overlapping selections of the same topic keep only one event connection', async () => {
  const responses = [];
  const page = browser(() => new Promise(resolve => responses.push(resolve)));
  const first = page.run("selectSession('next')");
  const second = page.run("selectSession('next')");
  responses[1](response(200, detail));
  await second;
  responses[0](response(200, detail));
  await first;
  assert.equal(page.eventSignals.length, 2);
  assert.equal(page.eventSignals.filter(signal => !signal.aborted).length, 1);
  page.run('app.events.abort()');
  assert.equal(page.eventSignals.filter(signal => !signal.aborted).length, 0);
});

function historyJob(number) {
  return {id: `job-${number}`, created_at: `2026-11-${String(number + 1).padStart(2, '0')}`,
    status: 'complete', reply: `응답 ${number}`, answer_ids: []};
}

test('latest pair loads older on demand and keeps loaded history during polling', async () => {
  const latest = historyJob(6);
  const current = {...detail, job: latest, conversation: [latest], older_before: latest.id};
  const calls = [];
  const page = browser(async url => {
    calls.push(url);
    if (url.includes('/api/conversations/')) return response(200, {
      conversation: [1, 2, 3, 4, 5].map(historyJob), older_before: 'job-1'});
    return response(200, current);
  });
  await page.run("selectSession('next')");
  assert.equal(page.run('app.detail.conversation.length'), 1);
  assert.equal(calls.filter(url => url.includes('/api/conversations/')).length, 0);
  page.element('#answer-q2').value = '다른 답 초안';
  await page.run('loadOlderConversation()');
  assert.equal(page.run('app.detail.conversation.length'), 6);
  await page.run('refreshDetail()');
  assert.equal(page.run('app.detail.conversation.length'), 6);
  assert.equal(page.element('#answer-q2').value, '다른 답 초안');
  page.run('collapseConversation()');
  assert.equal(page.run('app.detail.conversation.length'), 1);
  assert.equal(page.run('app.detail.older_before'), 'job-6');
});

test('new response during history loading does not lose the previous latest pair', async () => {
  let finish;
  const original = historyJob(6);
  const current = {...detail, job: original, conversation: [original], older_before: original.id};
  const page = browser(async url => url.includes('/api/conversations/') ?
    new Promise(resolve => { finish = resolve; }) : response(200, current));
  await page.run("selectSession('next')");
  const loading = page.run('loadOlderConversation()');
  await page.run('loadOlderConversation()');
  page.run(`receiveJob('next', ${JSON.stringify({...historyJob(7), status: 'running'})})`);
  assert.equal(page.run('app.detail.older_before'), 'job-7');
  finish(response(200, {conversation: [1, 2, 3, 4, 5].map(historyJob), older_before: 'job-1'}));
  await loading;
  assert.deepEqual(JSON.parse(page.run('JSON.stringify(app.detail.conversation.map(job => job.id))')),
    [1, 2, 3, 4, 5, 6, 7].map(number => `job-${number}`));
});

test('history load from an old selection cannot alter a newly selected topic', async () => {
  let finish;
  const latest = historyJob(6);
  const current = {...detail, job: latest, conversation: [latest], older_before: latest.id};
  const page = browser(async url => url.includes('/api/conversations/') ?
    new Promise(resolve => { finish = resolve; }) : response(200, current));
  await page.run("selectSession('next')");
  const loading = page.run('loadOlderConversation()');
  page.run(`app.current = 'other'; app.detail = {...app.detail, id: 'other', conversation: []};
    app.conversationState = null; mergeConversation(app.detail)`);
  finish(response(200, {conversation: [historyJob(1)], older_before: null}));
  await loading;
  assert.equal(page.run('app.detail.id'), 'other');
  assert.equal(page.run('app.detail.conversation.length'), 0);
});

test('question retry survives when its failed conversation is not loaded', () => {
  const page = browser(async () => response(200, {}));
  const failed = {id: 'old', status: 'failed', answer_ids: ['q1']};
  const current = {...detail, job: historyJob(6), conversation: [historyJob(6)], question_jobs: {q1: failed}};
  const html = page.run(`renderQuestion({id: 'q1', status: 'answer_saved'}, ${JSON.stringify(current)})`);
  assert.match(html, /data-retry-job="old"/);
});

test('Enter inserts a line while Command-Enter submits only its answer and ignores IME', () => {
  const page = browser(async () => response(200, {}));
  const handlers = {};
  page.collections.set('[data-answer]', [{dataset: {answer: 'q2'},
    addEventListener: (name, handler) => { handlers[name] = handler; }}]);
  page.run(`app.detail = ${JSON.stringify(detail)}; const submitted = [];
    submitAnswer = id => submitted.push(id); bindDetailEvents()`);
  let prevented = 0;
  const event = {key: 'Enter', metaKey: false, preventDefault: () => { prevented++; }};
  handlers.keydown(event);
  handlers.keydown({...event, metaKey: true, isComposing: true});
  handlers.keydown({...event, metaKey: true, keyCode: 229});
  handlers.keydown({...event, metaKey: true, repeat: true});
  assert.equal(page.run('submitted.length'), 0);
  assert.equal(prevented, 1);
  handlers.keydown({...event, metaKey: true});
  assert.equal(page.run('submitted.join()'), 'q2');
  assert.equal(prevented, 2);
});

test('conversation shortcut sends its own text through the currently selected provider', async () => {
  const payloads = [];
  const page = browser(async (url, options) => {
    if (url === '/api/submit') {
      payloads.push(JSON.parse(options.body));
      return response(202, {id: 'new', status: 'queued'});
    }
    return response(200, url === '/api/sessions' ? {sessions: [detail]} : detail);
  });
  const handlers = {};
  page.element('#ask').addEventListener = (name, listener) => { handlers[name] = listener; };
  page.run(`app.current = 'next'; app.detail = ${JSON.stringify(detail)}; bindDetailEvents()`);
  page.element('#answer-q2').value = '다른 문제의 초안';
  let prevented = 0;
  const event = {key: 'Enter', metaKey: false, preventDefault: () => { prevented++; }};
  for (const provider of ['claude', 'codex']) {
    page.run(`app.provider = '${provider}'`);
    page.element('#ask').value = `첫 줄\n${provider}로 보낼 내용`;
    const previous = payloads.length;
    handlers.keydown(event);
    handlers.keydown({...event, metaKey: true, isComposing: true});
    assert.equal(payloads.length, previous);
    handlers.keydown({...event, metaKey: true});
    await new Promise(setImmediate);
    assert.equal(payloads.length, previous + 1, page.element('#toast').textContent);
    assert.equal(payloads.at(-1).provider, provider);
    assert.equal(payloads.at(-1).message, `첫 줄\n${provider}로 보낼 내용`);
    assert.deepEqual(payloads.at(-1).answers, {});
  }
  assert.equal(prevented, 2);
  assert.equal(page.element('#answer-q2').value, '다른 문제의 초안');
});

test('answer buttons and shortcut hints stay neutral when switching between AI providers', () => {
  const page = browser(async () => response(200, {}));
  const input = page.run(`renderAnswerInput({id: 'q1', number: 1})`);
  assert.match(input, /⌘\+Enter 답변하기/);
  assert.match(input, />답변하기<\/button>/);
  page.element('#ask-submit').textContent = '답변하기';
  for (const provider of ['claude', 'codex']) {
    page.run(`app.provider = '${provider}'; render(${JSON.stringify(detail)})`);
    const html = page.element('#content').innerHTML;
    assert.match(html, /id="ask"[^>]*aria-keyshortcuts="Meta\+Enter"/);
    assert.match(html, /id="ask-submit"[^>]*>답변하기<\/button>/);
    assert.equal(page.element('#ask-submit').textContent, '답변하기');
  }
});

test('empty conversation shortcut and button share the same validation', () => {
  const page = browser(async () => { throw new Error('must not submit'); });
  const handlers = {};
  page.element('#ask-submit').addEventListener = (name, listener) => { handlers[name] = listener; };
  page.run(`app.detail = ${JSON.stringify(detail)}; bindDetailEvents()`);
  page.element('#ask').value = '  ';
  assert.equal(handlers.click, page.run('submitQuestion'));
  page.run('submitQuestion()');
  assert.match(page.element('#toast').textContent, /궁금한 점/);
});

test('one response area follows the submitted question without moving again on every poll', () => {
  const page = browser(async () => response(200, {}));
  const thread = page.element('#conversation-thread');
  thread.parentElement = {};
  const placed = [];
  const cards = ['q1', 'q2'].map(id => ({dataset: {questionCard: id},
    after(node) { placed.push(id); this.nextElementSibling = node; }}));
  page.collections.set('[data-question-card]', cards);
  const update = `positionConversation({job: {answer_ids: ['q2']}})`;
  page.run(update);
  assert.deepEqual(placed, ['q2']);
  page.run(update);
  assert.deepEqual(placed, ['q2']);
  assert.equal(cards[1].nextElementSibling, thread);
});

test('batch responses follow the last related card and archived responses stay in the question area', () => {
  const page = browser(async () => response(200, {}));
  const thread = page.element('#conversation-thread');
  thread.parentElement = {};
  const placed = [];
  const cards = ['q1', 'q2', 'unrelated'].map(id => ({dataset: {questionCard: id},
    after(node) { placed.push(id); this.nextElementSibling = node; }}));
  page.collections.set('[data-question-card]', cards);
  page.run(`positionConversation({job: {answer_ids: ['q2', 'q1']}})`);
  assert.deepEqual(placed, ['q2']);
  page.element('#question-replies').after = node => { placed.push('archived'); };
  page.run(`positionConversation({job: {answer_ids: ['old-question']}})`);
  assert.deepEqual(placed, ['q2', 'archived']);
});

test('general conversation and its processing state are placed below its input', () => {
  const page = browser(async () => response(200, {}));
  const thread = page.element('#conversation-thread');
  thread.parentElement = {};
  const placed = [];
  page.element('#ask-box').after = node => { placed.push(node); };
  page.run(`positionConversation({job: {answer_ids: []}})`);
  assert.equal(placed[0], thread);
  page.run(`render(${JSON.stringify(detail)})`);
  const html = page.element('#content').innerHTML;
  assert.ok(html.indexOf('id="ask-box"') < html.indexOf('id="conversation-thread"'));
  assert.ok(html.indexOf('id="conversation-thread"') < html.indexOf('id="job-status"'));
  assert.equal((html.match(/id="conversation-thread"/g) || []).length, 1);
});

test('older history has separate one-item and all-items controls', async () => {
  const latest = historyJob(3);
  const current = {...detail, job: latest, conversation: [latest], older_before: latest.id};
  const calls = [];
  const page = browser(async url => {
    calls.push(url);
    if (url.endsWith('&all=1')) return response(200, {conversation: [historyJob(0), historyJob(1)],
      older_before: null});
    if (url.includes('/api/conversations/')) return response(200, {conversation: [historyJob(2)],
      older_before: 'job-2'});
    return response(200, current);
  });
  await page.run("selectSession('next')");
  assert.match(page.element('#conversation-tools').innerHTML, /1개 불러오기/);
  assert.match(page.element('#conversation-tools').innerHTML, /전부 불러오기/);
  await page.run('loadOlderConversation()');
  assert.equal(page.run('app.detail.conversation.length'), 2);
  await page.run('loadAllConversation()');
  assert.equal(page.run('app.detail.conversation.length'), 4);
  assert.ok(calls.includes('/api/conversations/next?before=job-2&all=1'));
});

test('image paste and file previews stay attached to their own input', async () => {
  const page = browser(async () => response(200, {}));
  page.run(`app.current = 'next'; readImageFile = async file => 'data:image/png;base64,aW1hZ2U='`);
  const pasteHandlers = {};
  const input = {addEventListener: (name, callback) => { pasteHandlers[name] = callback; }};
  page.context.pasteInput = input;
  page.run("bindImagePaste(pasteInput, 'q1')");
  let prevented = false;
  const file = {type: 'image/png', name: '스크린샷.png', size: 20};
  pasteHandlers.paste({clipboardData: {items: [{type: file.type, getAsFile: () => file}]},
    preventDefault: () => { prevented = true; }});
  await new Promise(setImmediate);
  assert.ok(prevented);
  assert.equal(page.run("hasImages('q1')"), true);
  assert.equal(page.run("hasImages('ask')"), false);
  assert.equal(page.run("imagePayload(['q1'])[0].target"), 'q1');
  assert.match(page.run("renderImageDrafts('q1')"), /스크린샷.png/);
});

test('image-only answer sends just that image and preserves other input attachments', async () => {
  const payloads = [];
  const page = browser(async (url, options) => {
    if (url === '/api/submit') {
      payloads.push(JSON.parse(options.body));
      return response(202, {id: 'image', status: 'queued'});
    }
    return response(200, url === '/api/sessions' ? {sessions: [detail]} : detail);
  });
  page.run(`app.current = 'next'; app.detail = ${JSON.stringify(detail)};
    imageDrafts.set(imageDraftKey('q1'), [{name:'one.png',mime_type:'image/png',data_base64:'abc'}]);
    imageDrafts.set(imageDraftKey('q2'), [{name:'two.png',mime_type:'image/png',data_base64:'def'}]);`);
  await page.run("submitAnswer('q1')");
  assert.deepEqual(payloads[0].answers, {q1: ''});
  assert.equal(payloads[0].images.length, 1);
  assert.equal(payloads[0].images[0].target, 'q1');
  assert.equal(page.run("hasImages('q1')"), false);
  assert.equal(page.run("hasImages('q2')"), true);
});

test('cancelled answer is restored as a draft with its original images', async () => {
  const image = {id: 'image-1', job_id: 'old', mime_type: 'image/png', name: '원본.png'};
  const page = browser(async url => {
    if (url === '/api/cancel') return response(202, {status: 'cancelled', submitted_answers: [
      {id: 'q1', answer: '수정할 원답', images: [image]}]});
    return response(200, url === '/api/sessions' ? {sessions: [detail]} : detail);
  });
  page.run(`app.current = 'next'; app.detail = ${JSON.stringify(detail)}`);
  await page.run("cancelAnswer('job-1')");
  assert.equal(page.drafts.get('mastery:next:q1'), '수정할 원답');
  assert.equal(page.run("imagePayload(['q1'])[0].existing.id"), 'image-1');
  assert.match(page.run("renderCancelAnswer({id:'job',can_cancel:true})"), /답변 취소하기/);
});

test('a general message cancel button does not appear under unrelated questions', () => {
  const page = browser(async () => response(200, {}));
  const general = {...detail, job: {id:'general',status:'complete',answer_ids:[],can_cancel:true}};
  assert.equal(page.run(`renderQuestionCancel({id:'q1'}, ${JSON.stringify(general)})`), '');
});

test('Markdown parses tables, nested lists, headings and fenced code', () => {
  const page = browser(async () => response(200, {}));
  const markdown = '# 제목\n\n| 구분 | 내용 |\n|---|---|\n| 화면 | **정적 파일** |\n\n' +
    '1. 준비\n   - 확인\n\n```html\n<div>예시</div>\n```';
  const html = page.run(`studyMarkdown.parse(${JSON.stringify(markdown)})`);
  for (const tag of ['h1', 'table', 'thead', 'tbody', 'ol', 'ul', 'pre', 'code', 'strong']) {
    assert.match(html, new RegExp(`<${tag}[ >]`));
  }
  assert.match(html, /&lt;div&gt;예시&lt;\/div&gt;/);
});

test('raw HTML and dangerous links are inert while completed diagram fences get an explicit marker', () => {
  const page = browser(async () => response(200, {}));
  const unsafe = '<script>bad()</script>\n\n[x](javascript:alert(1))';
  const html = page.run(`studyMarkdown.parse(${JSON.stringify(unsafe)})`);
  assert.doesNotMatch(html, /<script|href="javascript/);
  const diagram = '```html-diagram height=400\n<svg viewBox="0 0 200 80"></svg>\n```';
  assert.match(page.run(`studyMarkdown.parse(${JSON.stringify(diagram)})`), /class="diagram-source"/);
  assert.doesNotMatch(page.run(`studyMarkdown.parse(${JSON.stringify(diagram.slice(0, -3))})`),
    /class="diagram-source"/);
});
