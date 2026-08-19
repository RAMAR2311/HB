import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, Provider, ProviderInvoice, ProviderPayment, obtener_hora_bogota

proveedores_bp = Blueprint('proveedores_bp', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_admin():
    return current_user.is_authenticated and current_user.rol == 'admin'


@proveedores_bp.route('', methods=['GET'], strict_slashes=False)
@proveedores_bp.route('/', methods=['GET'], strict_slashes=False)
@login_required
def index():
    if not check_admin():
        flash('⛔ Acceso denegado: El módulo de Proveedores requiere privilegios de Administrador.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()

    # Métricas Globales de Deuda y Cuentas por Pagar
    total_facturado_global = sum(p.total_facturado for p in proveedores)
    total_abonos_global = sum(p.total_abonos for p in proveedores)
    total_deuda_global = sum(p.saldo_pendiente for p in proveedores)
    proveedores_con_deuda = len([p for p in proveedores if p.saldo_pendiente > 0])

    return render_template('proveedores/index.html',
                           proveedores=proveedores,
                           total_facturado_global=total_facturado_global,
                           total_abonos_global=total_abonos_global,
                           total_deuda_global=total_deuda_global,
                           proveedores_con_deuda=proveedores_con_deuda)


@proveedores_bp.route('/crear', methods=['POST'])
@login_required
def crear():
    if not check_admin():
        flash('⛔ No tienes permisos para realizar esta acción.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    nombre = request.form.get('nombre', '').strip()
    empresa = request.form.get('empresa', '').strip()
    telefono = request.form.get('telefono', '').strip()

    if not nombre:
        flash('⚠️ El nombre del proveedor es obligatorio.', 'danger')
        return redirect(url_for('proveedores_bp.index'))

    nuevo_prov = Provider(
        nombre=nombre,
        empresa=empresa if empresa else None,
        telefono=telefono if telefono else None,
        fecha_creacion=obtener_hora_bogota()
    )

    try:
        db.session.add(nuevo_prov)
        db.session.commit()
        flash(f'✅ Proveedor "{nombre}" registrado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al crear proveedor: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.index'))


@proveedores_bp.route('/<int:id>', methods=['GET'])
@login_required
def cuenta(id):
    if not check_admin():
        flash('⛔ Acceso denegado.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    provider = Provider.query.get_or_404(id)
    now_date = obtener_hora_bogota().strftime('%Y-%m-%d')
    return render_template('proveedores/cuenta.html', provider=provider, now_date=now_date)


@proveedores_bp.route('/<int:id>/invoice', methods=['POST'])
@login_required
def registrar_factura(id):
    if not check_admin():
        flash('⛔ No tienes permisos para registrar facturas.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    provider = Provider.query.get_or_404(id)

    monto_raw = request.form.get('monto_total', '0').replace('.', '').replace(',', '')
    numero_factura = request.form.get('numero_factura', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    fecha_raw = request.form.get('fecha_factura', '').strip()

    try:
        monto_total = float(monto_raw)
        if monto_total <= 0:
            raise ValueError()
    except ValueError:
        flash('⚠️ El monto de la factura debe ser un valor numérico mayor a cero.', 'danger')
        return redirect(url_for('proveedores_bp.cuenta', id=id))

    # Parsear Fecha
    fecha_factura = obtener_hora_bogota()
    if fecha_raw:
        try:
            fecha_factura = datetime.strptime(fecha_raw, '%Y-%m-%d')
        except ValueError:
            pass

    # Gestión de Archivo Adjunto (Comprobante)
    comprobante_filename = None
    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'providers')
            os.makedirs(upload_dir, exist_ok=True)

            timestamp = int(datetime.now().timestamp())
            filename_clean = secure_filename(file.filename.rsplit('.', 1)[0])[:30]
            comprobante_filename = f"prov_{id}_{timestamp}_{filename_clean}.{ext}"
            file.save(os.path.join(upload_dir, comprobante_filename))

    nueva_factura = ProviderInvoice(
        provider_id=provider.id,
        monto_total=monto_total,
        numero_factura=numero_factura if numero_factura else None,
        descripcion=descripcion if descripcion else None,
        comprobante=comprobante_filename,
        fecha_factura=fecha_factura
    )

    try:
        db.session.add(nueva_factura)
        db.session.commit()
        flash(f'📄 Factura #{numero_factura or nueva_factura.id} por ${monto_total:,.0f} registrada con éxito.'.replace(',', '.'), 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al registrar factura: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/<int:id>/payment', methods=['POST'])
@login_required
def registrar_abono(id):
    if not check_admin():
        flash('⛔ No tienes permisos para registrar abonos.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    provider = Provider.query.get_or_404(id)

    monto_raw = request.form.get('monto_abonado', '0').replace('.', '').replace(',', '')
    observacion = request.form.get('observacion', '').strip()
    fecha_raw = request.form.get('fecha_pago', '').strip()

    try:
        monto_abonado = float(monto_raw)
        if monto_abonado <= 0:
            raise ValueError()
    except ValueError:
        flash('⚠️ El monto del abono debe ser un valor numérico mayor a cero.', 'danger')
        return redirect(url_for('proveedores_bp.cuenta', id=id))

    fecha_pago = obtener_hora_bogota()
    if fecha_raw:
        try:
            fecha_pago = datetime.strptime(fecha_raw, '%Y-%m-%d')
        except ValueError:
            pass

    nuevo_abono = ProviderPayment(
        provider_id=provider.id,
        monto_abonado=monto_abonado,
        observacion=observacion if observacion else None,
        fecha_pago=fecha_pago
    )

    try:
        db.session.add(nuevo_abono)
        db.session.commit()
        flash(f'💵 Abono de ${monto_abonado:,.0f} registrado a la cuenta de "{provider.nombre}".'.replace(',', '.'), 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al registrar abono: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/<int:id>/invoice/<int:inv_id>/editar', methods=['POST'])
@login_required
def editar_factura(id, inv_id):
    if not check_admin():
        flash('⛔ No tienes permisos para editar facturas.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    invoice = ProviderInvoice.query.filter_by(id=inv_id, provider_id=id).first_or_404()

    monto_raw = request.form.get('monto_total', '0').replace('.', '').replace(',', '')
    numero_factura = request.form.get('numero_factura', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    fecha_raw = request.form.get('fecha_factura', '').strip()

    try:
        monto_total = float(monto_raw)
        if monto_total <= 0:
            raise ValueError()
    except ValueError:
        flash('⚠️ El monto de la factura debe ser mayor a cero.', 'danger')
        return redirect(url_for('proveedores_bp.cuenta', id=id))

    if fecha_raw:
        try:
            invoice.fecha_factura = datetime.strptime(fecha_raw, '%Y-%m-%d')
        except ValueError:
            pass

    invoice.monto_total = monto_total
    invoice.numero_factura = numero_factura if numero_factura else None
    invoice.descripcion = descripcion if descripcion else None

    # Si se sube un nuevo comprobante
    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename != '' and allowed_file(file.filename):
            # Eliminar comprobante anterior si existía
            if invoice.comprobante:
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'providers', invoice.comprobante)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

            ext = file.filename.rsplit('.', 1)[1].lower()
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'providers')
            os.makedirs(upload_dir, exist_ok=True)
            timestamp = int(datetime.now().timestamp())
            filename_clean = secure_filename(file.filename.rsplit('.', 1)[0])[:30]
            comprobante_filename = f"prov_{id}_{timestamp}_{filename_clean}.{ext}"
            file.save(os.path.join(upload_dir, comprobante_filename))
            invoice.comprobante = comprobante_filename

    try:
        db.session.commit()
        flash(f'✅ Factura #{invoice.numero_factura or invoice.id} actualizada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al actualizar factura: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/<int:id>/invoice/<int:inv_id>/eliminar', methods=['POST'])
@login_required
def eliminar_factura(id, inv_id):
    if not check_admin():
        flash('⛔ No tienes permisos.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    invoice = ProviderInvoice.query.filter_by(id=inv_id, provider_id=id).first_or_404()

    # Eliminar archivo comprobante físico si existiera
    if invoice.comprobante:
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'providers', invoice.comprobante)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    try:
        db.session.delete(invoice)
        db.session.commit()
        flash('🗑️ Factura eliminada correctamente de la cuenta corriente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al eliminar factura: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/<int:id>/payment/<int:pay_id>/editar', methods=['POST'])
@login_required
def editar_abono(id, pay_id):
    if not check_admin():
        flash('⛔ No tienes permisos para editar abonos.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    payment = ProviderPayment.query.filter_by(id=pay_id, provider_id=id).first_or_404()

    monto_raw = request.form.get('monto_abonado', '0').replace('.', '').replace(',', '')
    observacion = request.form.get('observacion', '').strip()
    fecha_raw = request.form.get('fecha_pago', '').strip()

    try:
        monto_abonado = float(monto_raw)
        if monto_abonado <= 0:
            raise ValueError()
    except ValueError:
        flash('⚠️ El monto del abono debe ser mayor a cero.', 'danger')
        return redirect(url_for('proveedores_bp.cuenta', id=id))

    if fecha_raw:
        try:
            payment.fecha_pago = datetime.strptime(fecha_raw, '%Y-%m-%d')
        except ValueError:
            pass

    payment.monto_abonado = monto_abonado
    payment.observacion = observacion if observacion else None

    try:
        db.session.commit()
        flash(f'✅ Registro de abono actualizado con éxito.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al actualizar abono: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/<int:id>/payment/<int:pay_id>/eliminar', methods=['POST'])
@login_required
def eliminar_abono(id, pay_id):
    if not check_admin():
        flash('⛔ No tienes permisos.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    payment = ProviderPayment.query.filter_by(id=pay_id, provider_id=id).first_or_404()

    try:
        db.session.delete(payment)
        db.session.commit()
        flash('🗑️ Registro de abono eliminado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al eliminar abono: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.cuenta', id=id))


@proveedores_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_proveedor(id):
    if not check_admin():
        flash('⛔ No tienes permisos.', 'danger')
        return redirect(url_for('tables_bp.mapa_mesas'))

    provider = Provider.query.get_or_404(id)
    nombre = provider.nombre

    # Eliminar comprobantes físicos
    for inv in provider.invoices:
        if inv.comprobante:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'providers', inv.comprobante)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass

    try:
        db.session.delete(provider)
        db.session.commit()
        flash(f'🗑️ Proveedor "{nombre}" y todo su historial de cuenta corriente eliminados con éxito.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error al eliminar proveedor: {str(e)}', 'danger')

    return redirect(url_for('proveedores_bp.index'))
