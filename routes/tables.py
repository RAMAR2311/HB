from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Mesa, Sale, SaleDetail, SalePayment, Product, User
from decimal import Decimal

tables_bp = Blueprint('tables_bp', __name__)

@tables_bp.route('/mapa', methods=['GET'])
@login_required
def mapa_mesas():
    mesas = Mesa.query.order_by(Mesa.id).all()
    meseros = User.query.all()
    return render_template('sales/mapa_mesas.html', mesas=mesas, meseros=meseros)

@tables_bp.route('/api/list', methods=['GET'])
@login_required
def api_listar_mesas():
    mesas = Mesa.query.order_by(Mesa.id).all()
    resultado = []
    
    for m in mesas:
        # Buscar venta activa (abierta) para la mesa
        venta_activa = Sale.query.filter_by(table_id=m.id, estado_cuenta='abierta').first()
        consumo_total = float(venta_activa.monto_total) if venta_activa else 0.0
        conteo_items = sum(d.cantidad_vendida for d in venta_activa.detalles) if venta_activa else 0
        mesero_nombre = venta_activa.mesero.nombre if (venta_activa and venta_activa.mesero) else None
        
        resultado.append({
            'id': m.id,
            'nombre': m.nombre,
            'capacidad': m.capacidad,
            'estado': m.estado,
            'mesa_padre_id': m.mesa_padre_id,
            'venta_id': venta_activa.id if venta_activa else None,
            'consumo_total': consumo_total,
            'items_count': conteo_items,
            'mesero': mesero_nombre
        })
        
    return jsonify(resultado)

@tables_bp.route('/api/cuenta/<int:table_id>', methods=['GET'])
@login_required
def api_cuenta_mesa(table_id):
    mesa_obj = Mesa.query.get(table_id)
    target_id = table_id
    if mesa_obj and mesa_obj.mesa_padre_id:
        target_id = mesa_obj.mesa_padre_id

    venta_abierta = Sale.query.filter_by(table_id=target_id, estado_cuenta='abierta').first()
    if not venta_abierta:
        return jsonify({'existe': False, 'mesa_id': target_id, 'items': [], 'mesero_id': None, 'porcentaje_propina': 10, 'monto_descuento': 0, 'aplica_recargo_datafono': False})

    items = []
    for d in venta_abierta.detalles:
        prod = d.producto
        es_manual = (d.product_id is None)
        nombre_prod = getattr(d, 'nombre_manual', None) if es_manual else (prod.nombre if prod else 'Producto')
        items.append({
            'id': d.product_id,
            'sku': prod.sku if prod else 'MANUAL',
            'nombre': nombre_prod or 'Producto Externo',
            'tipo_producto': prod.tipo_producto if prod else 'simple',
            'cantidad': d.cantidad_vendida,
            'precio_final': float(d.precio_venta_final),
            'precio_limite': float(prod.precio_costo if current_user.rol == 'admin' else prod.precio_minimo) if prod else 0,
            'precio_minimo': float(prod.precio_minimo) if prod else 0,
            'es_manual': es_manual,
            'es_cortesia': d.es_cortesia,
            'cortesia_para': d.cortesia_para,
            'variant_id': d.variant_id
        })

    return jsonify({
        'existe': True,
        'mesa_id': target_id,
        'sale_id': venta_abierta.id,
        'mesero_id': venta_abierta.mesero_id,
        'porcentaje_propina': float(venta_abierta.porcentaje_propina or 10),
        'monto_descuento': float(venta_abierta.monto_descuento or 0),
        'aplica_recargo_datafono': bool(venta_abierta.aplica_recargo_datafono),
        'items': items
    })

@tables_bp.route('/api/nueva', methods=['POST'])
@login_required
def api_nueva_mesa():
    data = request.get_json() or {}
    nombre = str(data.get('nombre', '')).strip()
    capacidad = int(data.get('capacidad', 4))
    
    if not nombre:
        return jsonify({'error': 'El nombre de la mesa es obligatorio.'}), 400
        
    if Mesa.query.filter_by(nombre=nombre).first():
        return jsonify({'error': f'La mesa "{nombre}" ya existe.'}), 400
        
    nueva_m = Mesa(nombre=nombre, capacidad=capacidad, estado='libre')
    db.session.add(nueva_m)
    db.session.commit()
    
    return jsonify({'mensaje': f'Mesa "{nombre}" creada con éxito.', 'id': nueva_m.id})

