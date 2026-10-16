import re
from datetime import datetime


def validar_operacion(datos, viaje, ocupados):
    nombre = (datos.get('pasajero') or '').strip()
    telefono = (datos.get('telefono') or '').strip()
    asiento_raw = (datos.get('asiento') or '').strip()
    if not 3 <= len(nombre) <= 90 or not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]+", nombre):
        return 'Escribe un nombre válido (3 a 90 caracteres, solo letras).', None
    if not re.fullmatch(r'\d{10}', telefono):
        return 'El teléfono debe contener exactamente 10 dígitos.', None
    if not asiento_raw.isdigit():
        return 'Selecciona un asiento válido.', None
    asiento = int(asiento_raw)
    if not 1 <= asiento <= viaje['capacidad']:
        return 'El asiento está fuera del rango del autobús.', None
    if asiento in ocupados:
        return 'Ese asiento ya está vendido o apartado.', None
    try:
        salida = datetime.strptime(viaje['salida'], '%Y-%m-%dT%H:%M')
        if salida <= datetime.now():
            return 'No se pueden realizar operaciones para viajes que ya salieron.', None
    except ValueError:
        return 'La fecha del viaje no es válida.', None
    return None, {'pasajero': nombre, 'telefono': telefono, 'asiento': asiento}
