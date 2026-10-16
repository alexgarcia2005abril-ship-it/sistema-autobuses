
import re
from datetime import datetime
from base_de_datos.rutas import RUTAS


def validar_operacion(datos, viaje, ocupados):
    nombre = (datos.get("pasajero") or "").strip()
    telefono = (datos.get("telefono") or "").strip()
    asiento_raw = (datos.get("asiento") or "").strip()
    destino = (datos.get("destino") or "").strip()

    if not 3 <= len(nombre) <= 90:
        return "El nombre debe tener entre 3 y 90 caracteres.", None

    if not re.fullmatch(
        r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]+",
        nombre
    ):
        return "El nombre solo puede contener letras.", None

    if not re.fullmatch(r"[0-9]{10}", telefono):
        return "El teléfono debe tener 10 dígitos.", None

    if not asiento_raw.isdigit():
        return "Selecciona un asiento.", None

    asiento = int(asiento_raw)

    if asiento < 1 or asiento > viaje["capacidad"]:
        return "El asiento no es válido.", None

    if asiento in ocupados:
        return "Este asiento ya está ocupado o apartado.", None

    codigo = viaje["codigo_ruta"]

    if codigo not in RUTAS:
        return "La ruta seleccionada no es válida.", None

    destinos = RUTAS[codigo]["destinos"]

    if destino not in destinos:
        return "Selecciona un destino válido.", None

    try:
        salida = datetime.strptime(
            viaje["salida"],
            "%Y-%m-%dT%H:%M"
        )
    except ValueError:
        return "La fecha del viaje no es válida.", None

    if salida <= datetime.now():
        return "Esta salida ya terminó.", None

    precio = destinos[destino]

    return None, {
        "pasajero": nombre,
        "telefono": telefono,
        "asiento": asiento,
        "destino": destino,
        "precio": precio
    }
