from functools import wraps
from flask import abort
from flask_login import current_user

def admin_required(f):
    """
    Decorador para proteger rutas exclusivas del administrador.
    Lanza un error 403 Forbidden si el usuario actual no tiene el rol de administrador.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