@tables_bp.route('/api/unir', methods=['POST'])
@login_required
def api_unir_mesas():
    """Une dos o más mesas activas combinando y sumando sus consumos en una sola mesa principal."""
    data = request.get_json() or {}
    mesa_principal_id = data.get('mesa_principal_id')
    mesas_secundarias_ids = data.get('mesas_secundarias_ids', [])
    
    if not mesa_principal_id or not mesas_secundarias_ids:
        return jsonify({'error': 'Debes seleccionar una mesa principal y al menos una mesa secundaria.'}), 400
        
    mesa_principal = Mesa.query.get_or_404(mesa_principal_id)
    
    # Buscar o crear venta abierta en la mesa principal
    venta_principal = Sale.query.filter_by(table_id=mesa_principal.id, estado_cuenta='abierta').first()
    
    for sec_id in mesas_secundarias_ids:
        if int(sec_id) == int(mesa_principal_id): continue
        m_sec = Mesa.query.get(sec_id)
        if not m_sec: continue
        
        # Trasladar consumo de la mesa secundaria a la principal
        venta_sec = Sale.query.filter_by(table_id=m_sec.id, estado_cuenta='abierta').first()
        if venta_sec:
            if not venta_principal:
                # Si la mesa principal no tenía venta abierta, la venta secundaria pasa a ser la venta principal
                venta_sec.table_id = mesa_principal.id
                venta_principal = venta_sec
            else:
                # Si ambas mesas tenían ventas abiertas, combinar los productos sumando cantidades
                for d_sec in list(venta_sec.detalles):
                    existente = None
                    for d_p in venta_principal.detalles:
                        if (d_p.product_id == d_sec.product_id and 
                            d_p.variant_id == d_sec.variant_id and 
                            d_p.es_cortesia == d_sec.es_cortesia and 
                            d_p.precio_venta_final == d_sec.precio_venta_final):
                            existente = d_p
                            break

                    if existente:
                        # Sumar las cantidades consumidas en ambas mesas
                        existente.cantidad_vendida += d_sec.cantidad_vendida
                        db.session.delete(d_sec)
                    else:
                        # Reasignar el detalle a la venta principal
                        d_sec.sale_id = venta_principal.id

                db.session.flush()
                SalePayment.query.filter_by(sale_id=venta_sec.id).delete()
                Sale.query.filter_by(id=venta_sec.id).delete()
                
        m_sec.estado = 'unida'
        m_sec.mesa_padre_id = mesa_principal.id
        
    mesa_principal.estado = 'ocupada'
    
    # Recalcular subtotal y total de la venta principal
    if venta_principal:
        sub = sum(d.precio_venta_final * d.cantidad_vendida for d in venta_principal.detalles if not d.es_cortesia)
        desc = venta_principal.monto_descuento or Decimal('0.00')
        prop_pct = venta_principal.porcentaje_propina or Decimal('10.00')
        prop_monto = sub * (prop_pct / Decimal('100.00'))
        
        venta_principal.subtotal = Decimal(str(sub))
        venta_principal.monto_propina = Decimal(str(round(float(prop_monto), 2)))
        venta_principal.monto_total = Decimal(str(round(float(sub - desc + prop_monto), 2)))

    db.session.commit()
    
    return jsonify({'mensaje': 'Mesas unidas y consumos consolidados exitosamente.'})

@tables_bp.route('/api/separar', methods=['POST'])
@login_required
def api_separar_mesa():
    data = request.get_json() or {}
    mesa_id = data.get('mesa_id')
    mesa = Mesa.query.get_or_404(mesa_id)
    
    mesa.estado = 'libre'
    mesa.mesa_padre_id = None
    db.session.commit()
    
    return jsonify({'mensaje': f'Mesa "{mesa.nombre}" separada y liberada.'})

