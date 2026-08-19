from flask import Blueprint, request, jsonify, flash, redirect, render_template, abort, url_for, session
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, SaleDetail, SalePayment, SaleClient, Expense, Mesa, Categoria, User, obtener_hora_bogota
from decorators import admin_required
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

sales_bp = Blueprint('sales_bp', __name__)

@sales_bp.route('/', methods=['GET'])
@login_required
def index_caja():
    return redirect(url_for('tables_bp.mapa_mesas'))

@sales_bp.route('/nueva', methods=['GET', 'POST'])
@login_required # Importante: Te bloqueará el acceso si no hay current_user logeado (Flask-Login)
def procesar_venta():
    if request.method == 'GET':
        categorias = Categoria.query.filter(~Categoria.nombre.ilike('%insumo%')).order_by(Categoria.id).all()
        cat_insumos_ids = [c.id for c in Categoria.query.filter(Categoria.nombre.ilike('%insumo%')).all()]
        productos = Product.query.filter(
            Product.tipo_producto != 'insumo',
            ~Product.categoria_id.in_(cat_insumos_ids) if cat_insumos_ids else True
        ).all()
        mesas = Mesa.query.order_by(Mesa.id).all()
        meseros = User.query.all()

        mesa_id_param = request.args.get('mesa_id', type=int)
        items_iniciales = []
        mesero_id_inicial = current_user.id if current_user.rol in ['mesero', 'vendedor', 'cajero'] else None
        porcentaje_propina_inicial = 10
        monto_descuento_inicial = 0
        aplica_recargo_inicial = False

        if mesa_id_param:
            m_target = Mesa.query.get(mesa_id_param)
            if m_target and m_target.mesa_padre_id:
                mesa_id_param = m_target.mesa_padre_id

            venta_abierta = Sale.query.filter_by(table_id=mesa_id_param, estado_cuenta='abierta').first()
            if venta_abierta:
                mesero_id_inicial = venta_abierta.mesero_id or current_user.id
                porcentaje_propina_inicial = float(venta_abierta.porcentaje_propina or 10)
                monto_descuento_inicial = float(venta_abierta.monto_descuento or 0)
                aplica_recargo_inicial = bool(venta_abierta.aplica_recargo_datafono)
                for d in venta_abierta.detalles:
                    prod = d.producto
                    es_manual = (d.product_id is None)
                    nombre_prod = getattr(d, 'nombre_manual', None) if es_manual else (prod.nombre if prod else 'Producto')
                    items_iniciales.append({
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
                        'variant_id': d.variant_id
                    })

        return render_template('sales/nueva.html', 
                               categorias=categorias, 
                               productos=productos, 
                               mesas=mesas, 
                               meseros=meseros,
                               items_iniciales=items_iniciales,
                               mesero_id_inicial=mesero_id_inicial,
                               porcentaje_propina_inicial=porcentaje_propina_inicial,
                               monto_descuento_inicial=monto_descuento_inicial,
                               aplica_recargo_inicial=aplica_recargo_inicial)

    """
    Se espera que los datos vengan en el cuerpo de la petición (JSON)
    Ej: {'items': [{ 'product_id': 1, 'cantidad': 2, 'precio_final': 15.50}, ...], 'metodo_pago': 'transferencia'}
    """
    data = request.get_json()
    items = data.get('items', [])
    pagos_data = data.get('pagos', [])  # Nuevo: array de pagos mixtos
    metodo_pago_legacy = data.get('metodo_pago', 'efectivo')  # Retrocompatibilidad
    
    if not items:
        return jsonify({'error': 'No se enviaron productos para la venta'}), 400

    # Si no se envían pagos en el nuevo formato, crear uno único con el método legacy
    if not pagos_data:
        pagos_data = [{'metodo_pago': metodo_pago_legacy, 'monto': None}]  # monto=None se llenará con el total

    try:
        # Determinar el método de pago principal (para la columna legacy de retrocompatibilidad)
        if len(pagos_data) == 1:
            metodo_pago_principal = pagos_data[0].get('metodo_pago', 'efectivo')
        else:
            metodo_pago_principal = 'mixto'

        # Manejar Fecha de Venta para registros de fechas anteriores
        from models import Turno
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        if not turno_abierto:
            return jsonify({'error': 'No hay un turno abierto. Por favor abre un turno antes de facturar.'}), 400

        fecha_venta_str = data.get('fecha_venta')
        fecha_venta_obj = obtener_hora_bogota()
        if fecha_venta_str:
            try:
                fecha_seleccionada = datetime.strptime(fecha_venta_str, '%Y-%m-%d').date()
                if fecha_seleccionada != fecha_venta_obj.date():
                    # Si no es hoy, combinamos la fecha seleccionada con la hora actual para conservar secuencialidad de hora de registro
                    fecha_venta_obj = datetime.combine(fecha_seleccionada, fecha_venta_obj.time())
            except ValueError:
                pass # Fallback silencioso a la hora actual si el formato falla

        # Calcular número de turno (reinicia diariamente)
        hoy_inicio = fecha_venta_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        ventas_hoy_count = Sale.query.filter(Sale.fecha_venta >= hoy_inicio).count()
        numero_turno = ventas_hoy_count + 1

        # Parámetros avanzados de POS Bar & Comidas
        table_id = data.get('table_id')
        mesero_id = data.get('mesero_id')
        porcentaje_propina = Decimal(str(data.get('porcentaje_propina', '0.00')))
        monto_descuento = Decimal(str(data.get('monto_descuento', '0.00')))
        aplica_recargo_datafono = bool(data.get('aplica_recargo_datafono', False))
        estado_cuenta = data.get('estado_cuenta', 'pagada')

        if estado_cuenta == 'abierta' and not table_id:
            return jsonify({'error': 'Las ventas directas en caja no admiten cuenta abierta ni comanda. Deben ser cobradas y facturadas de inmediato.'}), 400

        nueva_venta = None
        if table_id:
            m_target = Mesa.query.get(int(table_id))
            if m_target and m_target.mesa_padre_id:
                table_id = m_target.mesa_padre_id
            nueva_venta = Sale.query.filter_by(table_id=int(table_id), estado_cuenta='abierta').first()

        cantidades_previas = {}
        if nueva_venta:
            for d_ant in nueva_venta.detalles:
                p_id = d_ant.product_id or 0
                v_id = d_ant.variant_id or 0
                cort = bool(d_ant.es_cortesia)
                cantidades_previas[(p_id, v_id, cort)] = cantidades_previas.get((p_id, v_id, cort), 0) + d_ant.cantidad_vendida

            # Reutilizar la venta abierta existente: restaurar stock antiguo y reemplazar detalles
            for d_ant in nueva_venta.detalles:
                if d_ant.producto and d_ant.producto.tipo_producto not in ['producto_final', 'combo', 'preparado']:
                    d_ant.producto.cantidad_stock += d_ant.cantidad_vendida
                    if d_ant.variante:
                        d_ant.variante.cantidad_stock += d_ant.cantidad_vendida

            SaleDetail.query.filter_by(sale_id=nueva_venta.id).delete()
            if estado_cuenta != 'abierta':
                SalePayment.query.filter_by(sale_id=nueva_venta.id).delete()

            nueva_venta.vendedor_id = current_user.id
            nueva_venta.mesero_id = int(mesero_id) if mesero_id else None
            nueva_venta.metodo_pago = metodo_pago_principal
            nueva_venta.porcentaje_propina = porcentaje_propina
            nueva_venta.monto_descuento = monto_descuento
            nueva_venta.aplica_recargo_datafono = aplica_recargo_datafono
            nueva_venta.estado_cuenta = estado_cuenta
        else:
            nueva_venta = Sale(
                vendedor_id=current_user.id,
                mesero_id=int(mesero_id) if mesero_id else None,
                table_id=int(table_id) if table_id else None,
                monto_total=Decimal('0.00'),
                metodo_pago=metodo_pago_principal,
                fecha_venta=fecha_venta_obj,
                numero_turno=numero_turno,
                porcentaje_propina=porcentaje_propina,
                monto_descuento=monto_descuento,
                aplica_recargo_datafono=aplica_recargo_datafono,
                estado_cuenta=estado_cuenta,
                turno_id=turno_abierto.id
            )
            db.session.add(nueva_venta)

        db.session.flush()

        subtotal = Decimal('0.00')
        monto_cortesia = Decimal('0.00')
        items_adicion = []

        for item in items:
            product_id = item.get('product_id')
            variant_id = item.get('variant_id') # Posible variante
            cantidad_vendida = int(item.get('cantidad', 0))
            precio_venta_final = Decimal(str(item.get('precio_final', '0.00')))
            es_manual = item.get('es_manual', False)
            es_cortesia = (item.get('es_cortesia') in [True, 1, 'true', 'True', '1', 't', 'T'])
            notas = item.get('notas', '')

            if cantidad_vendida <= 0:
                raise ValueError("La cantidad vendida debe ser mayor a 0.")

            # Calcular la adición incremental (solo lo nuevo pedido en esta ronda)
            p_key_id = (product_id or 0) if not es_manual else -1
            v_key_id = variant_id or 0
            prev_qty = cantidades_previas.get((p_key_id, v_key_id, es_cortesia), 0)
            cant_adicion = max(0, cantidad_vendida - prev_qty)
            cantidades_previas[(p_key_id, v_key_id, es_cortesia)] = max(0, prev_qty - cantidad_vendida)

            if cant_adicion > 0:
                prod_obj = Product.query.get(product_id) if (product_id and not es_manual) else None
                nombre_item = item.get('nombre_manual') if es_manual else (prod_obj.nombre if prod_obj else item.get('nombre', 'Producto'))
                items_adicion.append({
                    'product_id': product_id,
                    'nombre': nombre_item,
                    'cantidad': cant_adicion,
                    'notas': notas,
                    'es_cortesia': es_cortesia,
                    'cortesia_para': item.get('cortesia_para', '')
                })

            if es_manual:
                # Producto manual (prestado de otro local) — no descuenta stock
                nombre_manual = item.get('nombre_manual', 'Producto Externo')
                precio_costo_manual = Decimal(str(item.get('precio_costo', '0.00')))

                cortesia_para = str(item.get('cortesia_para') or '').strip() if es_cortesia else None
                if es_cortesia and not cortesia_para:
                    cortesia_para = 'No especificado'

                detalle = SaleDetail(
                    sale_id=nueva_venta.id,
                    product_id=None,
                    variant_id=None,
                    cantidad_vendida=cantidad_vendida,
                    precio_venta_final=precio_venta_final,
                    es_cortesia=es_cortesia,
                    cortesia_para=cortesia_para,
                    nombre_manual=nombre_manual,
                    precio_costo_manual=precio_costo_manual
                )
                db.session.add(detalle)
                if not es_cortesia:
                    subtotal += (precio_venta_final * cantidad_vendida)
                else:
                    monto_cortesia += (precio_venta_final * cantidad_vendida)

                # Crear el gasto automático para descontar el ingreso prestado del balance final
                if precio_costo_manual > 0:
                    gasto_externo = Expense(
                        usuario_id=current_user.id,
                        tipo_gasto='Gasto Diario',
                        categoria='Pago Prod. Externo',
                        descripcion=f"Pago por producto manual prestado: {nombre_manual}",
                        monto=(precio_costo_manual * cantidad_vendida),
                        fecha_gasto=fecha_venta_obj,
                        turno_id=turno_abierto.id
                    )
                    db.session.add(gasto_externo)
            else:
                # Producto del inventario propio
                producto = Product.query.with_for_update().get(product_id)
                
                if not producto:
                    raise ValueError(f"El producto con ID {product_id} no existe.")

                botellaje_val = Decimal(str(producto.comision_mesero or '0.00'))

                if variant_id:
                    variante = ProductVariant.query.with_for_update().get(variant_id)
                    if not variante:
                        raise ValueError(f"La variante con ID {variant_id} no existe.")
                    if cantidad_vendida > variante.cantidad_stock and producto.tipo_producto not in ['producto_final', 'combo', 'preparado']:
                        raise ValueError(f"Stock insuficiente para la variante '{variante.nombre_variante}' de '{producto.nombre}'. Solicitado: {cantidad_vendida}, Disponible: {variante.cantidad_stock}.")
                    
                    variante.cantidad_stock -= cantidad_vendida
                    producto.cantidad_stock -= cantidad_vendida # Sincronizar producto base
                    precio_limite_autorizado = variante.precio_costo if current_user.rol == 'admin' else variante.precio_minimo
                else:
                    if producto.tipo_producto not in ['producto_final', 'combo', 'preparado']:
                        if cantidad_vendida > producto.cantidad_stock:
                            raise ValueError(f"Stock insuficiente para el producto '{producto.nombre}'. Solicitado: {cantidad_vendida}, Disponible: {producto.cantidad_stock}.")
                        producto.cantidad_stock -= cantidad_vendida
                    precio_limite_autorizado = producto.precio_costo if current_user.rol == 'admin' else producto.precio_minimo

                # Procesar siempre los insumos / productos componentes si tiene receta o es combo
                if producto.recetas and len(producto.recetas) > 0:
                    for receta in producto.recetas:
                        item_componente = receta.insumo
                        cant_desc = float(receta.cantidad_requerida) * float(cantidad_vendida)
                        stock_disp = float(item_componente.cantidad_stock or 0.0)
                        if stock_disp < cant_desc and item_componente.tipo_producto not in ['combo', 'preparado']:
                            raise ValueError(f"Stock insuficiente de '{item_componente.nombre}' para preparar '{producto.nombre}'. Solicitado: {cant_desc:.2f} {item_componente.unidad_medida_display}, Disponible: {stock_disp:.2f} {item_componente.unidad_medida_display}.")
                        item_componente.cantidad_stock = stock_disp - cant_desc

                if not es_cortesia and precio_venta_final < precio_limite_autorizado:
                    raise ValueError(f"No autorizado: El precio (${precio_venta_final}) del producto '{producto.nombre}' está por debajo del límite permitido (${precio_limite_autorizado}).")

                cortesia_para = str(item.get('cortesia_para') or '').strip() if es_cortesia else None
                if es_cortesia and not cortesia_para:
                    cortesia_para = 'No especificado'

                detalle = SaleDetail(
                    sale_id=nueva_venta.id,
                    product_id=producto.id,
                    variant_id=variant_id,
                    cantidad_vendida=cantidad_vendida,
                    precio_venta_final=Decimal('0.00') if es_cortesia else precio_venta_final,
                    es_cortesia=es_cortesia,
                    cortesia_para=cortesia_para,
                    botellaje_unitario=botellaje_val,
                    notas=item.get('notas', '')
                )
                db.session.add(detalle)
                
                if not es_cortesia:
                    subtotal += (precio_venta_final * cantidad_vendida)
                else:
                    monto_cortesia += (precio_venta_final * cantidad_vendida)

        # Cálculos de Propina, Recargo Datafono y Total Final
        monto_propina = Decimal(str(round(float(subtotal) * (float(porcentaje_propina) / 100.0), 2)))
        
        # Calcular recargo de Datafono (5%) si aplica
        monto_datafono_total = Decimal('0.00')
        total_pagos = Decimal('0.00')

        for pago_info in pagos_data:
            metodo = pago_info.get('metodo_pago', 'efectivo')
            monto_pago = pago_info.get('monto')
            
            if monto_pago is None:
                # Se calculará al final del recorrido
                pass
            else:
                monto_pago = Decimal(str(monto_pago))
                total_pagos += monto_pago
                if metodo == 'datafono':
                    monto_datafono_total += monto_pago

        monto_recargo_datafono = Decimal('0.00')
        if aplica_recargo_datafono and monto_datafono_total > 0:
            monto_recargo_datafono = Decimal(str(round(float(monto_datafono_total) * 0.05, 2)))

        monto_total = subtotal - monto_descuento + monto_propina + monto_recargo_datafono
        if monto_total < 0: monto_total = Decimal('0.00')

        nueva_venta.subtotal = subtotal
        nueva_venta.monto_propina = monto_propina
        nueva_venta.monto_cortesia = monto_cortesia
        nueva_venta.monto_recargo_datafono = monto_recargo_datafono
        nueva_venta.monto_total = monto_total

        # Registrar los pagos solo si la venta está siendo pagada
        if estado_cuenta == 'pagada':
            if not pagos_data or (len(pagos_data) == 1 and pagos_data[0].get('monto') is None):
                # Pago único completo
                metodo_unico = pagos_data[0].get('metodo_pago', 'efectivo') if pagos_data else 'efectivo'
                if metodo_unico == 'datafono' and aplica_recargo_datafono:
                    monto_recargo_datafono = Decimal(str(round(float(monto_total) * 0.05, 2)))
                    monto_total += monto_recargo_datafono
                    nueva_venta.monto_recargo_datafono = monto_recargo_datafono
                    nueva_venta.monto_total = monto_total

                pago = SalePayment(sale_id=nueva_venta.id, metodo_pago=metodo_unico, monto=monto_total)
                db.session.add(pago)
            else:
                for pago_info in pagos_data:
                    metodo = pago_info.get('metodo_pago', 'efectivo')
                    monto_pago = Decimal(str(pago_info.get('monto', 0)))
                    pago = SalePayment(sale_id=nueva_venta.id, metodo_pago=metodo, monto=monto_pago)
                    db.session.add(pago)

        # Actualizar estado de la Mesa si fue seleccionada
        if table_id:
            mesa_obj = Mesa.query.get(table_id)
            if mesa_obj:
                if estado_cuenta == 'pagada':
                    mesa_obj.estado = 'libre'
                else:
                    mesa_obj.estado = 'ocupada'

        # Guardar datos del cliente si aplican
        cliente_data = data.get('cliente')
        if cliente_data and isinstance(cliente_data, dict):
            cliente = SaleClient(
                sale_id=nueva_venta.id,
                nombre=cliente_data.get('nombre', 'Desconocido').strip(),
                documento=cliente_data.get('documento', '0').strip(),
                telefono=cliente_data.get('telefono', '').strip()
            )
            db.session.add(cliente)

        db.session.commit()
        
        if items_adicion:
            session[f'comanda_adicion_{nueva_venta.id}'] = items_adicion
        else:
            session.pop(f'comanda_adicion_{nueva_venta.id}', None)

        return jsonify({
            'success': True, 
            'message': 'Cuenta/Venta registrada con éxito.',
            'sale_id': nueva_venta.id,
            'total': str(monto_total),
            'numero_turno': numero_turno
        }), 201

    except ValueError as val_err:
        db.session.rollback()
        return jsonify({'error': str(val_err)}), 400
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error interno: {str(e)}'}), 500

