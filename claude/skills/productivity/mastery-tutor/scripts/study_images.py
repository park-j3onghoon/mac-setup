"""Local screenshot attachments: validate uploads and expose only safe image metadata."""

import base64
import binascii
from pathlib import Path
import uuid

from learning_store import Store, StoreError

MIME_EXTENSIONS = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MAX_IMAGE_BYTES = 6 * 1024 * 1024


def image_path(jobs_directory, metadata):
    job_id = Store.valid_id(metadata.get('job_id'))
    image_id = Store.valid_id(metadata.get('id'))
    extension = MIME_EXTENSIONS.get(metadata.get('mime_type'))
    if not extension:
        raise StoreError('PNG·JPEG·WebP 이미지만 첨부할 수 있습니다.')
    return Path(jobs_directory) / job_id / 'images' / (image_id + extension)


def validate_image(data, mime_type):
    signatures = {'image/png': data.startswith(b'\x89PNG\r\n\x1a\n'),
                  'image/jpeg': data.startswith(b'\xff\xd8\xff'),
                  'image/webp': data[:4] == b'RIFF' and data[8:12] == b'WEBP'}
    if not data or len(data) > MAX_IMAGE_BYTES or not signatures.get(mime_type):
        raise StoreError('첨부 이미지 형식이나 크기를 확인해 주세요. 이미지당 최대 6MB입니다.')


def decode_images(store, payload):
    uploads = payload.get('images', [])
    if not isinstance(uploads, list) or len(uploads) > 3:
        raise StoreError('한 번에 이미지는 최대 3개까지 첨부할 수 있습니다.')
    allowed_targets = set(payload.get('answers', {})) or {'ask'}
    decoded = []
    for upload in uploads:
        if not isinstance(upload, dict) or upload.get('target') not in allowed_targets:
            raise StoreError('이미지를 첨부한 입력칸을 확인해 주세요.')
        metadata = upload.get('existing')
        if metadata:
            data = read_existing_image(store, metadata, payload['session_id'])
            mime_type = metadata['mime_type']
        else:
            try:
                data = base64.b64decode(upload.get('data_base64', ''), validate=True)
            except (ValueError, binascii.Error):
                raise StoreError('이미지 데이터를 읽지 못했습니다.') from None
            mime_type = upload.get('mime_type')
        validate_image(data, mime_type)
        name = Path(str(upload.get('name', '스크린샷'))).name[:120]
        decoded.append({'target': upload['target'], 'mime_type': mime_type, 'name': name, 'data': data})
    return decoded


def read_existing_image(store, metadata, session_id):
    path = image_path(store.root / 'web/jobs', metadata)
    job = store.read_json(path.parent.parent / 'job.json')
    images = job.get('request', {}).get('images', []) if job else []
    if not job or job.get('session_id') != session_id or metadata not in images:
        raise StoreError('이 학습의 첨부 이미지를 찾지 못했습니다.')
    try:
        return path.read_bytes()
    except OSError:
        raise StoreError('첨부 이미지 파일을 찾지 못했습니다.') from None


def save_images(directory, decoded):
    images = []
    for upload in decoded:
        metadata = {key: upload[key] for key in ('target', 'mime_type', 'name')}
        metadata.update(id=str(uuid.uuid4()), job_id=directory.name)
        path = image_path(directory.parent, metadata)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(upload['data'])
        path.chmod(0o600)
        images.append(metadata)
    return images


def attach_to_questions(record, images):
    from study_view import questions
    for question in questions(record['state'].get('pending_batch')):
        attached = [image for image in images if image['target'] == question['id']]
        if attached:
            question['submitted_images'] = attached


def inference_images(record, request):
    from study_view import all_questions
    images = {image['id']: image for image in request.get('images', [])}
    for question in all_questions(record['state']):
        if question.get('status') == 'answer_saved':
            images.update({image['id']: image for image in question.get('submitted_images', [])})
    return list(images.values())
