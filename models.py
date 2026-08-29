from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import pytz

db = SQLAlchemy()

def obtener_hora_bogota():
    """Inyecta el uso de red horario en Colombia a nivel de sistema operativo."""
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(20)) # Nuevo Campo de Contacto (Nullable por Defecto)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(50), nullable=False, default='cajero')
    
    activo = db.Column(db.Boolean, default=True, nullable=False)
    
    # Restricción de Horarios Laborales (Bogotá, Colombia)
    horario_restringido = db.Column(db.Boolean, default=False, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=True) # ej. 14:00
    hora_fin = db.Column(db.Time, nullable=True)    # ej. 03:00 (soporta turnos trasnochados)
    dias_laborales = db.Column(db.String(100), default='0,1,2,3,4,5,6') # 0=Lun, 1=Mar, ..., 6=Dom
    
    ventas = db.relationship('Sale', foreign_keys='Sale.vendedor_id', backref='vendedor_user', lazy=True)
    ventas_mesero = db.relationship('Sale', foreign_keys='Sale.mesero_id', backref='mesero_user', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='admin', lazy=True)
    arqueos = db.relationship('ArqueoCaja', backref='cajero', lazy=True)

    def __init__(self, nombre=None, email=None, telefono=None, password_hash=None, rol=None, activo=True, horario_restringido=False, hora_inicio=None, hora_fin=None, dias_laborales='0,1,2,3,4,5,6', **kwargs):
        if nombre is not None: kwargs['nombre'] = nombre
        if email is not None: kwargs['email'] = email
        if telefono is not None: kwargs['telefono'] = telefono
        if password_hash is not None: kwargs['password_hash'] = password_hash
        if rol is not None: kwargs['rol'] = rol
        kwargs['activo'] = activo
        kwargs['horario_restringido'] = horario_restringido
        kwargs['hora_inicio'] = hora_inicio
        kwargs['hora_fin'] = hora_fin
        kwargs['dias_laborales'] = dias_laborales
        super(User, self).__init__(**kwargs)

    def verificar_acceso_horario(self):
        """
        Verifica si el usuario tiene permiso para operar en el momento actual (Hora de Bogotá).
        Retorna (True, None) si puede acceder, o (False, 'Motivo') si está fuera de horario.
        """
        if not self.activo:
            return False, "Tu cuenta se encuentra desactivada por la administración."

        if self.rol == 'admin' or not self.horario_restringido:
            return True, None

        if not self.hora_inicio or not self.hora_fin:
            return True, None

        ahora = obtener_hora_bogota()
        dia_semana_actual = str(ahora.weekday()) # 0=Lunes, 6=Domingo
        hora_actual = ahora.time()

        dias_permitidos = [d.strip() for d in (self.dias_laborales or '0,1,2,3,4,5,6').split(',') if d.strip()]
        es_turno_trasnochado = (self.hora_inicio > self.hora_fin)

        if es_turno_trasnochado:
            if hora_actual <= self.hora_fin:
                dia_origen_turno = str((ahora.weekday() - 1) % 7)
                if dia_origen_turno not in dias_permitidos and dia_semana_actual not in dias_permitidos:
                    return False, "Hoy no tienes turno laboral programado."
                if not (hora_actual <= self.hora_fin or hora_actual >= self.hora_inicio):
                    return False, f"Fuera de horario. Tu turno es de {self.hora_inicio.strftime('%I:%M %p')} a {self.hora_fin.strftime('%I:%M %p')}."
            else:
                if dia_semana_actual not in dias_permitidos:
                    return False, "Hoy no tienes turno laboral programado."
                if not (hora_actual >= self.hora_inicio):
                    return False, f"Tu turno comienza a las {self.hora_inicio.strftime('%I:%M %p')}."
        else:
            if dia_semana_actual not in dias_permitidos:
                return False, "Hoy no tienes turno laboral programado."
            if not (self.hora_inicio <= hora_actual <= self.hora_fin):
                return False, f"Fuera de horario. Tu turno es de {self.hora_inicio.strftime('%I:%M %p')} a {self.hora_fin.strftime('%I:%M %p')}."

        return True, None

