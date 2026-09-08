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
    raise RuntimeError('Cần có ít nhất một user trong database để chạy test upload.')
with client.session_transaction() as sess:
    sess['user_id'] = test_user['id']

resp_get = client.get('/viet-bai')
print('GET_viet_bai', resp_get.status_code)

img = (io.BytesIO(b'fake-image-bytes'), 'demo.png')
second_img = (io.BytesIO(b'fake-second-image-bytes'), 'demo-second.png')
resp_post = client.post(
    '/viet-bai',
    data={
        'title': 'Bài thử upload ảnh',
        'category': 'hoc-thuat',
        'excerpt': 'Mô tả bài thử',
        'content': '## Đầu bài\n\nĐây là nội dung mẫu.\n\n- Mục 1\n- Mục 2\n\n![Ảnh thử](https://example.com/demo.png)',
        'images': [img, second_img],
    },
    content_type='multipart/form-data',
    follow_redirects=False,
)
print('POST_viet_bai', resp_post.status_code, resp_post.headers.get('Location'))
print('uploads_exist', os.path.exists(os.path.join(app_module.UPLOAD_DIR, 'demo.png')), os.path.exists(os.path.join(app_module.UPLOAD_DIR, 'demo-second.png')))
