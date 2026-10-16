
import os
import sqlite3
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, abort, jsonify
)

from base_de_datos.conexion import (
    inicializar_db, obtener_db, cerrar_db
)

from base_de_datos.rutas import RUTAS
from validaciones.boletos import validar_operacion

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "alexito-desarrollo-local-cambiar-clave"
)

app.teardown_appcontext(cerrar_db)

inicializar_db()


@app.template_filter("fecha")
def formato_fecha(valor):
    if not valor:
        return ""

    return datetime.strptime(
        valor, "%Y-%m-%dT%H:%M"
    ).strftime("%d/%m/%Y - %H:%M")


def viajes_con_conteo():
    db = obtener_db()

    return db.execute("""
        SELECT v.*,
        COUNT(b.id) AS ocupados,
        COALESCE(SUM(
            CASE WHEN b.estado = 'VENDIDO'
            THEN 1 ELSE 0 END
        ), 0) AS vendidos,
        COALESCE(SUM(
            CASE WHEN b.estado = 'APARTADO'
            THEN 1 ELSE 0 END
        ), 0) AS apartados

        FROM viajes v

        LEFT JOIN boletos b
        ON b.viaje_id = v.id

        WHERE v.codigo_ruta IS NOT NULL
        AND v.salida > ?

        GROUP BY v.id
        ORDER BY v.salida, v.id
    """, (
        datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )).fetchall()


def detalle_viaje(viaje_id):
    db = obtener_db()

    viaje = db.execute("""
        SELECT * FROM viajes
        WHERE id = ?
        AND codigo_ruta IS NOT NULL
    """, (viaje_id,)).fetchone()

    if viaje is None:
        abort(404)

    boletos = db.execute("""
        SELECT * FROM boletos
        WHERE viaje_id = ?
        ORDER BY asiento
    """, (viaje_id,)).fetchall()

    estados = {
        b["asiento"]: b["estado"]
        for b in boletos
    }

    return viaje, boletos, estados


def seleccionar_viaje(viajes):
    valor = (
        request.form.get("viaje_id")
        if request.method == "POST"
        else request.args.get("viaje_id")
    )

    if valor:
        try:
            viaje_id = int(valor)
        except ValueError:
            abort(400)

        if not any(v["id"] == viaje_id for v in viajes):
            abort(400)

        return viaje_id

    return viajes[0]["id"] if viajes else None


@app.route("/")
def index():
    db = obtener_db()

    resumen = db.execute("""
        SELECT
        COUNT(*) AS total,
        COALESCE(SUM(
            CASE WHEN estado='VENDIDO'
            THEN 1 ELSE 0 END
        ), 0) AS vendidos,
        COALESCE(SUM(
            CASE WHEN estado='APARTADO'
            THEN 1 ELSE 0 END
        ), 0) AS apartados
        FROM boletos
    """).fetchone()

    return render_template(
        "index.html",
        viajes=viajes_con_conteo(),
        resumen=resumen,
        activo="inicio"
    )


@app.route("/venta", methods=["GET", "POST"])
def venta():
    return operacion(
        "VENDIDO",
        "venta.html",
        "venta"
    )


@app.route("/apartados", methods=["GET", "POST"])
def apartados():
    return operacion(
        "APARTADO",
        "apartados.html",
        "apartados"
    )


