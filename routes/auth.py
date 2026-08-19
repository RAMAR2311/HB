from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required
from models import User
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Consultamos el usuario
        user = User.query.filter_by(email=email).first()
        
        # Validar contraseña cifrada
        if user and check_password_hash(user.password_hash, password):
            if not user.activo:
                flash('⛔ Tu cuenta se encuentra deshabilitada. Comunícate con el administrador.', 'danger')
                return redirect(url_for('auth_bp.login'))

            permitido, msg_horario = user.verificar_acceso_horario()
            if not permitido:
                flash(f'⛔ {msg_horario}', 'danger')
                return redirect(url_for('auth_bp.login'))

            login_user(user) # Iniciar sesión del lado del servidor persistente
            flash(f'¡Bienvenido(a), {user.nombre}!', 'success')
            
            # Redirección inteligente basada en ROL o hacia la raíz para delegar el control
            return redirect(url_for('index'))
        
        flash('Tus credenciales (Correo o Contraseña) son inválidas.', 'danger')
        return redirect(url_for('auth_bp.login'))
        
    # GET: Mostrar Formulario normal
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user() # Rompe la sesión
    flash('¡Has cerrado tu sesión de manera segura!', 'success')
    return redirect(url_for('auth_bp.login'))
