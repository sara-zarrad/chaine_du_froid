# ESP32 MicroPython (simulation Wokwi)

- `main.py` : programme de l'ESP32 (DS18B20, buzzer, GPS simulé, envoi vers Firebase)
- `diagram.json` : schéma de câblage Wokwi
- `wokwi.toml` : configuration de l'extension Wokwi pour VS Code / Antigravity

## Simulation sur wokwi.com (le plus simple)
Copier `main.py` et `diagram.json` dans un projet ESP32 MicroPython, puis cliquer sur Play.

## Simulation dans Antigravity / VS Code
Le firmware MicroPython (`*.bin`, environ 2 Mo) n'est **pas** versionné. Le télécharger une fois :
```
Invoke-WebRequest -Uri "https://github.com/wokwi/wokwi-vscode-micropython/raw/main/esp32/ESP32_GENERIC-20251209-v1.27.0.bin" -OutFile "ESP32_GENERIC-20251209-v1.27.0.bin"
py -m pip install mpremote
```
Puis : ouvrir `diagram.json`, cliquer sur **Play**, laisser l'onglet du simulateur visible et, dans un second terminal :
```
py -m mpremote connect port:rfc2217://localhost:4000 run main.py
```
