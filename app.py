import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from base_de_datos.conexion import inicializar_db, obtener_db, cerrar_db
from validaciones.boletos import validar_operacion

app = Flask(__name__)
app.config['SECRET_KEY'] = 'central-autobuses-practica-red-local-2026'
app.teardown_appcontext(cerrar_db)
inicializar_db()

@app.template_filter('fecha')
def formato_fecha(valor):
    return datetime.strptime(valor, '%Y-%m-%dT%H:%M').strftime('%d/%m/%Y · %H:%M')


def viajes_con_conteo():
    return obtener_db().execute('''
        SELECT v.*, COUNT(b.id) AS ocupados,
        SUM(CASE WHEN b.estado = 'VENDIDO' THEN 1 ELSE 0 END) AS vendidos,
        SUM(CASE WHEN b.estado = 'APARTADO' THEN 1 ELSE 0 END) AS apartados
        FROM viajes v LEFT JOIN boletos b ON b.viaje_id=v.id
        GROUP BY v.id ORDER BY v.salida, v.id
    ''').fetchall()


def detalle_viaje(viaje_id):
    db = obtener_db()
    viaje = db.execute('SELECT * FROM viajes WHERE id=?', (viaje_id,)).fetchone()
    if viaje is None:
        abort(404)
    boletos = db.execute('SELECT * FROM boletos WHERE viaje_id=? ORDER BY asiento', (viaje_id,)).fetchall()
    estados = {b['asiento']: b['estado'] for b in boletos}
    return viaje, boletos, estados

@app.route('/')
def index():
    db = obtener_db()
    resumen = db.execute('''SELECT COUNT(*) AS total,
      COALESCE(SUM(estado='VENDIDO'),0) AS vendidos,
      COALESCE(SUM(estado='APARTADO'),0) AS apartados
      FROM boletos''').fetchone()
    return render_template('index.html', viajes=viajes_con_conteo(), resumen=resumen, activo='inicio')

@app.route('/venta', methods=['GET', 'POST'])
def venta():
    return operacion('VENDIDO', 'venta.html', 'venta')

@app.route('/apartados', methods=['GET', 'POST'])
def apartados():
    return operacion('APARTADO', 'apartados.html', 'apartados')


def operacion(estado, plantilla, activo):
    db = obtener_db()
    viajes = viajes_con_conteo()
    id_raw = request.form.get('viaje_id') if request.method == 'POST' else request.args.get('viaje_id')
    try:
        viaje_id = int(id_raw) if id_raw else (viajes[0]['id'] if viajes else None)
    except (ValueError, TypeError):
        abort(400)
    viaje, boletos, estados = detalle_viaje(viaje_id) if viaje_id is not None else (None, [], {})
    if request.method == 'POST' and viaje:
        error, datos = validar_operacion(request.form, viaje, set(estados))
        if error:
            flash(error, 'error')
        else:
            try:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO boletos (viaje_id,asiento,pasajero,telefono,estado) VALUES (?,?,?,?,?)',
                           (viaje_id, datos['asiento'], datos['pasajero'], datos['telefono'], estado))
                db.commit()
                flash(('Boleto vendido' if estado == 'VENDIDO' else 'Asiento apartado') + ' correctamente.', 'success')
                return redirect(url_for(activo, viaje_id=viaje_id))
            except sqlite3.IntegrityError:
                db.rollback()
                flash('El asiento acaba de ser ocupado. Selecciona otro.', 'error')
            except sqlite3.Error:
                db.rollback()
                flash('No se pudo guardar la operación.', 'error')
        viaje, boletos, estados = detalle_viaje(viaje_id)
    return render_template(plantilla, viajes=viajes, viaje=viaje,
                           estados=estados, activo=activo, ocupados=len(boletos))

@app.route('/boletos')
def boletos():
    db = obtener_db()
    registros = db.execute('''SELECT b.*,v.origen,v.destino,v.salida,v.precio
       FROM boletos b JOIN viajes v ON v.id=b.viaje_id
       WHERE b.estado='VENDIDO' ORDER BY b.id DESC''').fetchall()
    return render_template('boletos.html', registros=registros, activo='boletos')

@app.route('/disponibilidad')
def disponibilidad():
    viajes = viajes_con_conteo()
    valor = request.args.get('viaje_id', type=int)
    viaje_id = valor or (viajes[0]['id'] if viajes else None)
    viaje, boletos, estados = detalle_viaje(viaje_id) if viaje_id else (None, [], {})
    return render_template('disponibilidad.html', viajes=viajes, viaje=viaje,
                           estados=estados, boletos=boletos, activo='disponibilidad')

@app.post('/apartados/<int:boleto_id>/confirmar')
def confirmar_apartado(boleto_id):
    db = obtener_db()
    resultado = db.execute("UPDATE boletos SET estado='VENDIDO' WHERE id=? AND estado='APARTADO'", (boleto_id,))
    db.commit()
    flash('Apartado convertido en venta.' if resultado.rowcount else 'Ese apartado ya no está disponible.',
          'success' if resultado.rowcount else 'error')
    return redirect(url_for('disponibilidad'))

@app.post('/apartados/<int:boleto_id>/liberar')
def liberar_apartado(boleto_id):
    db = obtener_db()
    resultado = db.execute("DELETE FROM boletos WHERE id=? AND estado='APARTADO'", (boleto_id,))
    db.commit()
    flash('Asiento liberado.' if resultado.rowcount else 'No se encontró un apartado activo.',
          'success' if resultado.rowcount else 'error')
    return redirect(url_for('disponibilidad'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
