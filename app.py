import os
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

from flask import Flask, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, logout_user
from flask_wtf.csrf import CSRFProtect

# Importar la instancia de db desde models
from models import db, User

def create_app():
    app = Flask(__name__)
    
    # Configuración mediante variables de entorno (con fallback a PostgreSQL local)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-super-secreta')
    
    # Para la conexión a PostgreSQL, psycopg2 es el default de SQLALchemy al usar postgresql://
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:admin123@localhost:5432/HB')
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Inicializar Extensiones
    db.init_app(app)
    Migrate(app, db)
    CSRFProtect(app)
    
    login_manager = LoginManager()
    login_manager.login_view = 'auth_bp.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Importar y Registrar Blueprints
    from routes.sales import sales_bp
    from routes.inventory import inventory_bp
    from routes.auth import auth_bp
    from routes.arqueo import arqueo_bp
    from routes.gastos import gastos_bp
    
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(arqueo_bp, url_prefix='/arqueo')
    app.register_blueprint(gastos_bp, url_prefix='/gastos')
    
    # Registro de Blueprint Admin, Liquidaciones y Proveedores
    from routes.admin import admin_bp
    from routes.tables import tables_bp
    from routes.liquidaciones import liquidaciones_bp
    from routes.proveedores import proveedores_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(tables_bp, url_prefix='/tables')
    app.register_blueprint(liquidaciones_bp, url_prefix='/liquidaciones')
    app.register_blueprint(proveedores_bp, url_prefix='/proveedores')

    @app.before_request
    def verificar_horario_sesion_activa():
        if current_user.is_authenticated:
            if not getattr(current_user, 'activo', True):
                logout_user()
                flash('⛔ Tu cuenta ha sido desactivada por la administración.', 'danger')
                return redirect(url_for('auth_bp.login'))

            if current_user.rol != 'admin' and getattr(current_user, 'horario_restringido', False):
                if request.endpoint and (request.endpoint.startswith('auth_bp.') or request.endpoint == 'static'):
                    return
                permitido, msg_horario = current_user.verificar_acceso_horario()
                if not permitido:
                    logout_user()
                    flash(f'⛔ {msg_horario}', 'danger')
                    return redirect(url_for('auth_bp.login'))

    @app.template_filter('cop')
    def cop_filter(value):
        if value is None:
            return "0"
        try:
            # Formateo a moneda colombiana (separador de miles con coma, como pidió el usuario)
            return "{:,.0f}".format(float(value))
        except (ValueError, TypeError):
            return value

    @app.route('/')
    def index():
        # Redirección de sesión y rol de usuario
        if not current_user.is_authenticated:
            return redirect(url_for('auth_bp.login'))
            
        if current_user.rol == 'admin':
            return redirect(url_for('admin_bp.dashboard'))
            

        # Por defecto, Vendedores van directo a Cajas
        return redirect(url_for('sales_bp.procesar_venta'))

    return app

# Definición global para Gunicorn
app = create_app()

if __name__ == '__main__':
    # ---------------- LÓGICA DE INICIALIZACIÓN ----------------
    # =========================================================================
    # CONFIGURACIÓN PWA
    # =========================================================================
    from flask import send_from_directory
    @app.route('/manifest.json')
    def manifest():
        return send_from_directory('static', 'manifest.json')
        
    @app.route('/sw.js')
    def service_worker():
        return send_from_directory('static', 'sw.js', mimetype='application/javascript')
        
    @app.route('/offline')
    def offline():
        from flask import render_template
        return render_template('offline.html')

    with app.app_context():
        from models import db, User
        from werkzeug.security import generate_password_hash
        
        # Aseguramos que las tablas existan sin romper migraciones
        db.create_all()
        
        # Crear la carpeta de imágenes si no existe
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        # Verificamos e instanciamos la Categoría Oficial de Combos
        from models import Categoria, Product
        cat_combos = Categoria.query.filter(Categoria.nombre.ilike('%combo%')).first()
        if not cat_combos:
            cat_combos = Categoria(nombre='Combos')
            db.session.add(cat_combos)
            db.session.commit()
            print("[INFO] Categoría 'Combos' creada exitosamente.")
        elif cat_combos.nombre != 'Combos':
            cat_combos.nombre = 'Combos'
            db.session.commit()
            
        # Reasignar combos existentes que se encuentren en otras categorías
        combos_existentes = Product.query.filter_by(tipo_producto='combo').all()
        for cb in combos_existentes:
            if cb.categoria_id != cat_combos.id:
                cb.categoria_id = cat_combos.id
        if combos_existentes:
            db.session.commit()

        # Verificamos e instanciamos al Administrador si no existe
        if not User.query.filter_by(email='admin@harrybeer.com').first():
            master_admin = User(
                nombre='Administrador Harry Beer',
                email='admin@harrybeer.com',
                password_hash=generate_password_hash('Admin123'),
                rol='admin'
            )
            db.session.add(master_admin)
            db.session.commit()
            print("[INFO] Usuario maestro 'admin@harrybeer.com' fue creado exitosamente.")
            
    app.run(debug=True)
