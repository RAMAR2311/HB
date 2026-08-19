import os
import sys
sys.path.append(os.getcwd())

from app import create_app
from models import db, Product, Categoria, Receta, StockAdjustment, User
from werkzeug.security import generate_password_hash

def seed_bar_data():
    app = create_app()
    with app.app_context():
        print("[1/5] Limpiando datos existentes...")
        db.drop_all()
        db.create_all()

        print("[2/5] Creando Administradores...")
        admin1 = User(
            nombre='Administrador Harry Beer',
            email='admin@harrybeer.com',
            telefono='3001234567',
            password_hash=generate_password_hash('Admin123'),
            rol='admin'
        )
        admin2 = User(
            nombre='Admin General',
            email='admin@elgoldy.com',
            telefono='3007654321',
            password_hash=generate_password_hash('Admin123'),
            rol='admin'
        )
        cajero = User(
            nombre='Cajero Principal Barra',
            email='cajero@harrybeer.com',
            telefono='3009998877',
            password_hash=generate_password_hash('Cajero123'),
            rol='cajero'
        )
        db.session.add_all([admin1, admin2, cajero])
        db.session.commit()

        print("[3/5] Creando Categorias Oficiales...")
        cat_cervezas = Categoria(nombre="Cervezas (Nacionales, Artesanales, Importadas, Barril)")
        cat_licores = Categoria(nombre="Licores / Botellas (Whisky, Ron, Vodka, Tequila, Aguardiente, Ginebra)")
        cat_cocteles = Categoria(nombre="Cócteles y Tragos")
        cat_comidas = Categoria(nombre="Comidas / Platos Fuertes / Picadas / Snacks")
        cat_bebidas = Categoria(nombre="Bebidas sin Alcohol")
        cat_combos = Categoria(nombre="Combos")
        cat_insumos = Categoria(nombre="Insumos de Barra y Cocina")

        db.session.add_all([cat_cervezas, cat_licores, cat_cocteles, cat_comidas, cat_bebidas, cat_combos, cat_insumos])
        db.session.commit()

        print("[4/5] Creando Productos de Ejemplo por Categoria...")

        # ---------------- 1. INSUMOS DE BARRA Y COCINA ----------------
        # Licores en Onzas (1 oz = 30ml | 1 Botella 750ml = 25 oz | 1 Litro = 33.33 oz)
        insumo_ron = Product(
            sku="INS-RON-01", nombre="Ron para Coctelería y Barra (Onzas - 1oz = 30ml)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=250.0, precio_costo=1400.0, precio_minimo=0, precio_sugerido=0,
            observacion="Base para Cuba Libre y Mojitos (10 botellas 750ml = 250 oz | 1 oz = 30ml)"
        )
        insumo_menta = Product(
            sku="INS-MENT-01", nombre="Hierbabuena / Menta Fresca (Manojo)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=25, precio_costo=2000, precio_minimo=0, precio_sugerido=0,
            observacion="Menta fresca para cocteleria"
        )
        insumo_limon = Product(
            sku="INS-LIM-01", nombre="Limón Tahití (Kg)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=15, precio_costo=4000, precio_minimo=0, precio_sugerido=0,
            observacion="Para rodajas de cócteles y michelados"
        )
        insumo_ginebra = Product(
            sku="INS-GIN-01", nombre="Ginebra para Coctelería (Onzas - 1oz = 30ml)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=200.0, precio_costo=2200.0, precio_minimo=0, precio_sugerido=0,
            observacion="Base para Gin Tonic (8 botellas 750ml = 200 oz | 1 oz = 30ml)"
        )
        insumo_tequila = Product(
            sku="INS-TEQ-01", nombre="Tequila para Coctelería (Onzas - 1oz = 30ml)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=150.0, precio_costo=2400.0, precio_minimo=0, precio_sugerido=0,
            observacion="Base para Margaritas y Shots (6 botellas 750ml = 150 oz | 1 oz = 30ml)"
        )
        insumo_carne = Product(
            sku="INS-CARN-01", nombre="Carne Angus Hamburguesa 150g (Und)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=40, precio_costo=6500, precio_minimo=0, precio_sugerido=0,
            observacion="Medallones de carne seleccionada"
        )
        insumo_pan = Product(
            sku="INS-PAN-01", nombre="Pan Brioche Hamburguesa (Und)", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=50, precio_costo=1800, precio_minimo=0, precio_sugerido=0,
            observacion="Pan fresco sellado"
        )
        insumo_papas = Product(
            sku="INS-PAP-01", nombre="Porción Papas a la Francesa 200g", tipo_producto="insumo",
            categoria_id=cat_insumos.id, cantidad_stock=35, precio_costo=2500, precio_minimo=0, precio_sugerido=0,
            observacion="Papas corte fino pre-cocidas"
        )

        db.session.add_all([insumo_ron, insumo_menta, insumo_limon, insumo_ginebra, insumo_tequila, insumo_carne, insumo_pan, insumo_papas])
        db.session.commit()

        # ---------------- 2. CERVEZAS ----------------
        cerv_corona = Product(
            sku="CERV-COR-355", nombre="Cerveza Corona Extra 355ml", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=48, precio_costo=4500, precio_minimo=7000, precio_sugerido=9500,
            observacion="Botella retornable / no retornable fría"
        )
        cerv_club = Product(
            sku="CERV-CLUB-DOR", nombre="Cerveza Club Colombia Dorada 330ml", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=72, precio_costo=3400, precio_minimo=5500, precio_sugerido=7500,
            observacion="Cerveza rubia premium nacional"
        )
        cerv_stella = Product(
            sku="CERV-STEL-330", nombre="Cerveza Stella Artois 330ml", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=36, precio_costo=5000, precio_minimo=8000, precio_sugerido=11000,
            observacion="Importada Bélgica"
        )
        cerv_ipa = Product(
            sku="CERV-IPA-PINT", nombre="Pinta Artesanal IPA Harry Beer 500ml (Barril)", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=28, precio_costo=6000, precio_minimo=10000, precio_sugerido=14000,
            observacion="Cerveza tirada de grifo / chopp artesanal"
        )
        cerv_heineken = Product(
            sku="CERV-HEIN-LATA", nombre="Cerveza Heineken 330ml (Lata)", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=24, precio_costo=3800, precio_minimo=6000, precio_sugerido=8500,
            observacion="Lata fría"
        )
        cerv_poker = Product(
            sku="CERV-POK-330", nombre="Cerveza Poker 330ml", tipo_producto="producto_simple",
            categoria_id=cat_cervezas.id, cantidad_stock=2, precio_costo=2800, precio_minimo=4500, precio_sugerido=6000,
            observacion="Nacional tradicional (Stock bajo de prueba)"
        )

        db.session.add_all([cerv_corona, cerv_club, cerv_stella, cerv_ipa, cerv_heineken, cerv_poker])
        db.session.commit()

        # ---------------- 3. LICORES / BOTELLAS ----------------
        licor_oldparr = Product(
            sku="LIC-WHIS-OP12", nombre="Whisky Old Parr 12 Años 750ml", tipo_producto="producto_simple",
            categoria_id=cat_licores.id, cantidad_stock=8, precio_costo=125000, precio_minimo=180000, precio_sugerido=220000,
            comision_mesero=15000,
            observacion="Botella sellada con estampilla"
        )
        licor_ron_med = Product(
            sku="LIC-RON-MED8", nombre="Ron Medellín Añejo 8 Años 750ml", tipo_producto="producto_simple",
            categoria_id=cat_licores.id, cantidad_stock=14, precio_costo=55000, precio_minimo=85000, precio_sugerido=110000,
            comision_mesero=10000,
            observacion="Botella tradicional de Ron de Antioquia"
        )
        licor_aguardiente = Product(
            sku="LIC-AGU-AZUL", nombre="Aguardiente Antioqueño Azul 750ml (Sin Azúcar)", tipo_producto="producto_simple",
            categoria_id=cat_licores.id, cantidad_stock=18, precio_costo=42000, precio_minimo=65000, precio_sugerido=85000,
            comision_mesero=8000,
            observacion="Tapa azul tradicional"
        )
        licor_tequila = Product(
            sku="LIC-TEQ-JC", nombre="Tequila José Cuervo Especial 750ml", tipo_producto="producto_simple",
            categoria_id=cat_licores.id, cantidad_stock=6, precio_costo=75000, precio_minimo=120000, precio_sugerido=150000,
            comision_mesero=10000,
            observacion="Tequila reposado mexicano"
        )
        licor_tanqueray = Product(
            sku="LIC-GIN-TANQ", nombre="Ginebra Tanqueray London Dry 750ml", tipo_producto="producto_simple",
            categoria_id=cat_licores.id, cantidad_stock=5, precio_costo=95000, precio_minimo=140000, precio_sugerido=180000,
            comision_mesero=12000,
            observacion="Ginebra premium para cocteles"
        )

        db.session.add_all([licor_oldparr, licor_ron_med, licor_aguardiente, licor_tequila, licor_tanqueray])
        db.session.commit()

        # ---------------- 4. BEBIDAS SIN ALCOHOL ----------------
        beb_coca = Product(
            sku="BEB-COCA-400", nombre="Gaseosa Coca-Cola 400ml", tipo_producto="producto_simple",
            categoria_id=cat_bebidas.id, cantidad_stock=40, precio_costo=2200, precio_minimo=3500, precio_sugerido=5000,
            observacion="Botella PET fría"
        )
        beb_agua = Product(
            sku="BEB-AGUA-GAS", nombre="Agua Mineral con Gas Manantial 300ml", tipo_producto="producto_simple",
            categoria_id=cat_bebidas.id, cantidad_stock=30, precio_costo=1800, precio_minimo=3000, precio_sugerido=4500,
            observacion="Botella de vidrio"
        )
        beb_redbull = Product(
            sku="BEB-REDB-250", nombre="Red Bull Energy Drink 250ml", tipo_producto="producto_simple",
            categoria_id=cat_bebidas.id, cantidad_stock=24, precio_costo=6500, precio_minimo=9000, precio_sugerido=12000,
            observacion="Lata energizante"
        )
        beb_tonica = Product(
            sku="BEB-TONIC-300", nombre="Agua Tónica Schweppes 300ml", tipo_producto="producto_simple",
            categoria_id=cat_bebidas.id, cantidad_stock=20, precio_costo=2300, precio_minimo=3500, precio_sugerido=5500,
            observacion="Mezclador para Ginebra"
        )

        db.session.add_all([beb_coca, beb_agua, beb_redbull, beb_tonica])
        db.session.commit()

        # ---------------- 5. COMIDAS / PLATOS FUERTES / PICADAS / SNACKS ----------------
        com_picada = Product(
            sku="COM-PIC-ESP", nombre="Picada Harry Beer Especial (3-4 Personas)", tipo_producto="producto_simple",
            categoria_id=cat_comidas.id, cantidad_stock=15, precio_costo=22000, precio_minimo=35000, precio_sugerido=48000,
            observacion="Carne de res, pechuga, chorizo artesanal, queso, papas criollas y salsas de la casa"
        )
        com_burger = Product(
            sku="COM-BURG-ART", nombre="Hamburguesa Doble Angus Artesanal", tipo_producto="preparado",
            categoria_id=cat_comidas.id, cantidad_stock=0, precio_costo=0, precio_minimo=18000, precio_sugerido=26000,
            observacion="300g carne Angus, queso cheddar, tocineta y pan brioche"
        )
        com_alitas = Product(
            sku="COM-ALI-12BBQ", nombre="Alitas BBQ x 12 Piezas + Papas", tipo_producto="producto_simple",
            categoria_id=cat_comidas.id, cantidad_stock=20, precio_costo=14000, precio_minimo=22000, precio_sugerido=32000,
            observacion="Alitas crujientes bañadas en salsa BBQ ahumada con papas"
        )
        com_nachos = Product(
            sku="COM-NACH-CHEE", nombre="Nachos Tex-Mex con Queso y Guacamole", tipo_producto="producto_simple",
            categoria_id=cat_comidas.id, cantidad_stock=18, precio_costo=9000, precio_minimo=15000, precio_sugerido=22000,
            observacion="Totopos crocantes con queso cheddar fundido, guacamole y pico de gallo"
        )

        db.session.add_all([com_picada, com_burger, com_alitas, com_nachos])
        db.session.commit()

        # Vincular receta a la Hamburguesa (descuenta 2 carnes, 1 pan, 1 porcion papas)
        db.session.add(Receta(producto_final_id=com_burger.id, insumo_id=insumo_carne.id, cantidad_requerida=2))
        db.session.add(Receta(producto_final_id=com_burger.id, insumo_id=insumo_pan.id, cantidad_requerida=1))
        db.session.add(Receta(producto_final_id=com_burger.id, insumo_id=insumo_papas.id, cantidad_requerida=1))
        db.session.commit()

        # ---------------- 6. CÓCTELES Y TRAGOS (PREPARADOS) ----------------
        coctel_mojito = Product(
            sku="COC-MOJ-CLAS", nombre="Mojito Cubano Clásico", tipo_producto="preparado",
            categoria_id=cat_cocteles.id, cantidad_stock=0, precio_costo=0, precio_minimo=14000, precio_sugerido=22000,
            observacion="Ron blanco, zumo de limón, azúcar, hierbabuena fresca y soda"
        )
        coctel_gintonic = Product(
            sku="COC-GIN-TONIC", nombre="Gin Tonic Tanqueray Premium", tipo_producto="preparado",
            categoria_id=cat_cocteles.id, cantidad_stock=0, precio_costo=0, precio_minimo=18000, precio_sugerido=28000,
            observacion="Ginebra Tanqueray, tónica Schweppes y rodajas de limón"
        )
        coctel_margarita = Product(
            sku="COC-MARG-CLAS", nombre="Margarita Tradicional en Copa", tipo_producto="preparado",
            categoria_id=cat_cocteles.id, cantidad_stock=0, precio_costo=0, precio_minimo=16000, precio_sugerido=25000,
            observacion="Tequila, triple sec, zumo de limón y borde escarchado con sal"
        )

        db.session.add_all([coctel_mojito, coctel_gintonic, coctel_margarita])
        db.session.commit()

        # Vincular recetas de cocteles (Cantidades en Onzas donde 1 oz = 30ml)
        db.session.add(Receta(producto_final_id=coctel_mojito.id, insumo_id=insumo_ron.id, cantidad_requerida=2.0)) # 2 oz (60ml) ron
        db.session.add(Receta(producto_final_id=coctel_mojito.id, insumo_id=insumo_menta.id, cantidad_requerida=0.2)) # 0.2 manojo
        db.session.add(Receta(producto_final_id=coctel_mojito.id, insumo_id=insumo_limon.id, cantidad_requerida=0.1)) # 100g limon

        db.session.add(Receta(producto_final_id=coctel_gintonic.id, insumo_id=insumo_ginebra.id, cantidad_requerida=2.0)) # 2 oz (60ml) gin
        db.session.add(Receta(producto_final_id=coctel_gintonic.id, insumo_id=beb_tonica.id, cantidad_requerida=1.0)) # 1 tonica
        db.session.add(Receta(producto_final_id=coctel_gintonic.id, insumo_id=insumo_limon.id, cantidad_requerida=0.05))

        db.session.add(Receta(producto_final_id=coctel_margarita.id, insumo_id=insumo_tequila.id, cantidad_requerida=2.0)) # 2 oz (60ml) tequila
        db.session.add(Receta(producto_final_id=coctel_margarita.id, insumo_id=insumo_limon.id, cantidad_requerida=0.1))
        db.session.commit()

        # ---------------- 7. COMBOS Y PAQUETES PROMOCIONALES ----------------
        print("[5/5] Creando Combos Promocionales con Múltiples Productos...")

        # Combo 1: Combo Rumbero Corona (4 Coronas + 1 Picada Especial)
        combo1 = Product(
            sku="CMB-RUMB-COR", nombre="Combo Rumbero Corona (4 Coronas + 1 Picada)", tipo_producto="combo",
            categoria_id=cat_combos.id, cantidad_stock=0, precio_costo=0, precio_minimo=60000, precio_sugerido=75000,
            observacion="Ahorro especial: 4 Cervezas Corona 355ml + 1 Picada Harry Beer Especial"
        )
        db.session.add(combo1)
        db.session.flush()
        db.session.add(Receta(producto_final_id=combo1.id, insumo_id=cerv_corona.id, cantidad_requerida=4))
        db.session.add(Receta(producto_final_id=combo1.id, insumo_id=com_picada.id, cantidad_requerida=1))

        # Combo 2: Combo Parrandero Ron Medellín (1 Botella Ron + 4 Gaseosas + 1 Nachos)
        combo2 = Product(
            sku="CMB-PARR-MED", nombre="Combo Parrandero (1 Botella Ron 8 Años + 4 Coca-Colas + Nachos)", tipo_producto="combo",
            categoria_id=cat_combos.id, cantidad_stock=0, precio_costo=0, precio_minimo=110000, precio_sugerido=145000,
            comision_mesero=12000,
            observacion="Botella Ron Medellín 8 Años 750ml + 4 Coca-Colas 400ml + 1 Nachos Tex-Mex"
        )
        db.session.add(combo2)
        db.session.flush()
        db.session.add(Receta(producto_final_id=combo2.id, insumo_id=licor_ron_med.id, cantidad_requerida=1))
        db.session.add(Receta(producto_final_id=combo2.id, insumo_id=beb_coca.id, cantidad_requerida=4))
        db.session.add(Receta(producto_final_id=combo2.id, insumo_id=com_nachos.id, cantidad_requerida=1))

        # Combo 3: Bucket Club Colombia + Alitas (6 Cervezas Club + 1 Alitas x 12)
        combo3 = Product(
            sku="CMB-BUCK-CLUB", nombre="Bucket Amigos (6 Club Colombia + Alitas BBQ x 12)", tipo_producto="combo",
            categoria_id=cat_combos.id, cantidad_stock=0, precio_costo=0, precio_minimo=55000, precio_sugerido=70000,
            observacion="Balde con 6 Club Colombia Dorada bien frías + 1 orden de Alitas BBQ x 12"
        )
        db.session.add(combo3)
        db.session.flush()
        db.session.add(Receta(producto_final_id=combo3.id, insumo_id=cerv_club.id, cantidad_requerida=6))
        db.session.add(Receta(producto_final_id=combo3.id, insumo_id=com_alitas.id, cantidad_requerida=1))

        # Combo 4: Previa Aguardiente Antioqueño (1 Botella Aguardiente + 2 Red Bull + 1 Agua)
        combo4 = Product(
            sku="CMB-PREV-AGU", nombre="Combo Previa (1 Aguardiente Azul + 2 Red Bull + 1 Agua)", tipo_producto="combo",
            categoria_id=cat_combos.id, cantidad_stock=0, precio_costo=0, precio_minimo=85000, precio_sugerido=115000,
            comision_mesero=10000,
            observacion="1 Botella Aguardiente Azul 750ml + 2 Red Bull 250ml + 1 Agua Mineral con Gas"
        )
        db.session.add(combo4)
        db.session.flush()
        db.session.add(Receta(producto_final_id=combo4.id, insumo_id=licor_aguardiente.id, cantidad_requerida=1))
        db.session.add(Receta(producto_final_id=combo4.id, insumo_id=beb_redbull.id, cantidad_requerida=2))
        db.session.add(Receta(producto_final_id=combo4.id, insumo_id=beb_agua.id, cantidad_requerida=1))

        db.session.commit()

        # ---------------- 8. MESAS OFICIALES HARRY BEER ----------------
        print("[6/6] Sembrando Mesas Oficiales del Bar...")
        from models import Mesa
        mesas_nombres = [
            ("Mesa 1", 4), ("Mesa 2", 4), ("Mesa 3", 6), ("Mesa 4", 4),
            ("Mesa 5", 4), ("Mesa 6", 6), ("Barra 1", 2), ("Barra 2", 2),
            ("Terraza 1", 4), ("Terraza 2", 4), ("VIP 1", 8)
        ]
        for nom, cap in mesas_nombres:
            if not Mesa.query.filter_by(nombre=nom).first():
                m = Mesa(nombre=nom, capacidad=cap, estado='libre')
                db.session.add(m)
        db.session.commit()
        
        print("OK: Seed de datos de Bar & Comidas completado con éxito.")

if __name__ == '__main__':
    seed_bar_data()
