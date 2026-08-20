import os
import uuid
from datetime import datetime
from PIL import Image
from werkzeug.utils import secure_filename
from flask import current_app, Blueprint, render_template, request, redirect, url_for, flash, abort, send_file, jsonify
from flask_login import login_required, current_user
from models import db, Product, StockAdjustment, ProductVariant, Categoria, Receta, Provider, ProviderInvoice, obtener_hora_bogota
from decorators import admin_required
import pandas as pd
from io import BytesIO

inventory_bp = Blueprint('inventory_bp', __name__)

def guardar_imagen(file):
    """Procesa, valida, optimiza y guarda una imagen subida usando Pillow."""
    if not file or file.filename == '':
        return None
    
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp']:
        return None
        
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    
    unique_filename = f"img_{uuid.uuid4().hex[:12]}.webp"
    target_path = os.path.join(upload_folder, unique_filename)
    
    try:
        img = Image.open(file)
        # Redimensionar si es muy grande manteniendo aspect ratio
        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        
        # Guardar en formato WebP optimizado
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img.save(target_path, 'WEBP', quality=85)
        else:
            img = img.convert('RGB')
            img.save(target_path, 'WEBP', quality=85)
            
        return unique_filename
    except Exception:
        # Fallback a guardado seguro
        safe_name = f"img_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
        fallback_path = os.path.join(upload_folder, safe_name)
        file.seek(0)
        file.save(fallback_path)
        return safe_name


def asegurar_categoria_combos():
    """Garantiza la existencia de la categoría oficial de Combos y reasigna combos huérfanos o mal asignados."""
    cat = Categoria.query.filter(Categoria.nombre.ilike('%combo%')).first()
    if not cat:
        cat = Categoria(nombre='Combos')
        db.session.add(cat)
        db.session.commit()
    elif cat.nombre != 'Combos':
        cat.nombre = 'Combos'
        db.session.commit()
    # Asegurar que todos los productos de tipo 'combo' pertenezcan exclusivamente a esta categoría
    combos_mal_asignados = Product.query.filter(
        Product.tipo_producto == 'combo',
        (Product.categoria_id == None) | (Product.categoria_id != cat.id)
    ).all()
    if combos_mal_asignados:
        for cb in combos_mal_asignados:
            cb.categoria_id = cat.id
        db.session.commit()
    return cat

import math

class InMemoryPagination:
    def __init__(self, page, per_page, total, items):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.items = items
        self.pages = int(math.ceil(total / float(per_page))) if per_page > 0 and total > 0 else 1

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else None

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def next_num(self):
        return self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=1, left_current=2, right_current=2, right_edge=1):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num >= self.page - left_current and num <= self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

@inventory_bp.route('/', methods=['GET'])
@login_required
@admin_required
def index():
    asegurar_categoria_combos()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    tipo_filtro = request.args.get('tipo', 'todos')
    categoria_filtro = request.args.get('categoria', 'todas')
    filtro_alerta = request.args.get('alerta', '')
    
    query = Product.query
    
    # Filtro por tipo de producto
    if tipo_filtro in ['insumo', 'insumos']:
        query = query.filter_by(tipo_producto='insumo')
    elif tipo_filtro in ['combo', 'combos']:
        query = query.filter_by(tipo_producto='combo')
    elif tipo_filtro in ['preparado', 'preparados']:
        query = query.filter_by(tipo_producto='preparado')
    elif tipo_filtro in ['producto_simple', 'productos']:
        query = query.filter(Product.tipo_producto.in_(['producto_simple', 'producto_final']))
    elif tipo_filtro != 'todos':
        query = query.filter_by(tipo_producto=tipo_filtro)

    # Filtro por categoría
    if categoria_filtro and categoria_filtro != 'todas':
        try:
            cat_id = int(categoria_filtro)
            query = query.filter_by(categoria_id=cat_id)
        except ValueError:
            pass

    # --- KPIs de Inventario Globales y Filtrados ---
    todos_sistema = Product.query.all()
    total_catalogo = len(todos_sistema)
    total_combos_global = sum(1 for p in todos_sistema if p.tipo_producto == 'combo')
    total_alertas_global = sum(1 for p in todos_sistema if p.es_bajo_stock)

    todos = query.order_by(Product.nombre).all()
    if filtro_alerta in ['1', 'true', 'critico', 'bajo']:
        todos = [p for p in todos if p.es_bajo_stock]
        total_productos = len(todos)
        start = (page - 1) * per_page
        end = start + per_page
        productos = todos[start:end]
        paginacion = InMemoryPagination(page=page, per_page=per_page, total=total_productos, items=productos)
    else:
        # Paginación del listado principal
        paginacion = query.order_by(Product.nombre).paginate(
            page=page, per_page=per_page, error_out=False
        )
        productos = paginacion.items
        total_productos = len(todos)

    valor_costo = 0.0
    valor_sugerido = 0.0
    for p in todos:
        if p.variantes:
            for v in p.variantes:
                costo = float(v.precio_costo or p.precio_costo or 0)
                sugerido = float(v.precio_sugerido or p.precio_sugerido or 0)
                stock = float(v.cantidad_stock or 0)
                valor_costo += costo * stock
                valor_sugerido += sugerido * stock
        else:
            costo = float(p.precio_costo or 0)
            sugerido = float(p.precio_sugerido or 0)
            stock = float(p.cantidad_stock or 0)
            valor_costo += costo * stock
            valor_sugerido += sugerido * stock

    categorias = Categoria.query.order_by(Categoria.id).all()
    
    # Conteo por categoría
    conteo_categorias = {}
    for cat in categorias:
        conteo_categorias[cat.id] = Product.query.filter_by(categoria_id=cat.id).count()

    return render_template(
        'inventory/index.html',
        productos=productos,
        paginacion=paginacion,
        total_productos=total_productos,
        total_catalogo=total_catalogo,
        total_combos_global=total_combos_global,
        total_alertas_global=total_alertas_global,
        valor_costo=valor_costo,
        valor_sugerido=valor_sugerido,
        tipo_filtro=tipo_filtro,
        categoria_filtro=categoria_filtro,
        filtro_alerta=filtro_alerta,
        categorias=categorias,
        conteo_categorias=conteo_categorias
    )

