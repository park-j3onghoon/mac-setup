const imageDrafts = new Map();
const imageReads = new Map();
const storedImageUrls = new Map();

function imageDraftKey(target) { return `${app.current}:${target}`; }
function hasImages(target) { return Boolean(imageDrafts.get(imageDraftKey(target))?.length); }

function renderSavedImages(images) {
  return (images || []).map(image => `<img class="answer-image"
    data-saved-image="${escapeHtml(image.job_id + '/' + image.id)}"
    alt="${escapeHtml(image.name || '첨부한 이미지')}">`).join('');
}

function renderImageDrafts(target) {
  return (imageDrafts.get(imageDraftKey(target)) || []).map((image, index) => {
    const preview = image.existing ? renderSavedImages([image.existing]) :
      `<img class="answer-image" src="${escapeHtml(image.data_url)}" alt="${escapeHtml(image.name)}">`;
    return `<div class="image-draft">${preview}<button type="button" class="secondary"
      data-image-remove="${index}" data-image-target="${escapeHtml(target)}">이미지 삭제</button></div>`;
  }).join('');
}

function renderImageInput(target) {
  return `<div class="image-controls"><input id="images-${escapeHtml(target)}" type="file" hidden
    data-image-file="${escapeHtml(target)}" accept="image/png,image/jpeg,image/webp" multiple>
    <button type="button" class="secondary" data-image-add="${escapeHtml(target)}">이미지 첨부</button>
    <small class="subtle">스크린샷 붙여넣기 가능 · 최대 3개</small></div>
    <div class="image-drafts" data-image-drafts="${escapeHtml(target)}">${renderImageDrafts(target)}</div>`;
}

function readImageFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('이미지를 읽지 못했습니다. 다시 첨부해 주세요.'));
    reader.readAsDataURL(file);
  });
}

async function addImageFiles(target, files) {
  if (app.sending) return notify('전송이 끝난 뒤 이미지를 첨부해 주세요.');
  const key = imageDraftKey(target);
  imageReads.set(key, (imageReads.get(key) || 0) + 1);
  const decoded = [];
  try {
    for (const file of files) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 6 * 1024 * 1024) {
        throw new Error('6MB 이하의 PNG·JPEG·WebP 이미지를 첨부해 주세요.');
      }
      const dataUrl = await readImageFile(file);
      decoded.push({name: file.name || '스크린샷.png', mime_type: file.type, data_url: dataUrl,
        data_base64: dataUrl.slice(dataUrl.indexOf(',') + 1)});
    }
    const current = imageDrafts.get(key) || [];
    if (current.length + decoded.length > 3) throw new Error('이미지는 최대 3개까지 첨부할 수 있습니다.');
    imageDrafts.set(key, [...current, ...decoded]);
    if (key === imageDraftKey(target)) refreshImageDrafts(target);
  } catch (error) { notify(error.message); }
  finally {
    const remaining = imageReads.get(key) - 1;
    if (remaining) imageReads.set(key, remaining);
    else imageReads.delete(key);
  }
}

function refreshImageDrafts(target) {
  document.querySelectorAll('[data-image-drafts]').forEach(area => {
    if (area.dataset.imageDrafts === target) area.innerHTML = renderImageDrafts(target);
  });
  bindImageControls();
  hydrateStoredImages();
}

function bindImagePaste(input, target) {
  input.addEventListener('paste', event => {
    const files = [...(event.clipboardData?.items || [])]
      .filter(item => item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
    if (!files.length) return;
    event.preventDefault();
    addImageFiles(target, files);
  });
}

function bindImageControls() {
  document.querySelectorAll('[data-image-add]').forEach(button => {
    button.onclick = () => document.getElementById(`images-${button.dataset.imageAdd}`).click();
  });
  document.querySelectorAll('[data-image-file]').forEach(input => {
    input.onchange = () => { addImageFiles(input.dataset.imageFile, [...input.files]); input.value = ''; };
  });
  document.querySelectorAll('[data-image-remove]').forEach(button => {
    button.onclick = () => {
      const target = button.dataset.imageTarget;
      const drafts = [...(imageDrafts.get(imageDraftKey(target)) || [])];
      drafts.splice(Number(button.dataset.imageRemove), 1);
      imageDrafts.set(imageDraftKey(target), drafts);
      refreshImageDrafts(target);
    };
  });
}

function imagePayload(targets) {
  return targets.flatMap(target => (imageDrafts.get(imageDraftKey(target)) || []).map(image => {
    if (image.existing) return {target, name: image.name, existing: image.existing};
    return {target, name: image.name, mime_type: image.mime_type, data_base64: image.data_base64};
  }));
}

function restoreImageDrafts(sessionId, target, images) {
  imageDrafts.set(`${sessionId}:${target}`, images.map(image => ({name: image.name, existing: image})));
}

async function fetchStoredImage(key) {
  let response = await fetch(`/api/images/${key}`, {headers: {'X-Study-Token': connectionToken}});
  if (response.status === 403) {
    await api('/api/sessions');
    response = await fetch(`/api/images/${key}`, {headers: {'X-Study-Token': connectionToken}});
  }
  if (!response.ok) throw new Error('첨부 이미지를 불러오지 못했습니다.');
  return URL.createObjectURL(await response.blob());
}

function hydrateStoredImages() {
  document.querySelectorAll('[data-saved-image]').forEach(async image => {
    const key = image.dataset.savedImage;
    if (!storedImageUrls.has(key)) storedImageUrls.set(key, fetchStoredImage(key));
    image.removeAttribute('data-saved-image');
    try {
      const url = await storedImageUrls.get(key);
      if (image.isConnected) image.src = url;
    } catch (error) { storedImageUrls.delete(key); image.alt = error.message; }
  });
}
