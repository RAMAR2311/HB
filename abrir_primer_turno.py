import os
import sys
from datetime import datetime
sys.path.append(os.getcwd())

from app import create_app
from models import db, Turno

def abrir_primer_turno():
    app = create_app()
    with app.app_context():
        # Verificar si ya existe un turno abierto
        turno_abierto = Turno.query.filter_by(estado='abierto').first()
        if turno_abierto:
            print("Ya existe un turno abierto. (Turno #{} - Abierto el {})".format(
                turno_abierto.numero_turno, turno_abierto.fecha_apertura
            ))
            return
            
        print("Abriendo el Turno 1...")
        nuevo_turno = Turno(
            numero_turno=1,
            fecha_apertura=datetime.now(),
            estado='abierto',
            base_inicial=0.0
        )
        db.session.add(nuevo_turno)
        db.session.commit()
        print("OK: El Turno 1 ha sido abierto con éxito. ¡Ya puedes empezar a facturar!")

if __name__ == '__main__':
    abrir_primer_turno()