@tables_bp.route('/api/editar', methods=['POST'])
@login_required
def api_editar_mesa():
    data = request.get_json() or {}
    mesa_id = data.get('id')
    nombre = str(data.get('nombre', '')).strip()
    capacidad = int(data.get('capacidad', 4))

    if not mesa_id:
        return jsonify({'error': 'ID de mesa no especificado.'}), 400

    mesa = Mesa.query.get_or_404(mesa_id)

    if not nombre:
        return jsonify({'error': 'El nombre de la mesa es obligatorio.'}), 400

    # Verificar si el nombre ya existe en otra mesa
    existente = Mesa.query.filter(Mesa.nombre == nombre, Mesa.id != mesa_id).first()
    if existente:
        return jsonify({'error': f'La mesa con nombre "{nombre}" ya existe.'}), 400

    mesa.nombre = nombre
    mesa.capacidad = capacidad
    db.session.commit()

    return jsonify({'mensaje': f'Mesa "{nombre}" actualizada con éxito.'})

@tables_bp.route('/api/eliminar', methods=['POST'])
@login_required
def api_eliminar_mesa():
    data = request.get_json() or {}
    mesa_id = data.get('id')
    
    if not mesa_id:
        return jsonify({'error': 'ID de mesa no especificado.'}), 400

    mesa = Mesa.query.get_or_404(mesa_id)

    # Validar si tiene una venta abierta
    venta_abierta = Sale.query.filter_by(table_id=mesa.id, estado_cuenta='abierta').first()
    if venta_abierta:
        return jsonify({'error': f'No se puede eliminar la mesa "{mesa.nombre}" porque tiene una cuenta abierta activa.'}), 400

    nombre_mesa = mesa.nombre

    # Desvincular ventas pasadas cerradas para evitar fallos de Clave Foránea (FK)
    Sale.query.filter_by(table_id=mesa.id).update({'table_id': None})
    
    # Desvincular mesas secundarias si tenía mesas unidas
    Mesa.query.filter_by(mesa_padre_id=mesa.id).update({'mesa_padre_id': None})

    db.session.delete(mesa)
    db.session.commit()

    return jsonify({'mensaje': f'Mesa "{nombre_mesa}" eliminada con éxito.'})

@tables_bp.route('/api/limpiar_cuenta', methods=['POST'])
@login_required
def api_limpiar_cuenta_mesa():
    """Limpia/cancela la cuenta abierta guardada de una mesa y restablece su estado a libre."""
    data = request.get_json() or {}
    mesa_id = data.get('table_id')

    if not mesa_id:
        return jsonify({'error': 'ID de mesa no especificado.'}), 400

    mesa = Mesa.query.get_or_404(mesa_id)
    target_id = mesa.id
    if mesa.mesa_padre_id:
        target_id = mesa.mesa_padre_id

    venta_abierta = Sale.query.filter_by(table_id=target_id, estado_cuenta='abierta').first()

    if venta_abierta:
        # Restaurar stock de productos e insumos descontados
        for d in venta_abierta.detalles:
            if d.producto and d.producto.tipo_producto not in ['producto_final', 'combo', 'preparado']:
                d.producto.cantidad_stock = float(d.producto.cantidad_stock or 0.0) + float(d.cantidad_vendida)
                if d.variante:
                    d.variante.cantidad_stock = float(d.variante.cantidad_stock or 0.0) + float(d.cantidad_vendida)
            if d.producto and d.producto.recetas:
                for r in d.producto.recetas:
                    if r.insumo and r.insumo.tipo_producto not in ['combo', 'preparado']:
                        r.insumo.cantidad_stock = float(r.insumo.cantidad_stock or 0.0) + (float(r.cantidad_requerida) * float(d.cantidad_vendida))

        # Marcar la venta como cancelada
        venta_abierta.estado_cuenta = 'cancelada'

    # Desvincular mesas secundarias si estaban unidas y liberar todas las mesas asociadas
    Mesa.query.filter_by(mesa_padre_id=target_id).update({'mesa_padre_id': None, 'estado': 'libre'})
    mesa_principal = Mesa.query.get(target_id)
    if mesa_principal:
        mesa_principal.estado = 'libre'

    db.session.commit()

    return jsonify({'mensaje': f'La cuenta de la mesa "{mesa_principal.nombre if mesa_principal else mesa.nombre}" fue limpiada y la mesa liberada con éxito.'})