# Endpoint API asíncrono para el escáner del Punto de Venta
@sales_bp.route('/api/producto/<path:sku>', methods=['GET'])
@login_required
def api_buscar_producto(sku):
    producto = Product.query.filter(Product.sku == sku, Product.tipo_inventario.in_(['tienda', 'celulares'])).first()
    auto_select_variant = None
    
    if not producto:
        # Búsqueda por IMEI en variantes de celulares
        variante = ProductVariant.query.join(Product).filter(
            Product.tipo_inventario == 'celulares',
            ProductVariant.nombre_variante.like(f"%{sku}%")
        ).first()
        
        if variante:
            producto = variante.producto
            auto_select_variant = variante.id
        else:
            return jsonify({'error': 'Código SKU o IMEI no encontrado en el sistema'}), 404
        
    return jsonify({
        'id': producto.id,
        'nombre': producto.nombre,
        'sku': producto.sku,
        'tipo_producto': producto.tipo_producto,
        'tipo_inventario': producto.tipo_inventario,
        'cantidad_stock': producto.total_stock,
        'precio_minimo': float(producto.precio_minimo),
        'precio_limite': float(producto.precio_costo) if current_user.rol == 'admin' else float(producto.precio_minimo),
        'precio_sugerido': float(producto.precio_sugerido),
        'variantes': [{"id": v.id, "nombre": v.nombre_variante, "stock": v.cantidad_stock, "precio_minimo": float(v.precio_minimo or producto.precio_minimo), "precio_limite": float(v.precio_costo or producto.precio_costo) if current_user.rol == 'admin' else float(v.precio_minimo or producto.precio_minimo), "precio_sugerido": float(v.precio_sugerido or producto.precio_sugerido)} for v in producto.variantes],
        'auto_select_variant': auto_select_variant
    })

