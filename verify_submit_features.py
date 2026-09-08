import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "Tether"))
import app as app_module

client = app_module.app.test_client()
with app_module.app.app_context():
    app_module.init_db()
    test_user = app_module.get_db().execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
if test_user is None:
    raise RuntimeError('Cần có ít nhất một user trong database để chạy test submit.')
with client.session_transaction() as sess:
    sess['user_id'] = test_user['id']

resp_get = client.get('/viet-bai')
print('GET_viet_bai', resp_get.status_code)

payload = {
    'title': 'Bài thử block editor',
    'category': 'hoc-thuat',
    'excerpt': 'Mô tả bài thử cho block editor',
    'content': '## Tiêu đề phụ\n\nĐây là đoạn văn mẫu.\n\n- Mục 1\n- Mục 2',
    'images': [
        (io.BytesIO(b'img1'), 'a.png'),
        (io.BytesIO(b'img2'), 'b.png'),
    ],
}
resp_post = client.post(
    '/viet-bai',
    data=payload,
    content_type='multipart/form-data',
    follow_redirects=False,
)
print('POST_viet_bai', resp_post.status_code, resp_post.headers.get('Location'))
print('uploads_exist', os.path.exists(os.path.join(app_module.UPLOAD_DIR, 'a.png')), os.path.exists(os.path.join(app_module.UPLOAD_DIR, 'b.png')))
