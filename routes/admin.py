from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, User, SaleDetail, SalePayment, StockAdjustment, Expense, obtener_hora_bogota
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash
from decorators import admin_required
from decimal import Decimal
from datetime import datetime, time

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/vendedores', methods=['GET', 'POST'])
@login_required
@admin_required
def vendedores():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip().lower()
        telefono = request.form.get('telefono', '').strip()
        password = request.form.get('password', '').strip()
        rol = request.form.get('rol', 'cajero')
        activo = bool(request.form.get('activo'))
        
        horario_restringido = bool(request.form.get('horario_restringido'))
        hora_ini_str = request.form.get('hora_inicio')
        hora_fin_str = request.form.get('hora_fin')
        dias_list = request.form.getlist('dias_laborales')
        dias_str = ','.join(dias_list) if dias_list else '0,1,2,3,4,5,6'

        hora_inicio = datetime.strptime(hora_ini_str, '%H:%M').time() if (horario_restringido and hora_ini_str) else None
        hora_fin = datetime.strptime(hora_fin_str, '%H:%M').time() if (horario_restringido and hora_fin_str) else None

        if User.query.filter_by(email=email).first():
            flash('Acción Denegada: Ese correo ya le pertenece a otro usuario.', 'danger')
        else:
            try:
                nuevo_usuario = User(
                    nombre=nombre,
                    email=email,
                    telefono=telefono if telefono else None,
                    password_hash=generate_password_hash(password),
                    rol=rol,
                    activo=activo,
                    horario_restringido=horario_restringido,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                    dias_laborales=dias_str
                )
                db.session.add(nuevo_usuario)
                db.session.commit()
                flash(f"¡Personal '{nombre}' registrado exitosamente con rol '{rol}'!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f'Ocurrió un error al intentar registrar al usuario: {str(e)}', 'danger')
            
        return redirect(url_for('admin_bp.vendedores'))
        
    lista_vendedores = User.query.filter(User.rol != 'admin').order_by(User.nombre).all()
    return render_template('admin/vendedores.html', vendedores=lista_vendedores)

@admin_bp.route('/vendedores/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_vendedor(id):
    u = User.query.get_or_404(id)
    nombre = request.form.get('nombre', '').strip()
    email = request.form.get('email', '').strip().lower()
    telefono = request.form.get('telefono', '').strip()
    password = request.form.get('password', '').strip()
    rol = request.form.get('rol', u.rol)
    activo = (request.form.get('activo') in ['on', 'true', '1', True])
    
    horario_restringido = (request.form.get('horario_restringido') in ['on', 'true', '1', True])
    hora_ini_str = request.form.get('hora_inicio')
    hora_fin_str = request.form.get('hora_fin')
    dias_list = request.form.getlist('dias_laborales')
    dias_str = ','.join(dias_list) if dias_list else '0,1,2,3,4,5,6'

    # Verificar si el correo ya existe en otro usuario
    otro = User.query.filter(User.email == email, User.id != id).first()
    if otro:
        flash(f'El correo {email} ya está registrado para otro usuario.', 'danger')
        return redirect(url_for('admin_bp.vendedores'))

    try:
        u.nombre = nombre
        u.email = email
        u.telefono = telefono if telefono else None
        u.rol = rol
        u.activo = activo
        u.horario_restringido = horario_restringido

        if horario_restringido and hora_ini_str:
            u.hora_inicio = datetime.strptime(hora_ini_str, '%H:%M').time()
        elif not horario_restringido:
            u.hora_inicio = None

        if horario_restringido and hora_fin_str:
            u.hora_fin = datetime.strptime(hora_fin_str, '%H:%M').time()
        elif not horario_restringido:
            u.hora_fin = None

        u.dias_laborales = dias_str

        if password:
            u.password_hash = generate_password_hash(password)

        db.session.commit()
        flash(f'¡Personal "{u.nombre}" actualizado correctamente!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar: {str(e)}', 'danger')

    return redirect(url_for('admin_bp.vendedores'))

@admin_bp.route('/vendedores/toggle_status/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_status_vendedor(id):
    u = User.query.get_or_404(id)
    if u.rol == 'admin':
        return jsonify({'error': 'No se puede desactivar al usuario administrador principal.'}), 400

    u.activo = not u.activo
    db.session.commit()
    return jsonify({
        'success': True,
        'activo': u.activo,
        'mensaje': f'El estado de {u.nombre} ahora es {"ACTIVO" if u.activo else "INACTIVO"}.'
    })

@admin_bp.route('/vendedores/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_vendedor(id):
    u = User.query.get_or_404(id)
    if u.rol == 'admin':
        flash('No se puede eliminar la cuenta de administrador principal.', 'danger')
        return redirect(url_for('admin_bp.vendedores'))

    # Si tiene historial de ventas o registros
    if u.ventas or u.ventas_mesero or u.arqueos:
        u.activo = False
        db.session.commit()
        flash(f'El usuario "{u.nombre}" cuenta con historial de ventas registradas. Se ha DESACTIVADO su acceso para no afectar los reportes contables.', 'warning')
    else:
        db.session.delete(u)
        db.session.commit()
        flash(f'El usuario "{u.nombre}" ha sido eliminado exitosamente.', 'success')

    return redirect(url_for('admin_bp.vendedores'))

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Se obtienen métricas clave para que el administrador tenga un resumen rápido de las operaciones del negocio
    todos_prods = Product.query.all()
    total_productos = len(todos_prods)
    # Alertar sobre TODOS los productos, insumos, cócteles o combos con stock bajo o crítico
    productos_bajo_stock = sum(1 for p in todos_prods if p.es_bajo_stock)
    
    # Se filtran las ventas del Turno en curso
    from models import Turno
    turno_abierto = Turno.query.filter_by(estado='abierto').first()
    
    if turno_abierto:
        total_ventas = db.session.query(func.sum(Sale.monto_total)).filter(Sale.turno_id == turno_abierto.id).scalar() or 0.0
        conteo_ventas = Sale.query.filter(Sale.turno_id == turno_abierto.id).count()
        turno_numero = turno_abierto.numero_turno
    else:
        total_ventas = 0.0
        conteo_ventas = 0
        turno_numero = 'Ninguno'

    return render_template('admin/dashboard.html', 
                           total_productos=total_productos,
                           productos_bajo_stock=productos_bajo_stock,
                           total_ventas=total_ventas,
                           conteo_ventas=conteo_ventas,
                           turno_numero=turno_numero)



@admin_bp.route('/balance-financiero', methods=['GET', 'POST'])
@login_required
@admin_required
def balance_financiero():
    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
    else:
        fecha_inicio_str = request.args.get('fecha_inicio')
        fecha_fin_str = request.args.get('fecha_fin')

    hoy = obtener_hora_bogota()
    import calendar
    if not fecha_inicio_str or not fecha_fin_str:
        # Por defecto, mes calendario actual (del 1 al 30/31)
        primer_dia = hoy.replace(day=1)
        ultimo_dia_num = calendar.monthrange(hoy.year, hoy.month)[1]
        ultimo_dia = hoy.replace(day=ultimo_dia_num)
        
        fecha_inicio_str = primer_dia.strftime('%Y-%m-%d')
        fecha_fin_str = ultimo_dia.strftime('%Y-%m-%d')

    from datetime import datetime, timedelta
    try:
        inicio_dt = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
        fin_dt = datetime.strptime(fecha_fin_str, '%Y-%m-%d')
        # Avanzamos límite al inicio del siguiente día matemáticamente
        fin_dt_query = fin_dt + timedelta(days=1)
    except ValueError:
        flash("Formato de fecha inválido.", "danger")
        return redirect(url_for('admin_bp.dashboard'))

    # 1. Ventas Totales
    ventas_query = Sale.query.filter(Sale.fecha_venta >= inicio_dt, Sale.fecha_venta < fin_dt_query).all()
    ventas_efectivo = 0.0
    ventas_transferencia = 0.0
    
    for v in ventas_query:
        if v.pagos:
            for pago in v.pagos:
                monto = float(pago.monto)
                if pago.metodo_pago == 'efectivo':
                    ventas_efectivo += monto
                else:
                    ventas_transferencia += monto
        else:
            monto = float(v.monto_total)
            if v.metodo_pago == 'efectivo':
                ventas_efectivo += monto
            elif v.metodo_pago in ['transferencia', 'nequi', 'bancolombia', 'daviplata']:
                ventas_transferencia += monto
                
    total_ingresos = ventas_efectivo + ventas_transferencia

    # 2. Costo de Mercancía Vendida (COGS) y Categorización
    detalles_query = SaleDetail.query.join(Sale).filter(
        Sale.fecha_venta >= inicio_dt,
        Sale.fecha_venta < fin_dt_query
    ).all()
    
    cantidades_por_categoria = {}
    cogs_total = 0.0
    total_cortesias = 0
    
    for d in detalles_query:
        # Calcular COGS unitario
        costo_unitario = 0.0
        if d.producto:
            costo_unitario = float(d.producto.precio_costo) if d.producto.precio_costo else 0.0
        elif getattr(d, 'precio_costo_manual', None):
            costo_unitario = float(d.precio_costo_manual)
            
        cogs_total += costo_unitario * float(d.cantidad_vendida)

        # Detectar Cortesía
        if d.es_cortesia or float(d.precio_venta_final) == 0.0:
            total_cortesias += d.cantidad_vendida
        else:
            # Agrupar por Categoría
            cat_name = 'Otros / Manuales'
            if d.producto and d.producto.categoria:
                cat_name = d.producto.categoria.nombre
            
            if cat_name not in cantidades_por_categoria:
                cantidades_por_categoria[cat_name] = 0
            cantidades_por_categoria[cat_name] += d.cantidad_vendida

    # 3. Costos Indirectos y Gastos Operativos
    gastos_query = Expense.query.filter(Expense.fecha_gasto >= inicio_dt, Expense.fecha_gasto < fin_dt_query).order_by(Expense.fecha_gasto.asc()).all()
    
    lista_costos_indirectos = [g for g in gastos_query if g.tipo_gasto == 'Costos Indirectos']
    lista_costos_producto = [g for g in gastos_query if g.tipo_gasto == 'Costos Producto']
    lista_gastos_operacionales = [g for g in gastos_query if g.tipo_gasto == 'Gastos Operacionales']
    
    costos_indirectos = sum(g.monto for g in lista_costos_indirectos)
    costos_producto = sum(g.monto for g in lista_costos_producto)
    gastos_operacionales = sum(g.monto for g in lista_gastos_operacionales)
    
    total_salidas = float(cogs_total) + float(costos_indirectos) + float(costos_producto) + float(gastos_operacionales)
    utilidad_bruta = float(total_ingresos) - float(cogs_total)
    balance_neto = float(total_ingresos) - total_salidas

    datos_financieros = {
        'ventas_efectivo': float(ventas_efectivo),
        'ventas_transferencia': float(ventas_transferencia),
        'total_ingresos': float(total_ingresos),
        'cogs_total': float(cogs_total),
        'costos_indirectos': float(costos_indirectos),
        'costos_producto': float(costos_producto),
        'gastos_operacionales': float(gastos_operacionales),
        'total_salidas': total_salidas,
        'utilidad_bruta': utilidad_bruta,
        'balance_neto': balance_neto,
        'cantidades_por_categoria': cantidades_por_categoria,
        'total_cortesias': total_cortesias,
        'lista_costos_indirectos': lista_costos_indirectos,
        'lista_costos_producto': lista_costos_producto,
        'lista_gastos_operacionales': lista_gastos_operacionales
    }

    return render_template(
        'admin/balance_reporte.html',
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str,
        fecha_generacion=hoy.strftime('%Y-%m-%d %H:%M'),
        datos=datos_financieros
    )