# Ruta para la Impresión del formato Térmico (Ticket)
@sales_bp.route('/recibo/<int:sale_id>', methods=['GET'])
@sales_bp.route('/ticket/<int:sale_id>', methods=['GET'])
@login_required # Proteger confidencialidad del cajero
def imprimir_ticket(sale_id):
    # Regla: Retorna 404 si alguien ingresa un ID falso
    venta = Sale.query.get_or_404(sale_id)
    return render_template('sales/ticket.html', venta=venta)

# Endpoint Historial de Ventas (Administradores)
@sales_bp.route('/historial', methods=['GET'])
@login_required
@admin_required
def historial():
    # Calcular el valor exacto de 'HOY' en Bogotá
    hoy_bogota = obtener_hora_bogota().strftime('%Y-%m-%d')
    
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    
    hoy = obtener_hora_bogota()
    if not fecha_inicio or not fecha_fin:
        import calendar
        primer_dia = hoy.replace(day=1)
        ultimo_dia_num = calendar.monthrange(hoy.year, hoy.month)[1]
        ultimo_dia = hoy.replace(day=ultimo_dia_num)
            
        fecha_inicio = primer_dia.strftime('%Y-%m-%d')
        fecha_fin = ultimo_dia.strftime('%Y-%m-%d')
    
    # Optimización: eager loading (evita N+1 con joinedload)
    # IMPORTANTE: Filtrar para que NO salgan las ventas abiertas (cuentas sin pagar)
    query = Sale.query.options(joinedload(Sale.vendedor)).filter(Sale.estado_cuenta != 'abierta')
    
    # Motor de búsqueda por Rango Restricto
    if fecha_inicio:
        inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        query = query.filter(Sale.fecha_venta >= inicio_dt)
        
    if fecha_fin:
        fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        # Sumar 1 día matemáticamente para incluir los registros hasta las 23:59:59 del último día
        query = query.filter(Sale.fecha_venta < fin_dt + timedelta(days=1))
        
    # Restricción de perfil: Si no es admin, solo ve sus propias ventas
    if current_user.rol != 'admin':
        query = query.filter(Sale.vendedor_id == current_user.id)
        
    ventas = query.order_by(Sale.fecha_venta.desc()).all()
    
    # Auditar y cruzar sumatorios de métricas de pago (100% de conciliación)
    total_efectivo = Decimal('0')
    total_nequi = Decimal('0')
    total_daviplata = Decimal('0')
    total_llave = Decimal('0')
    total_datafono = Decimal('0')
    total_mixto_conteo = 0
    total_mixto_monto = Decimal('0')

    for v in ventas:
        if v.pagos:  # Ventas con tabla sale_payments
            for pago in v.pagos:
                metodo_normalizado = (pago.metodo_pago or 'efectivo').lower().strip()
                if metodo_normalizado in ['efectivo', 'cash']:
                    total_efectivo += pago.monto
                elif metodo_normalizado in ['nequi']:
                    total_nequi += pago.monto
                elif metodo_normalizado in ['daviplata']:
                    total_daviplata += pago.monto
                elif metodo_normalizado in ['llave', 'bre_b', 'bre-b', 'bancolombia', 'transferencia', 'banco']:
                    total_llave += pago.monto
                elif metodo_normalizado in ['datafono', 'tarjeta', 'tarjeta_credito', 'tarjeta_debito', 'pos']:
                    total_datafono += pago.monto
                else:
                    total_llave += pago.monto

            if len(v.pagos) > 1:
                total_mixto_conteo += 1
                total_mixto_monto += v.monto_total
        else:  # Retrocompatibilidad con ventas antiguas
            metodo_normalizado = (v.metodo_pago or 'efectivo').lower().strip()
            if metodo_normalizado in ['efectivo', 'cash']:
                total_efectivo += v.monto_total
            elif metodo_normalizado in ['nequi']:
                total_nequi += v.monto_total
            elif metodo_normalizado in ['daviplata']:
                total_daviplata += v.monto_total
            elif metodo_normalizado in ['llave', 'bre_b', 'bre-b', 'bancolombia', 'transferencia', 'banco']:
                total_llave += v.monto_total
            elif metodo_normalizado in ['datafono', 'tarjeta', 'tarjeta_credito', 'tarjeta_debito', 'pos']:
                total_datafono += v.monto_total
            else:
                total_efectivo += v.monto_total

    total_general = total_efectivo + total_nequi + total_daviplata + total_llave + total_datafono

    # Envío al Engine de HTML
    return render_template('sales/historial.html', 
                           ventas=ventas, 
                           total_efectivo=total_efectivo,
                           total_nequi=total_nequi,
                           total_daviplata=total_daviplata,
                           total_llave=total_llave,
                           total_datafono=total_datafono,
                           total_mixto_conteo=total_mixto_conteo,
                           total_mixto_monto=total_mixto_monto,
                           total_general=total_general,
                           fecha_inicio=fecha_inicio,
                           fecha_fin=fecha_fin)