class Categoria(db.Model):
    __tablename__ = 'categorias'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    
    productos = db.relationship('Product', backref='categoria', lazy=True)

    def __init__(self, **kwargs):
        super(Categoria, self).__init__(**kwargs)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    tipo_producto = db.Column(db.String(50), nullable=False, server_default='producto_final') # 'insumo', 'producto_final', 'adicional'
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    cantidad_stock = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    precio_costo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00) # Costo de Compra / Insumo
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=False)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=False)
    comision_mesero = db.Column(db.Numeric(10, 2), nullable=False, default=0.0) # Botellaje / Comisión para el mesero
    imagen = db.Column(db.String(255), nullable=True) # Nombre de la foto subida
    observacion = db.Column(db.Text, nullable=True) # Nota descriptiva
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)
    
    detalles_venta = db.relationship('SaleDetail', backref='producto', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='producto_rel', lazy=True, cascade="all, delete-orphan")
    variantes = db.relationship('ProductVariant', backref='producto', lazy=True, cascade="all, delete-orphan")
    recetas = db.relationship('Receta', foreign_keys='Receta.producto_final_id', backref='producto_final', lazy=True, cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super(Product, self).__init__(**kwargs)

    @property
    def total_stock(self):
        if self.variantes:
            return sum(float(v.cantidad_stock or 0) for v in self.variantes)
        return float(self.cantidad_stock or 0)

    @property
    def rango_precios(self):
        if not self.variantes:
            return None
        precios = [v.precio_sugerido for v in self.variantes if v.precio_sugerido is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_costos(self):
        if not self.variantes:
            return None
        precios = [v.precio_costo for v in self.variantes if v.precio_costo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_minimos(self):
        if not self.variantes:
            return None
        precios = [v.precio_minimo for v in self.variantes if v.precio_minimo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def es_combo(self):
        return self.tipo_producto == 'combo'

    @property
    def es_insumo(self):
        return self.tipo_producto == 'insumo'

    @property
    def es_preparado(self):
        return self.tipo_producto == 'preparado'

    @property
    def es_producto_simple(self):
        return self.tipo_producto in ['producto_simple', 'producto_final']

    @property
    def tipo_label(self):
        if self.tipo_producto == 'insumo':
            return 'Insumo'
        elif self.tipo_producto == 'combo':
            return 'Combo'
        elif self.tipo_producto == 'preparado':
            return 'Cóctel / Plato'
        return 'Producto Directo'

    @property
    def unidad_medida_display(self):
        """Retorna la unidad de medida según el tipo de producto o insumo (oz para licores de coctelería/barra)."""
        if self.es_insumo:
            nom_lower = (self.nombre or '').lower()
            if any(k in nom_lower for k in ['(kg)', ' kg', 'kilo']):
                return 'kg'
            if any(k in nom_lower for k in ['(manojo)', 'manojo', 'ramita']):
                return 'manojo'
            if any(k in nom_lower for k in ['(und)', ' und', 'unidad']):
                return 'uds'
            if any(k in nom_lower for k in ['shot', 'shots', 'onza', 'oz', 'ron', 'vodka', 'tequila', 'gin', 'ginebra', 'whisky', 'licor', 'trago', 'sirope', 'jarabe', 'triple sec', 'granel', 'aguardiente', 'brandy']):
                return 'shots'
            if any(k in nom_lower for k in ['porcion', 'porción', 'paquete']):
                return 'porc'
        return 'uds'

    @property
    def stock_disponible_calculado(self):
        """Calcula matemáticamente cuántas unidades se pueden armar de un combo o receta según el stock de sus componentes."""
        if self.es_combo or self.es_preparado:
            if not self.recetas or len(self.recetas) == 0:
                return 0
            max_posibles = []
            for r in self.recetas:
                if not r.insumo or float(r.cantidad_requerida or 0) <= 0:
                    continue
                stock_insumo = float(r.insumo.total_stock)
                cant_req = float(r.cantidad_requerida)
                posibles = int(stock_insumo // cant_req)
                max_posibles.append(posibles)
            return min(max_posibles) if max_posibles else 0
        return self.total_stock

    @property
    def es_bajo_stock(self):
        """Determina si un producto, insumo, cóctel o combo tiene existencias bajas o críticas."""
        if self.es_combo or self.es_preparado:
            return self.stock_disponible_calculado <= 5
        if self.variantes:
            return any(float(v.cantidad_stock or 0) <= 5 for v in self.variantes) or self.total_stock <= 10.0
        if self.es_insumo and self.unidad_medida_display in ['shots', 'oz']:
            # Para licores en shots, menos de 16 shots (1 botella estándar de 750ml) es alerta
            return float(self.cantidad_stock or 0) <= 16.0
        return float(self.cantidad_stock or 0) <= 10.0

    @property
    def tiene_botellaje(self):
        return bool(self.comision_mesero and float(self.comision_mesero) > 0)

class ProductVariant(db.Model):
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    nombre_variante = db.Column(db.String(100), nullable=False)
    cantidad_stock = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    # Nuevos precios específicos para variantes
    precio_costo = db.Column(db.Numeric(10, 2), nullable=True) 
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=True)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=True)

    def __init__(self, **kwargs):
        super(ProductVariant, self).__init__(**kwargs)

class Receta(db.Model):
    """Modelo para vincular un producto final (ej. Hot Dog) con sus insumos (Pan, Salchicha)."""
    __tablename__ = 'recetas'
    
    id = db.Column(db.Integer, primary_key=True)
    producto_final_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    cantidad_requerida = db.Column(db.Numeric(10, 2), nullable=False, default=1.0) # Cuántas unidades del insumo requiere
    
    insumo = db.relationship('Product', foreign_keys=[insumo_id])

    def __init__(self, **kwargs):
        super(Receta, self).__init__(**kwargs)

class Mesa(db.Model):
    """Modelo para gestionar el control de mesas y consumo en barra del bar."""
    __tablename__ = 'mesas'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)  # Ej: "Mesa 1", "Mesa 2", "Barra", "Terraza 1"
    capacidad = db.Column(db.Integer, nullable=False, default=4)
    estado = db.Column(db.String(20), nullable=False, default='libre')  # 'libre', 'ocupada', 'unida'
    mesa_padre_id = db.Column(db.Integer, db.ForeignKey('mesas.id'), nullable=True)  # Para mesas fusionadas/unidas
    
    ventas = db.relationship('Sale', backref='mesa', lazy=True)
    mesas_hijas = db.relationship('Mesa', backref=db.backref('mesa_padre', remote_side=[id]), lazy=True)

    def __init__(self, **kwargs):
        super(Mesa, self).__init__(**kwargs)

class Sale(db.Model):
    __tablename__ = 'sales'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mesero_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Mesero que atendió la mesa
    table_id = db.Column(db.Integer, db.ForeignKey('mesas.id'), nullable=True)  # Mesa asignada
    
    fecha_venta = db.Column(db.DateTime, default=obtener_hora_bogota)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    porcentaje_propina = db.Column(db.Numeric(5, 2), nullable=False, default=0.0)  # Ej: 10.00 %
    monto_propina = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    monto_descuento = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    monto_cortesia = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    
    aplica_recargo_datafono = db.Column(db.Boolean, nullable=False, default=False)  # 5% recargo datáfono
    monto_recargo_datafono = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    
    monto_total = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    numero_turno = db.Column(db.Integer, nullable=True)  # Turno del día para comanda
    estado_cuenta = db.Column(db.String(50), nullable=False, default='pagada')  # 'abierta', 'pagada', 'cancelada'
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=True)
    
    detalles = db.relationship('SaleDetail', backref='venta', lazy=True, cascade="all, delete-orphan")
    pagos = db.relationship('SalePayment', backref='venta', lazy=True, cascade="all, delete-orphan")
    cliente = db.relationship('SaleClient', backref='venta', lazy=True, cascade="all, delete-orphan", uselist=False)

    mesero = db.relationship('User', foreign_keys=[mesero_id], overlaps="mesero_user,ventas_mesero")
    vendedor = db.relationship('User', foreign_keys=[vendedor_id], overlaps="vendedor_user,ventas")

    def __init__(self, **kwargs):
        super(Sale, self).__init__(**kwargs)

    @property
    def total_botellaje(self):
        """Calcula el total de botellaje ganado por el mesero en esta venta."""
        return sum(d.botellaje_unitario * d.cantidad_vendida for d in self.detalles)

    @property
    def metodo_pago_display(self):
        """Retorna un resumen legible del método de pago.
        Si es pago único, retorna el nombre del método.
        Si es mixto, retorna 'Pago Mixto' con desglose."""
        if not self.pagos:
            return self.metodo_pago.capitalize() if self.metodo_pago else 'Efectivo'
        if len(self.pagos) == 1:
            return self.pagos[0].metodo_pago.capitalize()
        return 'Pago Mixto'

class SalePayment(db.Model):
    """Modelo para soportar pagos mixtos/parciales por venta.
    Permite registrar múltiples métodos de pago en una sola venta.
    Ej: $50.000 en efectivo + $30.000 por Nequi = $80.000 total."""
    __tablename__ = 'sale_payments'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False)  # efectivo, nequi, bancolombia, daviplata, llave, datafono
    monto = db.Column(db.Numeric(10, 2), nullable=False)

    def __init__(self, **kwargs):
        super(SalePayment, self).__init__(**kwargs)