@inventory_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo():
    if request.method == 'POST':
        # --- Manejo de Imagen con Pillow ---
        imagen_filename = None
        if 'imagen' in request.files:
            imagen_filename = guardar_imagen(request.files['imagen'])

        # Recibir variantes
        v_nombres = request.form.getlist('v_nombre[]')
        v_stocks = request.form.getlist('v_stock[]')
        v_costos = request.form.getlist('v_costo[]')
        v_mins = request.form.getlist('v_min[]')
        v_sugs = request.form.getlist('v_sug[]')

        tipo_prod = request.form.get('tipo_producto', 'producto_simple')
        cat_id = request.form.get('categoria_id')

        # Si el ítem es un combo, se asocia estrictamente a la categoría oficial de Combos
        if tipo_prod == 'combo':
            cat_id = asegurar_categoria_combos().id

        # Si hay variantes o es combo/preparado, el stock base es 0
        stock_base = 0.0 if (v_nombres or tipo_prod in ['combo', 'preparado']) else float(request.form.get('cantidad_stock', 0.0) or 0.0)

        nuevo_prod = Product(
            sku=request.form.get('sku').strip(),
            nombre=request.form.get('nombre').strip(),
            tipo_producto=tipo_prod,
            categoria_id=int(cat_id) if cat_id else None,
            cantidad_stock=stock_base,
            precio_costo=float(request.form.get('precio_costo', 0.0) or 0.0),
            precio_minimo=float(request.form.get('precio_minimo', 0.0) or 0.0),
            precio_sugerido=float(request.form.get('precio_sugerido', 0.0) or 0.0),
            comision_mesero=float(request.form.get('comision_mesero', 0.0) or 0.0),
            imagen=imagen_filename,
            observacion=request.form.get('observacion')
        )
        
        try:
            db.session.add(nuevo_prod)
            db.session.flush() # Para obtener el ID del producto
            
            # Crear variantes si existen
            for i in range(len(v_nombres)):
                if not v_nombres[i]: continue
                nueva_v = ProductVariant(
                    product_id=nuevo_prod.id,
                    nombre_variante=v_nombres[i],
                    cantidad_stock=float(v_stocks[i] or 0.0),
                    precio_costo=float(v_costos[i]) if v_costos[i] else nuevo_prod.precio_costo,
                    precio_minimo=float(v_mins[i]) if v_mins[i] else nuevo_prod.precio_minimo,
                    precio_sugerido=float(v_sugs[i]) if v_sugs[i] else nuevo_prod.precio_sugerido
                )
                db.session.add(nueva_v)

            db.session.commit()
            
            # Crear ajuste inicial automáticamente en el Kardex si tiene stock
            if nuevo_prod.total_stock > 0:
                ajuste_inicial = StockAdjustment(
                    product_id=nuevo_prod.id,
                    admin_id=current_user.id,
                    tipo_movimiento='Creación Inicial' + (' (con Variantes)' if v_nombres else ''),
                    stock_anterior=0,
                    stock_nuevo=nuevo_prod.total_stock
                )
                db.session.add(ajuste_inicial)
                db.session.commit()

            # Vinculación y Carga a Cuenta Corriente del Proveedor
            provider_id_val = request.form.get('provider_id')
            cargar_cuenta = bool(request.form.get('cargar_factura_proveedor'))

            if provider_id_val and provider_id_val.isdigit() and int(provider_id_val) > 0 and cargar_cuenta:
                prov = Provider.query.get(int(provider_id_val))
                if prov:
                    total_compra = 0.0
                    if v_nombres:
                        for i in range(len(v_nombres)):
                            if v_nombres[i]:
                                stk = int(v_stocks[i] or 0)
                                cst = float(v_costos[i]) if v_costos[i] else float(nuevo_prod.precio_costo)
                                total_compra += stk * cst
                    else:
                        total_compra = float(stock_base) * float(nuevo_prod.precio_costo or 0.0)

                    if total_compra > 0:
                        num_fac = request.form.get('numero_factura_proveedor', '').strip()
                        nueva_factura_prov = ProviderInvoice(
                            provider_id=prov.id,
                            monto_total=total_compra,
                            numero_factura=num_fac if num_fac else f"INV-{nuevo_prod.sku or nuevo_prod.id}",
                            descripcion=f"Ingreso de inventario: {nuevo_prod.nombre} (x{nuevo_prod.total_stock} uds @ ${nuevo_prod.precio_costo:,.0f}/u)".replace(',', '.'),
                            fecha_factura=obtener_hora_bogota()
                        )
                        db.session.add(nueva_factura_prov)
                        db.session.commit()
                        flash(f'📄 Se cargó automáticamente una factura por ${total_compra:,.0f} a la cuenta del proveedor "{prov.nombre}".'.replace(',', '.'), 'info')

            # Sincronización de Recetas / Composición de Combos
            if tipo_prod in ['combo', 'preparado', 'producto_final']:
                r_insumos = request.form.getlist('receta_insumo_id[]')
                r_cants = request.form.getlist('receta_cantidad[]')
                for i in range(len(r_insumos)):
                    if r_insumos[i]:
                        receta = Receta(
                            producto_final_id=nuevo_prod.id,
                            insumo_id=int(r_insumos[i]),
                            cantidad_requerida=float(r_cants[i] or 1.0)
                        )
                        db.session.add(receta)
                db.session.commit()

            flash(f'{nuevo_prod.tipo_label} "{nuevo_prod.nombre}" creado exitosamente.', 'success')
            return redirect(url_for('inventory_bp.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al intentar guardar el producto: {str(e)}', 'danger')
            
    categorias = Categoria.query.order_by(Categoria.id).all()
    insumos = Product.query.filter_by(tipo_producto='insumo').order_by(Product.nombre).all()
    todos_productos = Product.query.order_by(Product.nombre).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('inventory/form.html', categorias=categorias, insumos=insumos, todos_productos=todos_productos, proveedores=proveedores)


# ═════════════════════════════════════════════════════════════════════════
# Formulario Standalone de Ingreso de Mercancía / Stock para Vendedor & Cajero
# ═════════════════════════════════════════════════════════════════════════
@inventory_bp.route('/ingreso', methods=['GET', 'POST'])
@login_required
def ingreso_mercancia():
    hoy_bogota = obtener_hora_bogota().date()
    
    if request.method == 'POST':
        modo = request.form.get('modo', 'existente') # 'existente' o 'nuevo'
        provider_id_val = request.form.get('provider_id')
        num_factura = request.form.get('numero_factura_proveedor', '').strip()
        cargar_cuenta = bool(request.form.get('cargar_factura_proveedor'))
        notas = request.form.get('observacion', '').strip()

        try:
            if modo == 'existente':
                prod_id = request.form.get('product_id', type=int)
                cantidad_entrada = int(request.form.get('cantidad', 0))
                costo_unitario = float(request.form.get('precio_costo', 0.0) or 0.0)

                if not prod_id or cantidad_entrada <= 0:
                    flash('⚠️ Debes seleccionar un producto e ingresar una cantidad mayor a cero.', 'danger')
                    return redirect(url_for('inventory_bp.ingreso_mercancia'))

                producto = Product.query.get_or_404(prod_id)
                stock_anterior = producto.total_stock
                producto.cantidad_stock = (producto.cantidad_stock or 0) + cantidad_entrada
                
                if costo_unitario > 0:
                    producto.precio_costo = costo_unitario

                # Registro en Kardex
                ajuste = StockAdjustment(
                    product_id=producto.id,
                    admin_id=current_user.id,
                    tipo_movimiento=f'Entrada de Mercancía (+{cantidad_entrada})',
                    stock_anterior=stock_anterior,
                    stock_nuevo=producto.total_stock
                )
                db.session.add(ajuste)
                db.session.commit()

                # Carga a cuenta corriente de proveedor
                if provider_id_val and provider_id_val.isdigit() and int(provider_id_val) > 0 and cargar_cuenta:
                    prov = Provider.query.get(int(provider_id_val))
                    total_factura = float(costo_unitario if costo_unitario > 0 else (producto.precio_costo or 0)) * float(cantidad_entrada)
                    if prov and total_factura > 0:
                        inv = ProviderInvoice(
                            provider_id=prov.id,
                            monto_total=total_factura,
                            numero_factura=num_factura if num_factura else f"REC-{producto.sku or producto.id}-{int(datetime.now().timestamp())%10000}",
                            descripcion=f"Ingreso stock: {cantidad_entrada}x {producto.nombre} @ ${producto.precio_costo:,.0f}/u ({notas or 'Reabastecimiento'})".replace(',', '.'),
                            fecha_factura=obtener_hora_bogota()
                        )
                        db.session.add(inv)
                        db.session.commit()
                        flash(f'✅ Entrada de {cantidad_entrada} uds de "{producto.nombre}" registrada y factura de ${total_factura:,.0f} cargada a {prov.nombre}.'.replace(',', '.'), 'success')
                    else:
                        flash(f'✅ Entrada de {cantidad_entrada} uds de "{producto.nombre}" registrada correctamente.', 'success')
                else:
                    flash(f'✅ Entrada de {cantidad_entrada} uds de "{producto.nombre}" registrada correctamente.', 'success')

            elif modo == 'nuevo':
                sku = request.form.get('sku', '').strip()
                nombre = request.form.get('nombre', '').strip()
                cat_id = request.form.get('categoria_id')
                tipo_prod = request.form.get('tipo_producto', 'producto_simple')
                cantidad_stock = int(request.form.get('cantidad_stock', 0) or 0)
                precio_costo = float(request.form.get('precio_costo', 0.0) or 0.0)
                precio_sugerido = float(request.form.get('precio_sugerido', 0.0) or 0.0)

                if not nombre:
                    flash('⚠️ El nombre del producto es obligatorio.', 'danger')
                    return redirect(url_for('inventory_bp.ingreso_mercancia'))

                if not sku:
                    sku = f"PROD-{uuid.uuid4().hex[:6].upper()}"

                nuevo_prod = Product(
                    sku=sku,
                    nombre=nombre,
                    categoria_id=int(cat_id) if cat_id else None,
                    tipo_producto=tipo_prod,
                    cantidad_stock=cantidad_stock,
                    precio_costo=precio_costo,
                    precio_minimo=0,
                    precio_sugerido=precio_sugerido,
                    observacion=notas
                )
                db.session.add(nuevo_prod)
                db.session.flush()

                if cantidad_stock > 0:
                    ajuste = StockAdjustment(
                        product_id=nuevo_prod.id,
                        admin_id=current_user.id,
                        tipo_movimiento=f'Ingreso Inicial de Mercancía (+{cantidad_stock})',
                        stock_anterior=0,
                        stock_nuevo=cantidad_stock
                    )
                    db.session.add(ajuste)

                db.session.commit()

                # Carga a cuenta corriente de proveedor
                if provider_id_val and provider_id_val.isdigit() and int(provider_id_val) > 0 and cargar_cuenta:
                    prov = Provider.query.get(int(provider_id_val))
                    total_factura = float(precio_costo) * float(cantidad_stock)
                    if prov and total_factura > 0:
                        inv = ProviderInvoice(
                            provider_id=prov.id,
                            monto_total=total_factura,
                            numero_factura=num_factura if num_factura else f"FAC-{nuevo_prod.sku}",
                            descripcion=f"Ingreso nuevo producto: {cantidad_stock}x {nuevo_prod.nombre} @ ${precio_costo:,.0f}/u".replace(',', '.'),
                            fecha_factura=obtener_hora_bogota()
                        )
                        db.session.add(inv)
                        db.session.commit()
                        flash(f'✅ Producto "{nuevo_prod.nombre}" registrado y factura de ${total_factura:,.0f} cargada a {prov.nombre}.'.replace(',', '.'), 'success')
                    else:
                        flash(f'✅ Producto "{nuevo_prod.nombre}" registrado exitosamente.', 'success')
                else:
                    flash(f'✅ Producto "{nuevo_prod.nombre}" registrado exitosamente.', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error al procesar el ingreso de mercancía: {str(e)}', 'danger')

        return redirect(url_for('inventory_bp.ingreso_mercancia'))

    # GET:
    productos = Product.query.filter(Product.tipo_producto.in_(['producto_simple', 'producto_final', 'insumo'])).order_by(Product.nombre.asc()).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    categorias = Categoria.query.order_by(Categoria.nombre.asc()).all()

    # Historial de entradas del día registradas por este usuario
    inicio_dt = datetime.combine(hoy_bogota, datetime.min.time())
    fin_dt = datetime.combine(hoy_bogota, datetime.max.time())
    ajustes_hoy = StockAdjustment.query.filter(
        StockAdjustment.admin_id == current_user.id,
        StockAdjustment.fecha_ajuste >= inicio_dt,
        StockAdjustment.fecha_ajuste <= fin_dt
    ).order_by(StockAdjustment.fecha_ajuste.desc()).all()

    return render_template(
        'inventory/ingreso_mercancia.html',
        productos=productos,
        proveedores=proveedores,
        categorias=categorias,
        ajustes_hoy=ajustes_hoy,
        hoy=hoy_bogota.strftime('%Y-%m-%d')
    )


@inventory_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_producto(id):
    producto = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        stock_total_anterior = producto.total_stock
        
        # Actualizar Imagen si se sube una nueva con Pillow
        if 'imagen' in request.files:
            nueva_img = guardar_imagen(request.files['imagen'])
            if nueva_img:
                producto.imagen = nueva_img
                
        # Datos básicos
        tipo_prod = request.form.get('tipo_producto', 'producto_simple')
        cat_id = request.form.get('categoria_id')
        if tipo_prod == 'combo':
            cat_id = asegurar_categoria_combos().id
        producto.sku = request.form.get('sku').strip()
        producto.nombre = request.form.get('nombre').strip()
        producto.tipo_producto = tipo_prod
        producto.categoria_id = int(cat_id) if cat_id else None
        producto.precio_costo = float(request.form.get('precio_costo', 0.0) or 0.0)
        producto.precio_minimo = float(request.form.get('precio_minimo', 0.0) or 0.0)
        producto.precio_sugerido = float(request.form.get('precio_sugerido', 0.0) or 0.0)
        producto.comision_mesero = float(request.form.get('comision_mesero', 0.0) or 0.0)
        producto.observacion = request.form.get('observacion')
        
        # Sincronización de Variantes
        v_ids = request.form.getlist('variant_id[]')
        v_nombres = request.form.getlist('v_nombre[]')
        v_stocks = request.form.getlist('v_stock[]')
        v_costos = request.form.getlist('v_costo[]')
        v_mins = request.form.getlist('v_min[]')
        v_sugs = request.form.getlist('v_sug[]')

        ids_en_formulario = [int(vid) for vid in v_ids if vid]
        
        # 1. Eliminar las que ya no están en el formulario
        for v_existente in producto.variantes[:]:
            if v_existente.id not in ids_en_formulario:
                db.session.delete(v_existente)
        
        # 2. Actualizar o crear
        if not v_nombres:
            # Si no hay variantes, el stock es el base (0 para combos/preparados)
            if tipo_prod in ['combo', 'preparado']:
                producto.cantidad_stock = 0.0
            else:
                producto.cantidad_stock = float(request.form.get('cantidad_stock', 0.0) or 0.0)
        else:
            # Si hay variantes, el stock base es 0
            producto.cantidad_stock = 0.0
            for i in range(len(v_nombres)):
                nombre_v = v_nombres[i]
                if not nombre_v: continue
                
                vid = v_ids[i] if i < len(v_ids) else None
                stock_v = float(v_stocks[i] or 0.0)
                costo_v = float(v_costos[i]) if v_costos[i] else producto.precio_costo
                min_v = float(v_mins[i]) if v_mins[i] else producto.precio_minimo
                sug_v = float(v_sugs[i]) if v_sugs[i] else producto.precio_sugerido

                if vid:
                    v_obj = ProductVariant.query.get(int(vid))
                    if v_obj:
                        v_obj.nombre_variante = nombre_v
                        v_obj.cantidad_stock = stock_v
                        v_obj.precio_costo = costo_v
                        v_obj.precio_minimo = min_v
                        v_obj.precio_sugerido = sug_v
                else:
                    nueva_v = ProductVariant(
                        product_id=producto.id,
                        nombre_variante=nombre_v,
                        cantidad_stock=stock_v,
                        precio_costo=costo_v,
                        precio_minimo=min_v,
                        precio_sugerido=sug_v
                    )
                    db.session.add(nueva_v)

        try:
            db.session.commit()
            
            # Sincronización de Recetas / Composición de Combos
            Receta.query.filter_by(producto_final_id=producto.id).delete()
            
            if tipo_prod in ['combo', 'preparado', 'producto_final']:
                r_insumos = request.form.getlist('receta_insumo_id[]')
                r_cants = request.form.getlist('receta_cantidad[]')
                for i in range(len(r_insumos)):
                    if r_insumos[i]:
                        receta = Receta(
                            producto_final_id=producto.id,
                            insumo_id=int(r_insumos[i]),
                            cantidad_requerida=float(r_cants[i] or 1.0)
                        )
                        db.session.add(receta)
            db.session.commit()
                
            # Registrar ajuste de stock si el TOTAL cambió (solo para productos con stock físico directo)
            if tipo_prod not in ['combo', 'preparado']:
                stock_total_nuevo = producto.total_stock
                if stock_total_anterior != stock_total_nuevo:
                    ajuste = StockAdjustment(
                        product_id=producto.id,
                        admin_id=current_user.id,
                        tipo_movimiento='Ajuste en Edición Maestro',
                        stock_anterior=stock_total_anterior,
                        stock_nuevo=stock_total_nuevo
                    )
                    db.session.add(ajuste)
                    db.session.commit()
                
            flash(f'{producto.tipo_label} "{producto.nombre}" actualizado correctamente.', 'success')
            return redirect(url_for('inventory_bp.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error en la base de datos: {str(e)}', 'danger')

    categorias = Categoria.query.order_by(Categoria.id).all()
    insumos = Product.query.filter_by(tipo_producto='insumo').order_by(Product.nombre).all()
    # Para armar combos, excluir el mismo producto si ya existe para evitar autoreferencias
    todos_productos = Product.query.filter(Product.id != producto.id).order_by(Product.nombre).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('inventory/form.html', producto=producto, categorias=categorias, insumos=insumos, todos_productos=todos_productos, proveedores=proveedores)

@inventory_bp.route('/historial-ajustes')
@login_required
@admin_required
def historial_ajustes():
    ajustes = StockAdjustment.query.join(Product).order_by(StockAdjustment.fecha_ajuste.desc()).all()
    return render_template('inventory/historial_ajustes.html', ajustes=ajustes)

@inventory_bp.route('/ver/<int:id>', methods=['GET'])
@login_required
def ver_producto(id):
    producto = Product.query.get_or_404(id)
    ajustes = StockAdjustment.query.filter_by(product_id=id).order_by(StockAdjustment.fecha_ajuste.desc()).all()
    return render_template('inventory/ver.html', producto=producto, ajustes=ajustes)

@inventory_bp.route('/ajuste_stock/<int:id>', methods=['POST'])
@login_required
@admin_required
def ajuste_stock(id):
    producto = Product.query.get_or_404(id)
    cantidad_str = request.form.get('cantidad', '0')
    try:
        cantidad = int(cantidad_str)
    except ValueError:
        cantidad = 0
        
    observacion = request.form.get('observacion', '')
    
    if cantidad > 0:
        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            tipo_movimiento='Ingreso Manual',
            stock_anterior=producto.cantidad_stock,
            stock_nuevo=producto.cantidad_stock + cantidad
        )
        producto.cantidad_stock += cantidad
        if observacion:
            producto.observacion = observacion
        db.session.add(ajuste)
        db.session.commit()
        flash(f'Ingreso registrado: se agregaron {cantidad} unidades.', 'success')
    else:
        flash('La cantidad a ingresar debe ser mayor a 0.', 'warning')
        
    return redirect(url_for('inventory_bp.ver_producto', id=producto.id))

@inventory_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_producto(id):
    producto = Product.query.get_or_404(id)
        
    from models import SaleDetail
    
    # 1. Validación de seguridad en cascada (No eliminar lo que tiene historia financiera/logística)
    if SaleDetail.query.filter_by(product_id=producto.id).first():
        flash('Acción denegada: El producto ya está vinculado a Historial de Ventas. Sugerencia: Ajustar stock a 0.', 'warning')
        return redirect(url_for('inventory_bp.index'))
        
    try:
        # 2. Purgar dependencias suaves (Ajustes de Kardex)
        for ajuste in producto.ajustes_stock:
            db.session.delete(ajuste)
            
        # 3. Eliminar el producto madre (las Variantes se van automáticamente por regla delete-orphan de SQLAlchemy)
        nombre = producto.nombre
        db.session.delete(producto)
        db.session.commit()
        flash(f'Producto "{nombre}" fue borrado permanentemente del inventario.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error bloqueante en la base de datos: {str(e)}', 'danger')
        
    return redirect(url_for('inventory_bp.index'))

@inventory_bp.route('/producto/<int:id>/agregar_variante', methods=['POST'])
@login_required
@admin_required
def agregar_variante(id):
    producto = Product.query.get_or_404(id)
    nombre_variante = request.form.get('nombre_variante')
    cantidad_stock = int(request.form.get('cantidad_stock', 0))
    
    precio_costo_req = request.form.get('precio_costo')
    precio_minimo_req = request.form.get('precio_minimo')
    precio_sugerido_req = request.form.get('precio_sugerido')

    if not nombre_variante:
        flash('El nombre de la variante es obligatorio.', 'danger')
        return redirect(url_for('inventory_bp.index'))

    nueva_variante = ProductVariant(
        product_id=producto.id,
        nombre_variante=nombre_variante,
        cantidad_stock=cantidad_stock,
        precio_costo=float(precio_costo_req) if precio_costo_req else producto.precio_costo,
        precio_minimo=float(precio_minimo_req) if precio_minimo_req else producto.precio_minimo,
        precio_sugerido=float(precio_sugerido_req) if precio_sugerido_req else producto.precio_sugerido
    )
    try:
        db.session.add(nueva_variante)
        # Opcionalmente descontar o trackear en Kardex? La instrucción solo dice: "crea la ruta para añadir la subcategoría"
        db.session.commit()
        flash(f'Variante "{nombre_variante}" agregada con éxito.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al agregar la variante.', 'danger')

    return redirect(url_for('inventory_bp.index'))

@inventory_bp.route('/variante/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_variante(id):
    variante = ProductVariant.query.get_or_404(id)
    
    variante.nombre_variante = request.form.get('nombre_variante')
    variante.cantidad_stock = int(request.form.get('cantidad_stock', variante.cantidad_stock))
    
    precio_costo_req = request.form.get('precio_costo')
    precio_minimo_req = request.form.get('precio_minimo')
    precio_sugerido_req = request.form.get('precio_sugerido')
    
    if precio_costo_req: variante.precio_costo = float(precio_costo_req)
    if precio_minimo_req: variante.precio_minimo = float(precio_minimo_req)
    if precio_sugerido_req: variante.precio_sugerido = float(precio_sugerido_req)
    
    try:
        db.session.commit()
        flash('Variante editada con éxito.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al editar la variante.', 'danger')
        
    return redirect(url_for('inventory_bp.index'))

@inventory_bp.route('/variante/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_variante(id):
    variante = ProductVariant.query.get_or_404(id)
    
    from models import SaleDetail
    # Validar si ya hay ventas facturadas con esta variante para evitar conflictos en el Balance Financiero
    if SaleDetail.query.filter_by(variant_id=variante.id).first():
        flash('Acción denegada: No se puede eliminar una variante que tiene ventas facturadas (por integridad financiera). Sugerencia: Actualiza su stock a 0.', 'warning')
        return redirect(url_for('inventory_bp.index'))
        
    try:
        nombre = variante.nombre_variante
        db.session.delete(variante)
        db.session.commit()
        flash(f'La subcategoría "{nombre}" fue borrada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error grave en servidor al eliminar la variante: {str(e)}', 'danger')
        
    return redirect(url_for('inventory_bp.index'))

@inventory_bp.route('/plantilla-importacion')
@login_required
@admin_required
def descargar_plantilla():
    # Estructura limpia y adaptada para Bar & Comidas
    cols = ['sku', 'nombre', 'categoria', 'tipo_producto', 'cantidad_stock', 'precio_costo', 'precio_sugerido', 'botellaje', 'observacion']
    df = pd.DataFrame(columns=cols)
    
    # Filas de ejemplo representativas para guiar al usuario
    df.loc[0] = ['CERV-COR-355', 'Cerveza Corona Extra 355ml', 'Cervezas', 'producto_simple', 48, 4500, 9500, 0, 'Botella fría']
    df.loc[1] = ['LIC-OLD-750', 'Whisky Old Parr 12 Años 750ml', 'Licores / Botellas', 'producto_simple', 12, 125000, 220000, 15000, 'Botella sellada']
    df.loc[2] = ['COM-ALI-12BBQ', 'Alitas BBQ x 12 Piezas + Papas', 'Comidas / Platos Fuertes / Picadas / Snacks', 'producto_simple', 20, 14000, 32000, 0, 'Alitas con salsa BBQ y papas']
    df.loc[3] = ['BEB-COCA-400', 'Gaseosa Coca-Cola 400ml', 'Bebidas sin Alcohol', 'producto_simple', 36, 2200, 5000, 0, 'Botella PET fría']
    df.loc[4] = ['INS-LIM-KG', 'Limón Tahití (Kg)', 'Insumos de Barra y Cocina', 'insumo', 15, 4000, 0, 0, 'Para coctelería y michelados']
    
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    
    return send_file(output, download_name="plantilla_inventario_harry_beer.xlsx", as_attachment=True)

@inventory_bp.route('/importar', methods=['POST'])
@login_required
@admin_required
def importar_inventario():
    if 'archivo' not in request.files:
        flash('No se seleccionó ningún archivo.', 'danger')
        return redirect(url_for('inventory_bp.index'))
        
    archivo = request.files['archivo']
    if archivo.filename == '':
        flash('Ningún archivo seleccionado.', 'danger')
        return redirect(url_for('inventory_bp.index'))
        
    if not (archivo.filename.endswith('.xlsx') or archivo.filename.endswith('.csv')):
        flash('Formato no válido. Sube un archivo en formato .xlsx o .csv', 'warning')
        return redirect(url_for('inventory_bp.index'))
        
    try:
        if archivo.filename.endswith('.csv'):
            df = pd.read_csv(archivo)
        else:
            df = pd.read_excel(archivo)
            
        required_cols = ['sku', 'nombre', 'cantidad_stock', 'precio_costo', 'precio_sugerido']
        
        # Limpieza y normalización de encabezados
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            flash(f"El archivo fue rechazado. Faltan las siguientes columnas obligatorias: {', '.join(missing)}", 'danger')
            return redirect(url_for('inventory_bp.index'))
            
        # Obtener todas las categorías de la base de datos para mapeo rápido
        categorias_db = Categoria.query.all()
        
        def resolver_categoria(cat_texto):
            if not cat_texto or pd.isna(cat_texto):
                return None
            cat_str = str(cat_texto).strip().lower()
            for c in categorias_db:
                c_nom = c.nombre.lower()
                if cat_str in c_nom or c_nom in cat_str:
                    return c.id
                # Coincidencias por palabras clave
                if 'combo' in cat_str or 'paquete' in cat_str and 'combo' in c_nom: return c.id
                if 'cerveza' in cat_str and 'cerveza' in c_nom: return c.id
                if 'licor' in cat_str and 'licor' in c_nom: return c.id
                if 'coctel' in cat_str or 'cóctel' in cat_str and 'coctel' in c_nom or 'cóctel' in c_nom: return c.id
                if 'comida' in cat_str or 'snack' in cat_str or 'picada' in cat_str and 'comida' in c_nom: return c.id
                if 'sin alcohol' in cat_str or 'bebida' in cat_str and 'sin alcohol' in c_nom: return c.id
                if 'insumo' in cat_str and 'insumo' in c_nom: return c.id
            return None

        creados = 0
        actualizados = 0
        
        for idx, row in df.iterrows():
            sku_raw = str(row['sku']).strip()
            if not sku_raw or sku_raw.lower() == 'nan':
                continue
                
            cant = int(row['cantidad_stock']) if pd.notna(row['cantidad_stock']) else 0
            costo = float(row['precio_costo']) if pd.notna(row['precio_costo']) else 0.0
            sugerido = float(row['precio_sugerido']) if pd.notna(row['precio_sugerido']) else 0.0
            
            # Botellaje / Comisión mesero
            botellaje_val = 0.0
            if 'botellaje' in row and pd.notna(row['botellaje']):
                botellaje_val = float(row['botellaje'])
            elif 'comision_mesero' in row and pd.notna(row['comision_mesero']):
                botellaje_val = float(row['comision_mesero'])
                
            nombre_val = str(row['nombre']).strip()
            
            # Categoría
            cat_val = row.get('categoria')
            cat_id = resolver_categoria(cat_val)
            
            # Tipo de producto
            tipo_raw = str(row.get('tipo_producto', 'producto_simple')).strip().lower() if 'tipo_producto' in row and pd.notna(row['tipo_producto']) else 'producto_simple'
            if tipo_raw in ['insumo', 'materia prima', 'materia_prima']:
                tipo_prod = 'insumo'
            elif tipo_raw in ['preparado', 'coctel', 'cóctel', 'receta']:
                tipo_prod = 'preparado'
            elif tipo_raw in ['combo', 'paquete']:
                tipo_prod = 'combo'
                if not cat_id:
                    cat_id = asegurar_categoria_combos().id
            else:
                tipo_prod = 'producto_simple'

            if tipo_prod == 'combo' and not cat_id:
                cat_id = asegurar_categoria_combos().id

            obs_val = str(row['observacion']).strip() if 'observacion' in row and pd.notna(row['observacion']) and str(row['observacion']).lower() != 'nan' else ''

            prod = Product.query.filter_by(sku=sku_raw).first()
            
            if prod:
                # Actualizar producto existente
                stock_anterior = prod.cantidad_stock
                prod.cantidad_stock += cant
                prod.precio_costo = costo
                prod.precio_sugerido = sugerido
                prod.comision_mesero = botellaje_val
                prod.nombre = nombre_val
                if cat_id: prod.categoria_id = cat_id
                if tipo_prod: prod.tipo_producto = tipo_prod
                if obs_val: prod.observacion = obs_val
                
                if cant > 0:
                    ajuste = StockAdjustment(
                        product_id=prod.id,
                        admin_id=current_user.id,
                        tipo_movimiento='Suma por Carga Masiva (Excel)',
                        stock_anterior=stock_anterior,
                        stock_nuevo=prod.cantidad_stock
                    )
                    db.session.add(ajuste)
                actualizados += 1
            else:
                # Crear nuevo producto
                nuevo_prod = Product(
                    sku=sku_raw,
                    nombre=nombre_val,
                    categoria_id=cat_id,
                    tipo_producto=tipo_prod,
                    cantidad_stock=cant,
                    precio_costo=costo,
                    precio_minimo=0.0,
                    precio_sugerido=sugerido,
                    comision_mesero=botellaje_val,
                    observacion=obs_val
                )
                db.session.add(nuevo_prod)
                db.session.flush()
                
                if cant > 0:
                    ajuste = StockAdjustment(
                        product_id=nuevo_prod.id,
                        admin_id=current_user.id,
                        tipo_movimiento='Creación Inicial (Excel)',
                        stock_anterior=0,
                        stock_nuevo=cant
                    )
                    db.session.add(ajuste)
                creados += 1
                
        db.session.commit()
        flash(f'Carga masiva completada con éxito. Creados: {creados} | Stock y Precios Actualizados: {actualizados}.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error al procesar el archivo: {str(e)}', 'danger')
        
    return redirect(url_for('inventory_bp.index'))

@inventory_bp.route('/api/search')
@login_required
@admin_required
def api_search():
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify([])
    
    from sqlalchemy import or_
    productos = Product.query.filter(
        or_(
            Product.sku.ilike(f'%{query}%'),
            Product.nombre.ilike(f'%{query}%')
        )
    ).limit(10).all()
    
    results = []
    for p in productos:
        results.append({
            'id': p.id,
            'sku': p.sku,
            'nombre': p.nombre,
            'stock': p.total_stock,
            'url': url_for('inventory_bp.ver_producto', id=p.id)
        })
    
    return jsonify(results)
