import sys; sys.path.insert(0, '.')
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from app.database import AdminUser, get_database_url
import os

url = get_database_url()
engine = create_engine(url)
Session = sessionmaker(bind=engine)
db = Session()
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

existing = db.query(AdminUser).filter(AdminUser.username == 'superadmin').first()
if existing:
    print('Updating existing superadmin password...')
    existing.password_hash = pwd_context.hash('admin1234')
else:
    print('Creating new superadmin...')
    superadmin = AdminUser(
        username='superadmin',
        password_hash=pwd_context.hash('admin1234'),
        nombre='Super Administrador',
        rol='superadmin',
        permisos={'validador': True, 'reportes': True, 'exportaciones': True, 'powerbi': True, 'directorio': True, 'consola': True},
        activo=True
    )
    db.add(superadmin)

try:
    db.commit()
    print('✅ Superadmin listos: user=superadmin / pass=admin1234')
except Exception as e:
    print(f'Error: {e}')