class SaleClient(db.Model):
    """Modelo para almacenar los datos del cliente."""
    __tablename__ = 'sale_clients'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, unique=True)
    nombre = db.Column(db.String(150), nullable=False)
    documento = db.Column(db.String(50), nullable=False, index=True)
    telefono = db.Column(db.String(50), nullable=False)
    
    def __init__(self, **kwargs):
        super(SaleClient, self).__init__(**kwargs)

class SaleDetail(db.Model):
    __tablename__ = 'sale_details'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad_vendida = db.Column(db.Integer, nullable=False)
    precio_venta_final = db.Column(db.Numeric(10, 2), nullable=False)
    es_cortesia = db.Column(db.Boolean, nullable=False, default=False)
    cortesia_para = db.Column(db.String(150), nullable=True) # A quién se le otorgó la cortesía (ej. "Dueño", "DJ Andrés")
    botellaje_unitario = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    
    # Notas del cliente para modificaciones (ej. "Sin cebolla")
    notas = db.Column(db.String(255), nullable=True)

    variante = db.relationship('ProductVariant', backref='ventas_rel', lazy=True)

    def __init__(self, **kwargs):
        super(SaleDetail, self).__init__(**kwargs)

class BeneficiarioCortesia(db.Model):
    """Catálogo de personas autorizadas y registradas para recibir cortesías/regalos en el bar."""
    __tablename__ = 'beneficiarios_cortesia'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)
    rol_cargo = db.Column(db.String(100), nullable=True) # Ej: Dueño, DJ, Barman, Músico, VIP, etc.
    activo = db.Column(db.Boolean, nullable=False, default=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(BeneficiarioCortesia, self).__init__(**kwargs)

class StockAdjustment(db.Model):
    __tablename__ = 'stock_adjustments'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tipo_movimiento = db.Column(db.String(100), nullable=True) # Ej: Creación Inicial, Ajuste Manual
    stock_anterior = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    stock_nuevo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    fecha_ajuste = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(StockAdjustment, self).__init__(**kwargs)

class ArqueoCaja(db.Model):
    __tablename__ = 'arqueo_caja'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=True)
    fecha_arqueo = db.Column(db.Date, nullable=False)
    base_inicial = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    gastos_del_dia = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    retiro_grueso = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    efectivo_fisico_contado = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    digital_contado = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    diferencia = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_propinas = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_botellaje = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_descuentos = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    observaciones_gastos = db.Column(db.String(255), nullable=True)
    total_efectivo_sistema = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_transferencia_sistema = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(ArqueoCaja, self).__init__(**kwargs)

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=True)
    tipo_gasto = db.Column(db.String(50), nullable=False) # 'Gasto Diario' o 'Costo Indirecto'
    categoria = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    fecha_gasto = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='gastos', lazy=True)

    def __init__(self, **kwargs):
        super(Expense, self).__init__(**kwargs)


