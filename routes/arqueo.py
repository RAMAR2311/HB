from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Sale, SalePayment, ArqueoCaja, Expense
from decorators import admin_required
from datetime import datetime, date
from decimal import Decimal
import re
import pytz

arqueo_bp = Blueprint('arqueo_bp', __name__)

def obtener_hora_bogota():
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

def calcular_totales_dia(ventas_del_dia):
    """Calcula los totales de efectivo y transferencias del día.
    Usa SalePayment si está disponible, de lo contrario usa metodo_pago legacy."""
    total_efectivo = Decimal('0')
    total_transferencia = Decimal('0')
    
    for v in ventas_del_dia:
        if v.pagos:  # Ventas nuevas con tabla sale_payments
            for pago in v.pagos:
                if pago.metodo_pago == 'efectivo':
                    total_efectivo += pago.monto
                else:  # nequi, bancolombia, daviplata, transferencia
                    total_transferencia += pago.monto
        else:  # Retrocompatibilidad con ventas antiguas
            if v.metodo_pago == 'efectivo':
                total_efectivo += v.monto_total
            elif v.metodo_pago in ['transferencia', 'nequi', 'bancolombia', 'daviplata']:
                total_transferencia += v.monto_total
    
    return total_efectivo, total_transferencia


@arqueo_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    from models import Turno
    turno_abierto = Turno.query.filter_by(estado='abierto').first()
    
    if not turno_abierto:
        flash('No hay un turno abierto. Por favor, asegúrate de que exista un turno inicial.', 'warning')
        return redirect(url_for('admin_bp.dashboard'))

    # Calcular ventas CERRADAS del Turno ordenadas cronológicamente
    ventas_del_dia = Sale.query.filter_by(turno_id=turno_abierto.id).filter(Sale.estado_cuenta != 'abierta').order_by(Sale.fecha_venta.asc()).all()
    total_efectivo, total_transferencia = calcular_totales_dia(ventas_del_dia)

    # Métricas Operativas y Especiales del Turno
    total_propinas_dia = float(sum(v.monto_propina or 0 for v in ventas_del_dia))
    total_botellaje_dia = float(sum(v.total_botellaje or 0 for v in ventas_del_dia))
    total_descuentos_dia = float(sum(v.monto_descuento or 0 for v in ventas_del_dia))
    total_cortesias_dia = float(sum(v.monto_cortesia or 0 for v in ventas_del_dia))
    total_ventas_bruto = float(total_efectivo + total_transferencia)

    # Calcular gastos del Turno
    gastos_diarios_registros = Expense.query.filter_by(
        turno_id=turno_abierto.id,
        metodo_pago='efectivo'
    ).all()
    gastos_automaticos = float(sum(g.monto for g in gastos_diarios_registros))

    # Calcular gastos por productos externos del Turno
    gastos_externos_registros = Expense.query.filter_by(
        turno_id=turno_abierto.id,
        categoria='Pago Prod. Externo'
    ).all()
    gastos_externos = float(sum(g.monto for g in gastos_externos_registros))

    # El Arqueo no está duplicado si el turno sigue abierto, pero por seguridad revisamos
    arqueo_existente = ArqueoCaja.query.filter_by(turno_id=turno_abierto.id).first()

    base_sugerida = float(turno_abierto.base_inicial)

    if request.method == 'POST':
        if ArqueoCaja.query.filter_by(turno_id=turno_abierto.id).first():
            flash('⚠️ Ya existe un arqueo para este turno.', 'warning')
            return redirect(url_for('arqueo_bp.reporte'))

        base_inicial_raw = request.form.get('base_inicial', '0').replace('.', '').replace(',', '')
        efectivo_fisico_raw = request.form.get('efectivo_fisico_contado', '0').replace('.', '').replace(',', '')
        digital_contado_raw = request.form.get('digital_contado', '0').replace('.', '').replace(',', '')

        base_inicial = float(base_inicial_raw) if base_inicial_raw else 0.0
        retiro_grueso = 0.0
        efectivo_fisico_contado = float(efectivo_fisico_raw) if efectivo_fisico_raw else 0.0
        digital_contado = float(digital_contado_raw) if digital_contado_raw else 0.0
        
        # Recalcular gastos automáticos por seguridad
        gastos_recalculados = Expense.query.filter_by(
            turno_id=turno_abierto.id,
            metodo_pago='efectivo'
        ).all()
        gastos_del_dia = float(sum(g.monto for g in gastos_recalculados))
        
        # Cálculo contable de diferencia
        esperado = (base_inicial + float(total_efectivo)) - gastos_del_dia - retiro_grueso
        diferencia = efectivo_fisico_contado - esperado

        observaciones_gastos = request.form.get('observaciones_gastos', '').strip()

        nuevo_arqueo = ArqueoCaja(
            vendedor_id=current_user.id,
            turno_id=turno_abierto.id,
            fecha_arqueo=obtener_hora_bogota().date(),
            base_inicial=base_inicial,
            gastos_del_dia=gastos_del_dia,
            retiro_grueso=retiro_grueso,
            efectivo_fisico_contado=efectivo_fisico_contado,
            digital_contado=digital_contado,
            diferencia=diferencia,
            total_propinas=total_propinas_dia,
            total_botellaje=total_botellaje_dia,
            total_descuentos=total_descuentos_dia,
            observaciones_gastos=observaciones_gastos,
            total_efectivo_sistema=total_efectivo,
            total_transferencia_sistema=total_transferencia
        )

        try:
            db.session.add(nuevo_arqueo)
            
            # Cerrar el turno actual
            turno_abierto.estado = 'cerrado'
            turno_abierto.fecha_cierre = obtener_hora_bogota()
            turno_abierto.usuario_cierre_id = current_user.id
            turno_abierto.base_inicial = base_inicial # Actualizar la base inicial si fue modificada en el arqueo
            
            # Abrir el siguiente turno automáticamente
            nuevo_turno = Turno(
                numero_turno=turno_abierto.numero_turno + 1,
                fecha_apertura=obtener_hora_bogota(),
                estado='abierto',
                usuario_apertura_id=current_user.id,
                base_inicial=0.0 # Se deja en 0 para que la coloquen manualmente al cerrar
            )
            db.session.add(nuevo_turno)
            
            db.session.commit()
            flash('✅ Arqueo de caja guardado exitosamente. Se ha abierto un nuevo turno automáticamente.', 'success')
            return redirect(url_for('arqueo_bp.reporte'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al guardar el arqueo de caja: {str(e)}', 'danger')

    return render_template(
        'arqueo/form.html',
        turno=turno_abierto,
        fecha=obtener_hora_bogota().strftime('%Y-%m-%d'),
        ventas_del_dia=ventas_del_dia,
        total_efectivo=total_efectivo,
        total_transferencia=total_transferencia,
        total_ventas_bruto=total_ventas_bruto,
        total_propinas_dia=total_propinas_dia,
        total_botellaje_dia=total_botellaje_dia,
        total_descuentos_dia=total_descuentos_dia,
        total_cortesias_dia=total_cortesias_dia,
        arqueo_existente=arqueo_existente,
        gastos_automaticos=gastos_automaticos,
        gastos_externos=gastos_externos,
        base_sugerida=base_sugerida
    )

@arqueo_bp.route('/reporte', methods=['GET'])
@login_required
def reporte():
    turno_id = request.args.get('turno_id', type=int)
    
    # Obtener lista de arqueos según el rol
    if current_user.rol == 'admin':
        lista_arqueos = ArqueoCaja.query.order_by(ArqueoCaja.id.desc()).all()
    else:
        lista_arqueos = ArqueoCaja.query.filter_by(vendedor_id=current_user.id).order_by(ArqueoCaja.id.desc()).limit(10).all()
        
    if not lista_arqueos:
        flash('No hay arqueos registrados.', 'info')
        return redirect(url_for('admin_bp.dashboard'))

    # Si no se envía turno_id, usar el más reciente de la lista permitida
    if not turno_id:
        arqueo_actual = lista_arqueos[0]
    else:
        arqueo_actual = ArqueoCaja.query.filter_by(turno_id=turno_id).first()
        # Verificar permisos
        if current_user.rol != 'admin' and arqueo_actual and arqueo_actual.vendedor_id != current_user.id:
            flash('No tienes permiso para ver este arqueo.', 'danger')
            return redirect(url_for('arqueo_bp.reporte'))

    if not arqueo_actual:
        flash('Arqueo no encontrado.', 'danger')
        return redirect(url_for('arqueo_bp.reporte'))
        
    ventas_periodo = Sale.query.filter_by(turno_id=arqueo_actual.turno_id).order_by(Sale.fecha_venta.desc()).all()
    from models import Expense
    gastos_periodo = Expense.query.filter_by(turno_id=arqueo_actual.turno_id).order_by(Expense.fecha_gasto.desc()).all()

    efectivo_esperado = (arqueo_actual.base_inicial + arqueo_actual.total_efectivo_sistema) - arqueo_actual.gastos_del_dia - arqueo_actual.retiro_grueso
    digital_esperado = arqueo_actual.total_transferencia_sistema
    
    diferencia_efectivo = arqueo_actual.efectivo_fisico_contado - efectivo_esperado
    diferencia_digital = arqueo_actual.digital_contado - digital_esperado

    fecha_generacion = obtener_hora_bogota().strftime('%d/%m/%Y %I:%M %p')

    return render_template(
        'arqueo/reporte.html',
        lista_arqueos=lista_arqueos,
        arqueo=arqueo_actual,
        ventas_periodo=ventas_periodo,
        gastos_periodo=gastos_periodo,
        efectivo_esperado=efectivo_esperado,
        digital_esperado=digital_esperado,
        diferencia_efectivo=diferencia_efectivo,
        diferencia_digital=diferencia_digital,
        fecha_generacion=fecha_generacion
    )

@arqueo_bp.route('/anular/<int:id>', methods=['POST'])
@login_required
@admin_required
def anular(id):
    from models import Turno, Expense
    try:
        arqueo_a_anular = ArqueoCaja.query.get_or_404(id)
        turno_original = Turno.query.get(arqueo_a_anular.turno_id)
        
        # Buscar si existe un turno siguiente que se haya abierto al hacer este arqueo
        turno_siguiente = Turno.query.filter(Turno.numero_turno > turno_original.numero_turno).order_by(Turno.numero_turno.asc()).first()
        
        # Mover las ventas del turno siguiente al original si existen
        if turno_siguiente:
            ventas = Sale.query.filter_by(turno_id=turno_siguiente.id).all()
            gastos = Expense.query.filter_by(turno_id=turno_siguiente.id).all()
            for v in ventas:
                v.turno_id = turno_original.id
                v.numero_turno = turno_original.numero_turno
            for g in gastos:
                g.turno_id = turno_original.id
            
            db.session.delete(turno_siguiente)
            
        turno_original.estado = 'abierto'
        turno_original.fecha_cierre = None
        turno_original.usuario_cierre_id = None
        
        db.session.delete(arqueo_a_anular)
        db.session.commit()
        
        flash('Arqueo anulado exitosamente. El turno anterior ha sido reabierto.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al anular arqueo: {str(e)}', 'danger')
        
    return redirect(url_for('arqueo_bp.reporte'))
