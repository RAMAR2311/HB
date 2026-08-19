from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Sale, SaleDetail, User, Product, BeneficiarioCortesia, obtener_hora_bogota
from sqlalchemy import func, desc, or_
from datetime import datetime, date, timedelta
from decimal import Decimal

liquidaciones_bp = Blueprint('liquidaciones_bp', __name__)

@liquidaciones_bp.route('/', methods=['GET'])
@liquidaciones_bp.route('/index', methods=['GET'])
@login_required
def index():
    # Obtener rango de fechas según filtro
    filtro = request.args.get('filtro', 'hoy')
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    tab_activo = request.args.get('tab', 'botellaje')

    ahora = obtener_hora_bogota()
    hoy = ahora.date()

    if filtro == 'turno_actual':
        from models import Turno
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        turno_filtro_id = turno_abierto.id if turno_abierto else -1
        # No usamos dt_inicio/dt_fin para turno_actual, filtraremos por turno_id luego
    elif filtro == 'semana':
        inicio_sem = hoy - timedelta(days=hoy.weekday())
        dt_inicio = datetime.combine(inicio_sem, datetime.min.time())
        dt_fin = datetime.combine(hoy, datetime.max.time())
    elif filtro == 'mes':
        inicio_mes = hoy.replace(day=1)
        dt_inicio = datetime.combine(inicio_mes, datetime.min.time())
        dt_fin = datetime.combine(hoy, datetime.max.time())
    elif filtro == 'personalizado' and fecha_inicio_str and fecha_fin_str:
        try:
            d_ini = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            d_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            dt_inicio = datetime.combine(d_ini, datetime.min.time())
            dt_fin = datetime.combine(d_fin, datetime.max.time())
        except ValueError:
            dt_inicio = datetime.combine(hoy, datetime.min.time())
            dt_fin = datetime.combine(hoy, datetime.max.time())
    elif filtro == 'hoy':
        dt_inicio = datetime.combine(hoy, datetime.min.time())
        dt_fin = datetime.combine(hoy, datetime.max.time())
    else:
        # Default fallback is turno_actual
        filtro = 'turno_actual'
        from models import Turno
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        turno_filtro_id = turno_abierto.id if turno_abierto else -1

    # 1. BOTELLAJE
    query_botellaje = SaleDetail.query.join(Sale).filter(
        Sale.estado_cuenta == 'pagada',
        SaleDetail.botellaje_unitario > 0
    )
    if filtro == 'turno_actual':
        query_botellaje = query_botellaje.filter(Sale.turno_id == turno_filtro_id)
    else:
        query_botellaje = query_botellaje.filter(Sale.fecha_venta >= dt_inicio, Sale.fecha_venta <= dt_fin)
    detalles_botellaje = query_botellaje.order_by(desc(Sale.fecha_venta)).all()

    total_botellaje_acumulado = Decimal('0.00')
    total_botellas_count = 0
    resumen_botellaje_mesero = {}

    for d in detalles_botellaje:
        mesero_nom = d.venta.mesero.nombre if d.venta.mesero else 'Sin Mesero Asignado'
        mesero_id = d.venta.mesero_id or 0
        comision_total_item = d.botellaje_unitario * d.cantidad_vendida
        total_botellaje_acumulado += comision_total_item
        total_botellas_count += d.cantidad_vendida

        if mesero_id not in resumen_botellaje_mesero:
            resumen_botellaje_mesero[mesero_id] = {
                'nombre': mesero_nom,
                'botellas': 0,
                'total_comision': Decimal('0.00')
            }
        resumen_botellaje_mesero[mesero_id]['botellas'] += d.cantidad_vendida
        resumen_botellaje_mesero[mesero_id]['total_comision'] += comision_total_item

    # 2. PROPINAS
    query_propinas = Sale.query.filter(
        Sale.estado_cuenta == 'pagada',
        Sale.monto_propina > 0
    )
    if filtro == 'turno_actual':
        query_propinas = query_propinas.filter(Sale.turno_id == turno_filtro_id)
    else:
        query_propinas = query_propinas.filter(Sale.fecha_venta >= dt_inicio, Sale.fecha_venta <= dt_fin)
    ventas_con_propina = query_propinas.order_by(desc(Sale.fecha_venta)).all()

    total_propina_acumulada = sum(v.monto_propina for v in ventas_con_propina)
    resumen_propina_mesero = {}

    for v in ventas_con_propina:
        mesero_nom = v.mesero.nombre if v.mesero else 'Sin Mesero Asignado'
        mesero_id = v.mesero_id or 0

        if mesero_id not in resumen_propina_mesero:
            resumen_propina_mesero[mesero_id] = {
                'nombre': mesero_nom,
                'ventas_count': 0,
                'total_propina': Decimal('0.00')
            }
        resumen_propina_mesero[mesero_id]['ventas_count'] += 1
        resumen_propina_mesero[mesero_id]['total_propina'] += v.monto_propina

    # 3. CORTESÍAS & REGALOS
    query_cortesias = SaleDetail.query.join(Sale).filter(
        SaleDetail.es_cortesia == True
    )
    if filtro == 'turno_actual':
        query_cortesias = query_cortesias.filter(Sale.turno_id == turno_filtro_id)
    else:
        query_cortesias = query_cortesias.filter(Sale.fecha_venta >= dt_inicio, Sale.fecha_venta <= dt_fin)
    detalles_cortesias = query_cortesias.order_by(desc(Sale.fecha_venta)).all()

    total_cortesias_count = 0
    total_valor_comercial_cortesias = Decimal('0.00')
    total_costo_real_cortesias = Decimal('0.00')
    resumen_cortesias_beneficiario = {}

    for d in detalles_cortesias:
        prod = d.producto
        beneficiario = (d.cortesia_para or 'No especificado').strip()
        cant = d.cantidad_vendida
        precio_ref = (prod.precio_sugerido if prod else Decimal('0.00')) * cant
        costo_ref = (prod.precio_costo if prod else Decimal('0.00')) * cant

        total_cortesias_count += cant
        total_valor_comercial_cortesias += precio_ref
        total_costo_real_cortesias += costo_ref

        if beneficiario not in resumen_cortesias_beneficiario:
            resumen_cortesias_beneficiario[beneficiario] = {
                'beneficiario': beneficiario,
                'cantidad': 0,
                'valor_comercial': Decimal('0.00'),
                'costo_real': Decimal('0.00')
            }
        resumen_cortesias_beneficiario[beneficiario]['cantidad'] += cant
        resumen_cortesias_beneficiario[beneficiario]['valor_comercial'] += precio_ref
        resumen_cortesias_beneficiario[beneficiario]['costo_real'] += costo_ref

    # 4. CATÁLOGO DE BENEFICIARIOS
    beneficiarios_catalogo = BeneficiarioCortesia.query.order_by(BeneficiarioCortesia.nombre.asc()).all()

    return render_template(
        'liquidaciones/index.html',
        filtro=filtro,
        dt_inicio=dt_inicio,
        dt_fin=dt_fin,
        tab_activo=tab_activo,
        # Botellaje
        detalles_botellaje=detalles_botellaje,
        total_botellaje_acumulado=total_botellaje_acumulado,
        total_botellas_count=total_botellas_count,
        resumen_botellaje_mesero=resumen_botellaje_mesero.values(),
        # Propinas
        ventas_con_propina=ventas_con_propina,
        total_propina_acumulada=total_propina_acumulada,
        resumen_propina_mesero=resumen_propina_mesero.values(),
        # Cortesías
        detalles_cortesias=detalles_cortesias,
        total_cortesias_count=total_cortesias_count,
        total_valor_comercial_cortesias=total_valor_comercial_cortesias,
        total_costo_real_cortesias=total_costo_real_cortesias,
        resumen_cortesias_beneficiario=resumen_cortesias_beneficiario.values(),
        # Catálogo
        beneficiarios_catalogo=beneficiarios_catalogo
    )