class Turno(db.Model):
    __tablename__ = 'turnos'
    
    id = db.Column(db.Integer, primary_key=True)
    numero_turno = db.Column(db.Integer, nullable=False)
    fecha_apertura = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    usuario_apertura_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    usuario_cierre_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    estado = db.Column(db.String(20), nullable=False, default='abierto') # 'abierto', 'cerrado'
    base_inicial = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    
    usuario_apertura = db.relationship('User', foreign_keys=[usuario_apertura_id], lazy=True)
    usuario_cierre = db.relationship('User', foreign_keys=[usuario_cierre_id], lazy=True)
    
    ventas = db.relationship('Sale', backref='turno_rel', lazy=True)
    gastos = db.relationship('Expense', backref='turno_rel', lazy=True)
    arqueos = db.relationship('ArqueoCaja', backref='turno_rel', lazy=True)

    def __init__(self, **kwargs):
        super(Turno, self).__init__(**kwargs)


# =========================================================================
# MÓDULO DE PROVEEDORES Y CUENTAS POR PAGAR (CUENTA CORRIENTE)
# =========================================================================

class Provider(db.Model):
    """Representa a un proveedor de insumos, licores, alimentos o servicios."""
    __tablename__ = 'providers'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    empresa = db.Column(db.String(150), nullable=True)
    telefono = db.Column(db.String(50), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    invoices = db.relationship('ProviderInvoice', backref='provider', lazy=True, cascade='all, delete-orphan', order_by='desc(ProviderInvoice.fecha_factura)')
    payments = db.relationship('ProviderPayment', backref='provider', lazy=True, cascade='all, delete-orphan', order_by='desc(ProviderPayment.fecha_pago)')

    def __init__(self, **kwargs):
        super(Provider, self).__init__(**kwargs)

    @property
    def total_facturado(self):
        return sum(float(inv.monto_total or 0) for inv in self.invoices)

    @property
    def total_abonos(self):
        return sum(float(pay.monto_abonado or 0) for pay in self.payments)

    @property
    def saldo_pendiente(self):
        return self.total_facturado - self.total_abonos


class ProviderInvoice(db.Model):
    """Factura o cuenta de cobro emitida por un proveedor."""
    __tablename__ = 'provider_invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id', ondelete='CASCADE'), nullable=False)
    monto_total = db.Column(db.Numeric(12, 2), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(255), nullable=True)
    comprobante = db.Column(db.String(255), nullable=True)
    fecha_factura = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(ProviderInvoice, self).__init__(**kwargs)


class ProviderPayment(db.Model):
    """Abono o pago realizado a un proveedor para disminuir la deuda acumulada."""
    __tablename__ = 'provider_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id', ondelete='CASCADE'), nullable=False)
    monto_abonado = db.Column(db.Numeric(12, 2), nullable=False)
    observacion = db.Column(db.String(255), nullable=True)
    fecha_pago = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(ProviderPayment, self).__init__(**kwargs)