# Endpoint Visor de Ventas del Día para Cajeros (Solo lectura, se resetea cada día)
@sales_bp.route('/ventas_hoy', methods=['GET'])
@login_required
def ventas_hoy():
    hoy_bogota = obtener_hora_bogota().date()
    from models import Turno
    turno_abierto = Turno.query.filter_by(estado='abierto').first()
    
    if turno_abierto:
        query = Sale.query.options(joinedload(Sale.vendedor)).filter(Sale.turno_id == turno_abierto.id)
    else:
        query = Sale.query.filter(False) # No hay turno, no hay ventas

    if current_user.rol != 'admin':
        query = query.filter(Sale.vendedor_id == current_user.id)
        
    ventas = query.order_by(Sale.fecha_venta.desc()).all()
    
    # Acumuladores de las ventas de hoy
    total_efectivo = Decimal('0')
    total_nequi = Decimal('0')
    total_daviplata = Decimal('0')
    total_llave = Decimal('0')
    total_datafono = Decimal('0')
    total_mixto_conteo = 0
    total_mixto_monto = Decimal('0')
    
    for v in ventas:
        if v.pagos:
            for pago in v.pagos:
                metodo = (pago.metodo_pago or 'efectivo').lower().strip()
                if metodo in ['efectivo', 'cash']:
                    total_efectivo += pago.monto
                elif metodo in ['nequi']:
                    total_nequi += pago.monto
                elif metodo in ['daviplata']:
                    total_daviplata += pago.monto
                elif metodo in ['llave', 'bre_b', 'bre-b', 'bancolombia', 'transferencia']:
                    total_llave += pago.monto
                elif metodo in ['datafono', 'tarjeta', 'tarjeta_credito', 'tarjeta_debito']:
                    total_datafono += pago.monto
                else:
                    total_llave += pago.monto

            if len(v.pagos) > 1:
                total_mixto_conteo += 1
                total_mixto_monto += v.monto_total
        else:
            metodo = (v.metodo_pago or 'efectivo').lower().strip()
            if metodo in ['efectivo', 'cash']:
                total_efectivo += v.monto_total
            elif metodo in ['nequi']:
                total_nequi += v.monto_total
            elif metodo in ['daviplata']:
                total_daviplata += v.monto_total
            elif metodo in ['llave', 'bre_b', 'bre-b', 'bancolombia', 'transferencia']:
                total_llave += v.monto_total
            elif metodo in ['datafono', 'tarjeta']:
                total_datafono += v.monto_total
            else:
                total_efectivo += v.monto_total

    total_general = total_efectivo + total_nequi + total_daviplata + total_llave + total_datafono
                
    return render_template('sales/ventas_hoy.html',
                           ventas=ventas,
                           total_efectivo=total_efectivo,
                           total_nequi=total_nequi,
                           total_daviplata=total_daviplata,
                           total_llave=total_llave,
                           total_datafono=total_datafono,
                           total_mixto_conteo=total_mixto_conteo,
                           total_mixto_monto=total_mixto_monto,
                           total_general=total_general,
                           hoy=hoy_bogota.strftime('%Y-%m-%d'),
                           turno=turno_abierto)