# --- API PARA GESTIÓN DE BENEFICIARIOS DE CORTESÍAS ---

@liquidaciones_bp.route('/api/beneficiarios', methods=['GET'])
@login_required
def api_obtener_beneficiarios():
    """Retorna la lista de beneficiarios activos para el selector rápido del POS."""
    beneficiarios = BeneficiarioCortesia.query.filter_by(activo=True).order_by(BeneficiarioCortesia.nombre.asc()).all()
    return jsonify([
        {'id': b.id, 'nombre': b.nombre, 'rol_cargo': b.rol_cargo or ''} for b in beneficiarios
    ])


@liquidaciones_bp.route('/api/beneficiarios/nuevo', methods=['POST'])
@login_required
def api_nuevo_beneficiario():
    data = request.get_json() or {}
    nombre = str(data.get('nombre', '')).strip()
    rol_cargo = str(data.get('rol_cargo', '')).strip()

    if not nombre:
        return jsonify({'error': 'El nombre del beneficiario es obligatorio.'}), 400

    existente = BeneficiarioCortesia.query.filter(func.lower(BeneficiarioCortesia.nombre) == nombre.lower()).first()
    if existente:
        if not existente.activo:
            existente.activo = True
            existente.rol_cargo = rol_cargo or existente.rol_cargo
            db.session.commit()
            return jsonify({'success': True, 'mensaje': f'Beneficiario "{nombre}" reactivado con éxito.', 'id': existente.id, 'nombre': existente.nombre})
        return jsonify({'error': f'El beneficiario "{nombre}" ya está registrado.'}), 400

    nuevo = BeneficiarioCortesia(nombre=nombre, rol_cargo=rol_cargo, activo=True)
    db.session.add(nuevo)
    db.session.commit()

    return jsonify({'success': True, 'mensaje': f'Beneficiario "{nombre}" registrado con éxito.', 'id': nuevo.id, 'nombre': nuevo.nombre})


@liquidaciones_bp.route('/api/beneficiarios/editar/<int:b_id>', methods=['POST'])
@login_required
def api_editar_beneficiario(b_id):
    b = BeneficiarioCortesia.query.get_or_404(b_id)
    data = request.get_json() or {}
    nombre = str(data.get('nombre', '')).strip()
    rol_cargo = str(data.get('rol_cargo', '')).strip()

    if not nombre:
        return jsonify({'error': 'El nombre no puede estar vacío.'}), 400

    b.nombre = nombre
    b.rol_cargo = rol_cargo
    db.session.commit()

    return jsonify({'success': True, 'mensaje': f'Beneficiario "{nombre}" actualizado correctamente.'})


@liquidaciones_bp.route('/api/beneficiarios/eliminar/<int:b_id>', methods=['POST'])
@login_required
def api_eliminar_beneficiario(b_id):
    b = BeneficiarioCortesia.query.get_or_404(b_id)
    db.session.delete(b)
    db.session.commit()

    return jsonify({'success': True, 'mensaje': 'Beneficiario eliminado con éxito.'})
