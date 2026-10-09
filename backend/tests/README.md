Сквозной прогон API на SQLite (без Docker):

```
cd backend
DATABASE_URL=sqlite:///./test.db UPLOAD_DIR=./uploads ADMIN_EMAIL=d@test.ru ADMIN_PASSWORD=secret123 \
JWT_SECRET=0123456789abcdef0123456789abcdef PYTHONPATH=. python tests/smoke.py
```