# Endpoint para Anular/Eliminar Venta Histórica
@sales_bp.route('/eliminar/<int:sale_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_venta(sale_id):
    venta = Sale.query.get_or_404(sale_id)
    
    try:
        # Revertir Stock
        for detalle in venta.detalles:
            producto = Product.query.with_for_update().get(detalle.product_id)
            if not producto:
                continue
                
            if detalle.variant_id:
                variante = ProductVariant.query.with_for_update().get(detalle.variant_id)
                if variante:
                    variante.cantidad_stock += detalle.cantidad_vendida
                producto.cantidad_stock += detalle.cantidad_vendida
            else:
                producto.cantidad_stock += detalle.cantidad_vendida
                
            # Revertir siempre insumos si tiene receta
            if producto.recetas and len(producto.recetas) > 0:
                for receta in producto.recetas:
                    insumo = receta.insumo
                    if insumo:
                        insumo.cantidad_stock += (receta.cantidad_requerida * detalle.cantidad_vendida)
                    
        # Eliminar Venta y Detalles (Cascada)
        db.session.delete(venta)
        db.session.commit()
        flash('Venta anulada y stock devuelto exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Ocurrió un error al anular la venta.', 'danger')
        
    return redirect(url_for('sales_bp.historial'))


@sales_bp.route('/comanda/<int:sale_id>', methods=['GET'])
@login_required
def comanda_venta(sale_id):
    venta = Sale.query.get_or_404(sale_id)
    ver = request.args.get('ver')

    adicion_session = session.get(f'comanda_adicion_{sale_id}')
    es_adicion = (ver == 'adicion' or (ver != 'todo' and adicion_session is not None and len(adicion_session) > 0))

    items_barra = []
    items_cocina = []

    if es_adicion and adicion_session:
        for item_ad in adicion_session:
            p = Product.query.get(item_ad['product_id']) if item_ad.get('product_id') else None
            cat_nom = p.categoria.nombre.lower() if (p and p.categoria) else ''

            item_data = {
                'nombre': item_ad['nombre'],
                'cantidad': item_ad['cantidad'],
                'notas': item_ad.get('notas', ''),
                'es_cortesia': item_ad.get('es_cortesia', False),
                'cortesia_para': item_ad.get('cortesia_para', '')
            }

            if 'cerveza' in cat_nom or 'licor' in cat_nom or 'coctel' in cat_nom or 'cóctel' in cat_nom or 'bebida' in cat_nom or 'barra' in cat_nom:
                items_barra.append(item_data)
            else:
                items_cocina.append(item_data)
    else:
        for d in venta.detalles:
            p = Product.query.get(d.product_id) if d.product_id else None
            cat_nom = p.categoria.nombre.lower() if (p and p.categoria) else ''

            item_data = {
                'nombre': p.nombre if p else (d.nombre_manual or 'Producto'),
                'cantidad': d.cantidad_vendida,
                'notas': d.notas,
                'es_cortesia': d.es_cortesia,
                'cortesia_para': d.cortesia_para or ''
            }

            if 'cerveza' in cat_nom or 'licor' in cat_nom or 'coctel' in cat_nom or 'cóctel' in cat_nom or 'bebida' in cat_nom or 'barra' in cat_nom:
                items_barra.append(item_data)
            else:
                items_cocina.append(item_data)

    return render_template('sales/comanda.html', venta=venta, items_barra=items_barra, items_cocina=items_cocina, es_adicion=es_adicion)


@sales_bp.route('/api/cobro_parcial_split', methods=['POST'])
@login_required
def api_cobro_parcial_split():
    """Registra pagos parciales por persona al dividir cuentas en partes iguales."""
    data = request.get_json() or {}
    sale_id = data.get('sale_id')
    table_id = data.get('table_id')
    monto = Decimal(str(data.get('monto', '0.00')))
    metodo_pago = data.get('metodo_pago', 'efectivo')
    etiqueta = data.get('etiqueta', 'Pago Parcial')
    es_ultimo = bool(data.get('es_ultimo', False))

    if table_id and not sale_id:
        m_target = Mesa.query.get(int(table_id))
        if m_target and m_target.mesa_padre_id:
            table_id = m_target.mesa_padre_id
        v = Sale.query.filter_by(table_id=int(table_id), estado_cuenta='abierta').first()
        if v:
            sale_id = v.id

    if not sale_id:
        return jsonify({'error': 'No se encontró la orden abierta para registrar el cobro.'}), 400

    venta = Sale.query.get_or_404(sale_id)

    # Registrar el abono / pago parcial en SalePayment
    pago = SalePayment(sale_id=venta.id, metodo_pago=metodo_pago, monto=monto)
    db.session.add(pago)
    db.session.flush()

    total_pagado = sum(p.monto for p in venta.pagos)
    saldo_restante = max(Decimal('0.00'), venta.monto_total - total_pagado)
    mesa_liberada = False

    if saldo_restante <= Decimal('0.00') or es_ultimo:
        venta.estado_cuenta = 'pagada'
        if venta.mesa:
            venta.mesa.estado = 'libre'
            for h in venta.mesa.mesas_hijas:
                h.estado = 'libre'
                h.mesa_padre_id = None
            mesa_liberada = True

    db.session.commit()

    return jsonify({
        'success': True,
        'mensaje': f'Pago de {etiqueta} registrado con éxito (${monto:,.0f}).',
        'pago_id': pago.id,
        'sale_id': venta.id,
        'total_pagado': float(total_pagado),
        'monto_total': float(venta.monto_total),
        'saldo_restante': float(saldo_restante),
        'cuenta_cerrada': venta.estado_cuenta == 'pagada',
        'mesa_liberada': mesa_liberada
    })


