from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Expense, obtener_hora_bogota
from decorators import admin_required
from sqlalchemy import extract
from datetime import datetime

gastos_bp = Blueprint('gastos_bp', __name__)

@gastos_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        # Restricción de seguridad: no administradores solo pueden registrar gastos operacionales
        if current_user.rol != 'admin':
            tipo_gasto = 'Gastos Operacionales'
        else:
            tipo_gasto = request.form.get('tipo_gasto') or 'Gastos Operacionales'
            
        categoria = request.form.get('categoria')
        descripcion = request.form.get('descripcion')
        montos = request.form.getlist('monto[]')
        metodos_pago = request.form.getlist('metodo_pago[]')
        
        # Compatibilidad con formulario antiguo (sin arrays)
        if not montos:
            monto_single = request.form.get('monto')
            if monto_single:
                montos = [monto_single]
                metodos_pago = [request.form.get('metodo_pago', 'efectivo')]

        fecha_str = request.form.get('fecha_gasto')

        # Use the provided date or fallback to current datetime
        if fecha_str:
            try:
                fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
            except ValueError:
                fecha_obj = obtener_hora_bogota()
        else:
            fecha_obj = obtener_hora_bogota()

        from models import Turno
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        if not turno_abierto:
            flash('No hay un turno abierto. Debes abrir uno en la caja antes de registrar gastos.', 'danger')
            return redirect(url_for('gastos_bp.index'))

        try:
            for monto, metodo in zip(montos, metodos_pago):
                valor_float = float(monto)
                if valor_float > 0:
                    nuevo_gasto = Expense(
                        usuario_id=current_user.id,
                        tipo_gasto=tipo_gasto,
                        categoria=categoria,
                        descripcion=descripcion,
                        monto=valor_float,
                        metodo_pago=metodo,
                        fecha_gasto=fecha_obj,
                        turno_id=turno_abierto.id
                    )
                    db.session.add(nuevo_gasto)
            db.session.commit()
            flash('Gasto registrado exitosamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Error al intentar registrar el gasto en la base de datos.', 'danger')
        
        return redirect(url_for('gastos_bp.index'))

    # GET Logic (Filters by date if provided, otherwise shows all)
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')

    query = Expense.query
    
    hoy = obtener_hora_bogota()
    if not fecha_inicio_str or not fecha_fin_str:
        import calendar
        start_date = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ultimo_dia_num = calendar.monthrange(hoy.year, hoy.month)[1]
        end_date = hoy.replace(day=ultimo_dia_num, hour=23, minute=59, second=59, microsecond=999999)
            
        fecha_inicio_str = start_date.strftime('%Y-%m-%d')
        fecha_fin_str = end_date.strftime('%Y-%m-%d')
        query = query.filter(Expense.fecha_gasto >= start_date, Expense.fecha_gasto <= end_date)
    else:
        try:
            start_date = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            end_date = datetime.strptime(fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Expense.fecha_gasto >= start_date, Expense.fecha_gasto <= end_date)
        except ValueError:
            pass
    
    # Restricción de visibilidad: 
    # Si no es administrador, SOLAMENTE puede ver los gastos que haya registrado él mismo.
    if current_user.rol != 'admin':
        query = query.filter(Expense.usuario_id == current_user.id)
        
    gastos_lista = query.order_by(Expense.fecha_gasto.desc()).all()

    total_operativos = sum((g.monto for g in gastos_lista if g.tipo_gasto == 'Gastos Operacionales'))
    total_producto = sum((g.monto for g in gastos_lista if g.tipo_gasto == 'Costos Producto'))
    total_indirectos = sum((g.monto for g in gastos_lista if g.tipo_gasto == 'Costos Indirectos'))

    ahora = obtener_hora_bogota()
    # Provide today's date formatted for HTML5 <input type="date">
    hoy_str = ahora.strftime('%Y-%m-%d')
    return render_template('gastos/index.html', gastos=gastos_lista, total_operativos=total_operativos, total_producto=total_producto, total_indirectos=total_indirectos, hoy=hoy_str, fecha_inicio_default=fecha_inicio_str, fecha_fin_default=fecha_fin_str)

@gastos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_gasto(id):
    gasto = Expense.query.get_or_404(id)
    descripcion = gasto.descripcion or gasto.categoria
    try:
        db.session.delete(gasto)
        db.session.commit()
        flash(f'Gasto "{descripcion}" eliminado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al intentar eliminar el gasto.', 'danger')

    return redirect(url_for('gastos_bp.index'))
