import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT TRUE;"))
    db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS horario_restringido BOOLEAN DEFAULT FALSE;"))
    db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hora_inicio TIME NULL;"))
    db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hora_fin TIME NULL;"))
    db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS dias_laborales VARCHAR(100) DEFAULT '0,1,2,3,4,5,6';"))
    db.session.execute(text("UPDATE users SET activo = TRUE WHERE activo IS NULL;"))
    db.session.execute(text("UPDATE users SET horario_restringido = FALSE WHERE horario_restringido IS NULL;"))
    db.session.commit()
    print("MIGRATION COMPLETED SUCCESSFULLY")
