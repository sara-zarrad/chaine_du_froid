"""
Chaîne du froid : ESP32 en MicroPython (sans Arduino)
DS18B20 (température) + buzzer (alerte) + GPS simulé -> Firebase Realtime Database (REST).
Même format de données que la version Arduino : le dashboard et l'API FastAPI fonctionnent sans changement.
"""
import gc
import time
import network
import machine
import onewire
import ds18x20

try:
    import urequests as requests      # MicroPython classique
except ImportError:
    import requests                   # versions récentes
try:
    import ujson as json
except ImportError:
    import json
try:
    import random
except ImportError:
    import urandom as random

# ---------------- Configuration ----------------
TEMP_MIN = 2.0                 # plage conforme (°C)
TEMP_MAX = 8.0
PIN_ONE_WIRE = 4               # DS18B20 (data, résistance 4,7 kΩ vers 3V3)
PIN_BUZZER = 27

WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""
WIFI_TIMEOUT_MS = 15000
FIREBASE_HOST = "chaine-du-froid-default-rtdb.europe-west1.firebasedatabase.app"

INTERVAL_MS = 5000             # une mesure toutes les 5 s
ALERT_AFTER = 3                # mesures hors plage consécutives avant le buzzer
LOG_SIZE = 100                 # journal circulaire /transport/log/0 ... 99

# GPS simulé : Tunis -> Hammamet -> Sousse -> Monastir -> Sfax -> retour à Tunis
ROUTE = [(36.8065, 10.1815), (36.4000, 10.6167), (35.8256, 10.6369),
         (35.7643, 10.8113), (34.7406, 10.7603), (36.8065, 10.1815)]
NB_SEGMENTS = len(ROUTE) - 1
STEP = 0.02                    # avancée par mesure (0.0 -> 1.0 sur chaque segment)

# ---------------- État ----------------
wlan = network.WLAN(network.STA_IF)
segment = 0
progress = 0.0
out_count = 0
log_index = 0


def connect_wifi():
    """Connexion Wi-Fi avec délai maximal ; force un DNS public (évite les erreurs DNS)."""
    wlan.active(True)
    if wlan.isconnected():
        return True
    print("[Wi-Fi] Connexion à", WIFI_SSID)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    start = time.ticks_ms()
    while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), start) < WIFI_TIMEOUT_MS:
        time.sleep_ms(500)
        print(".", end="")
    print()
    if not wlan.isconnected():
        print("[Wi-Fi] Échec de connexion (timeout)")
        return False
    ip, mask, gw, _dns = wlan.ifconfig()
    try:
        wlan.ifconfig((ip, mask, gw, "8.8.8.8"))
    except Exception:
        pass
    print("[Wi-Fi] Connecté, IP :", wlan.ifconfig()[0])
    return True


def gps_position():
    """Position simulée : interpolation linéaire entre deux étapes du trajet."""
    global segment, progress
    a, b = ROUTE[segment], ROUTE[segment + 1]
    lat = a[0] + progress * (b[0] - a[0])
    lon = a[1] + progress * (b[1] - a[1])
    speed = 80 + random.randint(-10, 10)
    progress += STEP
    if progress >= 1.0:
        progress = 0.0
        segment = (segment + 1) % NB_SEGMENTS
    return lat, lon, speed


def beep(ms=400):
    """Bip de 1 kHz sur le buzzer (PWM)."""
    pwm = machine.PWM(machine.Pin(PIN_BUZZER), freq=1000)
    try:
        pwm.duty(512)
    except AttributeError:
        pwm.duty_u16(32768)
    time.sleep_ms(ms)
    pwm.deinit()
    machine.Pin(PIN_BUZZER, machine.Pin.OUT).value(0)


def firebase_send(method, path, payload):
    """Envoie un JSON à Firebase (PATCH ou PUT). Succès = code HTTP 200."""
    gc.collect()
    response = None
    try:
        response = requests.request(method, "https://" + FIREBASE_HOST + path,
                                    data=payload, headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            print("[Firebase Erreur]", method, path, "code", response.status_code)
            return False
        return True
    except Exception as e:                       # coupure réseau, DNS, TLS...
        print("[Firebase Erreur]", method, path, e)
        return False
    finally:
        if response is not None:
            response.close()


def read_temperature(sensor, roms):
    """Retourne la température en °C, ou None si le capteur est absent."""
    if not roms:
        return None
    sensor.convert_temp()
    time.sleep_ms(750)                           # temps de conversion du DS18B20
    return sensor.read_temp(roms[0])


def cycle(sensor, roms):
    """Une mesure : lecture, alerte locale, envoi à Firebase."""
    global out_count, log_index
    temp = read_temperature(sensor, roms)
    if temp is None:
        print("[ERREUR] DS18B20 non détecté. Mesure ignorée.")
        return
    out_of_range = temp < TEMP_MIN or temp > TEMP_MAX
    out_count = out_count + 1 if out_of_range else 0
    lat, lon, speed = gps_position()
    print("[Mesure] Temp: {:.2f} C | GPS: ({:.5f}, {:.5f}) | Vitesse: {} km/h | Etat: {}".format(
        temp, lat, lon, speed, "HORS PLAGE" if out_of_range else "OK"))
    if out_count >= ALERT_AFTER:
        print("[ALERTE] Rupture de la chaine du froid !")
        beep(400)

    if not wlan.isconnected() and not connect_wifi():
        return
    payload = json.dumps({"temperature": round(temp, 2), "lat": round(lat, 5), "lon": round(lon, 5),
                          "speed": speed, "out_of_range": out_of_range, "ts": {".sv": "timestamp"}})
    if firebase_send("PATCH", "/transport/current.json", payload):
        if firebase_send("PUT", "/transport/log/{}.json".format(log_index), payload):
            log_index = (log_index + 1) % LOG_SIZE


def main():
    print("=== Chaine du froid : ESP32 MicroPython ===")
    machine.Pin(PIN_BUZZER, machine.Pin.OUT).value(0)
    sensor = ds18x20.DS18X20(onewire.OneWire(machine.Pin(PIN_ONE_WIRE)))
    roms = sensor.scan()
    print("[DS18B20] capteurs trouvés :", len(roms))
    connect_wifi()
    while True:
        start = time.ticks_ms()
        cycle(sensor, roms)
        wait = INTERVAL_MS - time.ticks_diff(time.ticks_ms(), start)
        if wait > 0:
            time.sleep_ms(wait)


main()
