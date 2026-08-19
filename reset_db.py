import os
import sys
sys.path.append(os.getcwd())

from app import create_app
from models import db, User, Categoria
from werkzeug.security import generate_password_hash

CATEGORIAS_INICIALES = [
    "Cervezas (Nacionales, Artesanales, Importadas, Barril)",
    "Licores / Botellas (Whisky, Ron, Vodka, Tequila, Aguardiente, Ginebra)",
    "Cócteles y Tragos",
    "Comidas / Platos Fuertes / Picadas / Snacks",
    "Bebidas sin Alcohol",
    "Insumos de Barra y Cocina"
]

def reset_database():
    app = create_app()
    with app.app_context():
        print("[1/4] Eliminando todas las tablas existentes...")
        db.drop_all()
        
        print("[2/4] Creando nuevas tablas...")
        db.create_all()
        
        print("[3/4] Insertando categorias oficiales de Bar & Comidas...")
        for cat_nombre in CATEGORIAS_INICIALES:
            cat = Categoria(nombre=cat_nombre)
            db.session.add(cat)
        db.session.commit()
        print(f"   -> {len(CATEGORIAS_INICIALES)} categorias creadas con exito.")
        
        print("[4/4] Creando usuario Administrador...")
        admin_user = User(
            nombre='Administrador Harry Beer',
            email='admin@harrybeer.com',
            telefono='3000000000',
            password_hash=generate_password_hash('Admin123'),
            rol='admin'
        )
        db.session.add(admin_user)
        
        # Tambien agregamos admin@elgoldy.com para compatibilidad
        admin_elgoldy = User(
            nombre='Admin General',
            email='admin@elgoldy.com',
            telefono='3000000001',
            password_hash=generate_password_hash('Admin123'),
            rol='admin'
        )
        db.session.add(admin_elgoldy)
        db.session.commit()
        
        print("OK: Base de datos reiniciada y configurada exitosamente para HARRY BEER.")

if __name__ == '__main__':
    reset_database()
