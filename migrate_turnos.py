import sys
import os
from app import app
from models import db, Sale, Expense, ArqueoCaja, Turno, obtener_hora_bogota
from sqlalchemy import func, text
from datetime import datetime

def migrate_turnos():
    with app.app_context():
        # Crear la tabla Turno si no existe
        db.create_all()

        print("=== Migración de Sistema de Turnos ===")
        
        # Añadir columnas turno_id si no existen
        try:
            db.session.execute(text("ALTER TABLE sales ADD COLUMN turno_id INTEGER REFERENCES turnos(id);"))
            db.session.commit()
            print("Columna turno_id añadida a sales.")
        except Exception as e:
            db.session.rollback()
            print("Columna turno_id ya existe en sales.")

        try:
            db.session.execute(text("ALTER TABLE expenses ADD COLUMN turno_id INTEGER REFERENCES turnos(id);"))
            db.session.commit()
            print("Columna turno_id añadida a expenses.")
        except Exception as e:
            db.session.rollback()
            print("Columna turno_id ya existe en expenses.")

        try:
            db.session.execute(text("ALTER TABLE arqueo_caja ADD COLUMN turno_id INTEGER REFERENCES turnos(id);"))
            db.session.commit()
            print("Columna turno_id añadida a arqueo_caja.")
        except Exception as e:
            db.session.rollback()
            print("Columna turno_id ya existe en arqueo_caja.")

        
        # Verificar si ya existen turnos para no duplicar
        if Turno.query.count() > 0:
            print("Ya existen turnos en la base de datos. Saltando migración histórica.")
            return

        # 1. Obtener todas las fechas únicas de ventas
        fechas_ventas = db.session.query(func.date(Sale.fecha_venta)).distinct().all()
        fechas_gastos = db.session.query(func.date(Expense.fecha_gasto)).distinct().all()
        fechas_arqueos = db.session.query(ArqueoCaja.fecha_arqueo).distinct().all()

        todas_fechas = set([f[0] for f in fechas_ventas if f[0]] + 
                           [f[0] for f in fechas_gastos if f[0]] + 
                           [f[0] for f in fechas_arqueos if f[0]])
        fechas_ordenadas = sorted(list(todas_fechas))

        print(f"Encontradas {len(fechas_ordenadas)} fechas con actividad para migrar a Turnos.")

        numero_turno = 1
        for fecha in fechas_ordenadas:
            fecha_str = fecha.strftime('%Y-%m-%d')
            print(f"Procesando fecha: {fecha_str}...")

            dt_apertura = datetime.combine(fecha, datetime.min.time())

            turno = Turno(
                numero_turno=numero_turno,
                fecha_apertura=dt_apertura,
                fecha_cierre=datetime.combine(fecha, datetime.max.time()),
                estado='cerrado',
                base_inicial=0.0
            )
            db.session.add(turno)
            db.session.flush()

            # Actualizar Sales
            ventas_dia = Sale.query.filter(func.date(Sale.fecha_venta) == fecha).all()
            for v in ventas_dia:
                v.turno_id = turno.id
            
            # Actualizar Expenses
            gastos_dia = Expense.query.filter(func.date(Expense.fecha_gasto) == fecha).all()
            for g in gastos_dia:
                g.turno_id = turno.id

            # Actualizar ArqueoCaja
            arqueos_dia = ArqueoCaja.query.filter(ArqueoCaja.fecha_arqueo == fecha).all()
            for a in arqueos_dia:
                a.turno_id = turno.id
                turno.usuario_apertura_id = a.vendedor_id
                turno.usuario_cierre_id = a.vendedor_id
                turno.base_inicial = a.base_inicial
                turno.fecha_cierre = a.fecha_creacion

            numero_turno += 1

        db.session.commit()
        print("Migración histórica completada.")

        # Verificar si hay turno abierto
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        if not turno_abierto:
            print("Abriendo un nuevo turno inicial para operaciones futuras...")
            nuevo_turno = Turno(
                numero_turno=numero_turno,
                fecha_apertura=obtener_hora_bogota(),
                estado='abierto',
                base_inicial=0.0
            )
            
            ultimo_arqueo = ArqueoCaja.query.order_by(ArqueoCaja.fecha_arqueo.desc(), ArqueoCaja.id.desc()).first()
            if ultimo_arqueo:
                nuevo_turno.base_inicial = float(ultimo_arqueo.base_inicial + ultimo_arqueo.total_efectivo_sistema - ultimo_arqueo.gastos_del_dia - ultimo_arqueo.retiro_grueso)

            db.session.add(nuevo_turno)
            db.session.commit()
            print(f"Turno #{nuevo_turno.numero_turno} ABIERTO exitosamente.")

if __name__ == '__main__':
    migrate_turnos()
