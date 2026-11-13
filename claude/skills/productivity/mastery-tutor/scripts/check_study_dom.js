async function checkStudyDom() {
  // Run with chrome-devtools evaluate_script on a dedicated background study tab. No submissions.
  const checks = [];
  const check = (name, condition) => {
    if (!condition) throw new Error(name);
    checks.push(name);
  };
  function checkMarkdown() {
    const node = document.createElement('div');
    node.innerHTML = renderMarkdown('# 제목\n\n| A | B |\n|---|---|\n| 1 | **2** |\n\n' +
      '1. 첫째\n   - 안쪽\n\n```html\n<div>코드</div>\n```');
    check('table', node.querySelectorAll('table td').length === 2);
    check('nested lists', Boolean(node.querySelector('ol ul')));
    check('heading', node.querySelector('h1')?.textContent === '제목');
    check('HTML code stays text', node.querySelector('pre code')?.textContent.includes('<div>코드</div>'));
    node.innerHTML = renderMarkdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n' +
      '[x](javascript:alert(1)) [safe](https://example.com)');
    check('raw HTML inert', !node.querySelector('script,img'));
    check('link allowlist', node.querySelectorAll('a').length === 1);
    check('safe external link', node.querySelector('a')?.rel.includes('noopener'));
    check('unfinished diagram stays code', !renderMarkdown('```html-diagram\n<div>x</div>')
      .includes('class="diagram-source"'));
  }
  function checkDiagramPolicy() {
    const input = '<style>@keyframes a{to{opacity:0}}</style><svg onload="alert(1)">' +
      '<animateMotion/><animateTransform/><animateColor/><animate/><set/>' +
      '<a href="https://example.com"><text>그림</text></a></svg>' +
      '<div style="animation:a 1s infinite!important;transition:all 1s!important">정적</div>' +
      '<iframe src="https://example.com"></iframe><form><input autofocus></form><script>alert(1)</script>';
    const parsed = new DOMParser().parseFromString(diagramDocument(input), 'text/html');
    check('diagram scripts removed', !parsed.querySelector('script,[onload]'));
    check('diagram external controls removed', !parsed.querySelector('iframe,a,form,input'));
    const animations = parsed.querySelector('animateMotion,animateTransform,animateColor,animate,set');
    check('SVG animations removed', !animations);
    check('only trusted stylesheet', parsed.querySelectorAll('style').length === 1);
    check('CSS animation disabled', parsed.querySelector('div').style.animationName === 'none');
    check('CSS transition disabled', parsed.querySelector('div').style.transitionProperty === 'none');
    const policy = parsed.querySelector('meta[http-equiv]').content;
    check('CSP denies network', policy.includes("default-src 'none'"));
    check('SVG retained', Boolean(parsed.querySelector('svg text')));
  }
  async function checkMountedDiagram() {
    const host = document.createElement('section');
    host.innerHTML = renderMarkdown('```html-diagram height=220\n' +
      '<svg viewBox="0 0 200 80"><text x="10" y="30">그림</text></svg>\n```');
    document.body.append(host);
    try {
      mountStudyDiagrams();
      const frame = host.querySelector('iframe');
      check('iframe rendered', Boolean(frame));
      check('empty sandbox', frame.getAttribute('sandbox') === '');
      check('requested height', frame.style.height === '220px');
      await new Promise(resolve => { frame.onload = resolve; setTimeout(resolve, 500); });
      check('opaque origin', frame.contentDocument === null);
    } finally { host.remove(); }
  }
  checkMarkdown();
  checkDiagramPolicy();
  await checkMountedDiagram();
  return {passed: checks.length, checks};
}