def operacion(estado, plantilla, activo):
    db = obtener_db()

    viajes = viajes_con_conteo()
    viaje_id = seleccionar_viaje(viajes)

    if viaje_id is not None:
        viaje, boletos, estados = detalle_viaje(viaje_id)
    else:
        viaje, boletos, estados = None, [], {}

    if request.method == "POST" and viaje:
        error, datos = validar_operacion(
            request.form,
            viaje,
            set(estados)
        )

        if error:
            flash(error, "error")

        else:
            try:
                db.execute("BEGIN IMMEDIATE")

                ocupacion = db.execute("""
                    SELECT id FROM boletos
                    WHERE viaje_id = ?
                    AND asiento = ?
                """, (
                    viaje_id,
                    datos["asiento"]
                )).fetchone()

                if ocupacion:
                    raise sqlite3.IntegrityError(
                        "Asiento ocupado"
                    )

                db.execute("""
                    INSERT INTO boletos (
                        viaje_id,
                        asiento,
                        pasajero,
                        telefono,
                        estado,
                        destino_boleto,
                        precio_boleto
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    viaje_id,
                    datos["asiento"],
                    datos["pasajero"],
                    datos["telefono"],
                    estado,
                    datos["destino"],
                    datos["precio"]
                ))

                db.commit()

                if estado == "VENDIDO":
                    flash(
                        "Boleto vendido correctamente.",
                        "success"
                    )
                else:
                    flash(
                        "Asiento apartado correctamente.",
                        "success"
                    )

                return redirect(url_for(
                    activo,
                    viaje_id=viaje_id
                ))

            except sqlite3.IntegrityError:
                db.rollback()
                flash(
                    "El asiento ya está ocupado.",
                    "error"
                )

            except sqlite3.Error:
                db.rollback()
                flash(
                    "Error al guardar la operación.",
                    "error"
                )

        viaje, boletos, estados = detalle_viaje(viaje_id)

    destinos = {}

    if viaje:
        destinos = RUTAS[
            viaje["codigo_ruta"]
        ]["destinos"]

    return render_template(
        plantilla,
        viajes=viajes,
        viaje=viaje,
        estados=estados,
        ocupados=len(boletos),
        destinos=destinos,
        activo=activo,
        rutas=RUTAS
    )


@app.route("/boletos")
def boletos():
    db = obtener_db()

    registros = db.execute("""
        SELECT
        b.*,
        v.origen,
        v.destino AS destino_final,
        v.salida,
        v.codigo_ruta

        FROM boletos b
        JOIN viajes v
        ON v.id = b.viaje_id

        WHERE b.estado = 'VENDIDO'

        ORDER BY b.id DESC
    """).fetchall()

    return render_template(
        "boletos.html",
        registros=registros,
        rutas=RUTAS,
        activo="boletos"
    )


@app.route("/disponibilidad")
def disponibilidad():
    viajes = viajes_con_conteo()
    viaje_id = seleccionar_viaje(viajes)

    if viaje_id:
        viaje, boletos, estados = detalle_viaje(viaje_id)
    else:
        viaje, boletos, estados = None, [], {}

    return render_template(
        "disponibilidad.html",
        viajes=viajes,
        viaje=viaje,
        boletos=boletos,
        estados=estados,
        rutas=RUTAS,
        activo="disponibilidad"
    )


@app.post("/apartados/<int:boleto_id>/confirmar")
def confirmar_apartado(boleto_id):
    db = obtener_db()

    fila = db.execute("""
        SELECT viaje_id FROM boletos
        WHERE id = ? AND estado = 'APARTADO'
    """, (boleto_id,)).fetchone()

    if fila is None:
        flash("El apartado no está disponible.", "error")
        return redirect(url_for("disponibilidad"))

    resultado = db.execute("""
        UPDATE boletos
        SET estado = 'VENDIDO'
        WHERE id = ?
        AND estado = 'APARTADO'
    """, (boleto_id,))

    db.commit()

    flash(
        "Apartado confirmado."
        if resultado.rowcount
        else "No se pudo confirmar.",
        "success" if resultado.rowcount else "error"
    )

    return redirect(url_for(
        "disponibilidad",
        viaje_id=fila["viaje_id"]
    ))


@app.post("/apartados/<int:boleto_id>/liberar")
def liberar_apartado(boleto_id):
    db = obtener_db()

    fila = db.execute("""
        SELECT viaje_id FROM boletos
        WHERE id = ? AND estado = 'APARTADO'
    """, (boleto_id,)).fetchone()

    if fila is None:
        flash("El apartado no existe.", "error")
        return redirect(url_for("disponibilidad"))

    resultado = db.execute("""
        DELETE FROM boletos
        WHERE id = ? AND estado = 'APARTADO'
    """, (boleto_id,))

    db.commit()

    flash(
        "Asiento liberado."
        if resultado.rowcount
        else "No se pudo liberar.",
        "success" if resultado.rowcount else "error"
    )

    return redirect(url_for(
        "disponibilidad",
        viaje_id=fila["viaje_id"]
    ))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
        threaded=True
    )
