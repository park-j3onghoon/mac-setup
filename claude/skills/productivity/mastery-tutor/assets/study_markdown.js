/* Local Markdown rendering. Model HTML never runs in the study page. */
function escapeMarkup(value) {
  return String(value ?? '').replace(/[&<>"']/g, char =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}

const studyMarkdown = new marked.Marked({gfm: true, breaks: true, renderer: {
  html: token => escapeMarkup(token.text),
  image: token => escapeMarkup(token.text),
  link({href, tokens}) {
    const label = this.parser.parseInline(tokens);
    if (!/^https?:\/\//i.test(href)) return label;
    return `<a href="${escapeMarkup(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  },
  code(token) {
    if (!/^html-diagram(?:\s|$)/.test(token.lang || '')) return false;
    const fence = token.raw.match(/^ {0,3}(`{3,}|~{3,})/);
    const close = fence && new RegExp(`\\n {0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
    if (!close?.test(token.raw)) return false;
    const height = Number(token.lang.match(/height=(\d+)/)?.[1] || 320);
    return `<pre class="diagram-source" data-diagram-height="${Math.min(720, Math.max(160, height))}">` +
      `<code>${escapeMarkup(token.text)}</code></pre>`;
  },
}});

function renderMarkdown(value) {
  if (!DOMPurify.isSupported) return escapeMarkup(value);
  return DOMPurify.sanitize(studyMarkdown.parse(String(value ?? '')), {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a'],
    ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class', 'start', 'align', 'data-diagram-height'],
    ALLOW_DATA_ATTR: false,
  });
}

function diagramDocument(source) {
  const fragment = DOMPurify.sanitize(source, {
    USE_PROFILES: {html: true, svg: true},
    FORBID_TAGS: ['a', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed',
      'img', 'image', 'video', 'audio', 'foreignobject', 'animate', 'animatemotion', 'animatetransform',
      'animatecolor', 'set', 'discard', 'style', 'meta', 'link', 'base'],
    FORBID_ATTR: ['autofocus', 'tabindex'],
    RETURN_DOM_FRAGMENT: true,
  });
  fragment.querySelectorAll('[style]').forEach(element => {
    element.style.setProperty('animation', 'none', 'important');
    element.style.setProperty('transition', 'none', 'important');
  });
  const container = document.createElement('div');
  container.append(fragment);
  const body = container.innerHTML;
  const policy = "default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'";
  const fontSize = document.documentElement.style.fontSize || '22px';
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="${policy}">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{margin:12px;color:#263d43;background:#fffdf7;font:${fontSize}/1.65 system-ui,sans-serif}
    *{box-sizing:border-box}svg{max-width:100%;height:auto}pre{white-space:pre-wrap}</style>
    </head><body>${body}</body></html>`;
}

function mountStudyDiagrams() {
  document.querySelectorAll('pre.diagram-source').forEach(source => {
    const figure = document.createElement('figure');
    figure.className = 'study-diagram';
    const caption = document.createElement('figcaption');
    caption.textContent = '설명 그림';
    const frame = document.createElement('iframe');
    frame.title = '설명을 돕는 그림';
    frame.setAttribute('sandbox', '');
    frame.setAttribute('referrerpolicy', 'no-referrer');
    frame.style.height = `${Number(source.dataset.diagramHeight) || 320}px`;
    frame.srcdoc = diagramDocument(source.textContent);
    figure.append(caption, frame);
    source.replaceWith(figure);
  });
}
