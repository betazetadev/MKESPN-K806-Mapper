# Mini Keypad Mapper

**Mini Keypad Mapper** es una herramienta sencilla para Linux que permite asignar **atajos de teclado** y **comandos personalizados** a un mini teclado USB de 8 teclas (distribución de 2 filas x 4 columnas).

Con esta aplicación puedes convertir tu pequeño keypad en un **panel de accesos directos** para abrir aplicaciones, lanzar combinaciones de teclas o ejecutar comandos, todo de forma visual y fácil de configurar.

> ⚠️ **Nota de compatibilidad:** Actualmente solo está probada con un modelo económico tipo *"8 key programming game keyboard"* (VendorID: `30fa`, ProductID: `1340`).  
> Si tienes otro modelo, eres libre de hacer un **fork**, adaptar el código y contribuir con mejoras o abrir un *issue* (no aseguramos soporte oficial, pero lo revisaremos con interés).

---

## ✨ Características

- **GUI visual** para asignar acciones a cada tecla
- Ejecución de **comandos** (ej. `firefox`, `code`, `nautilus`)
- Ejecución de **combos de teclado** (ej. `Ctrl+Alt+T`, `Super+E`)
- **Resaltado visual** de la tecla pulsada en el mapa
- Guardado automático en JSON de las asignaciones
- **Daemon opcional** para que funcione en segundo plano al iniciar sesión
- Código abierto con licencia MIT

---

## 🛠️ Requisitos

- **Sistema Operativo:** Linux (probado en Ubuntu 22.04+ con X11/Wayland)
- **Python:** 3.8+
- **Dependencias del sistema:**

```bash
sudo apt install -y python3-evdev python3-tk xdotool
```

---

## ⚙️ Configuración de Permisos

Por defecto, los dispositivos de entrada en `/dev/input/event*` requieren permisos de administrador. Para usar el mini teclado sin `sudo`, sigue estos pasos:

### 1. Crear regla udev

Crea el archivo de configuración:

```bash
sudo nano /etc/udev/rules.d/99-mini-keypad.rules
```

### 2. Añadir la regla

Agrega la siguiente línea al archivo:

```
SUBSYSTEM=="input", ATTRS{idVendor}=="30fa", ATTRS{idProduct}=="1340", MODE="0666"
```

### 3. Recargar las reglas

```bash
sudo udevadm control --reload
sudo udevadm trigger
```

### 4. Reconectar el dispositivo

Desconecta y vuelve a conectar el teclado. Ahora tu usuario podrá acceder al dispositivo sin usar `sudo`.

---

## 🚀 Uso

### GUI (Configuración)

1. Ejecuta la aplicación:
   ```bash
   python3 mini_keypad_mapper.py
   ```

2. **Selecciona tu dispositivo** (`/dev/input/eventXX`)

3. **Pulsa "Record from device"** para capturar teclas

4. **Asigna comandos o combos** y guarda la configuración

5. La configuración se almacena automáticamente en `~/.keymap.json`

### Daemon (Ejecución en Segundo Plano)

Una vez configurado, puedes arrancar el daemon minimalista:

```bash
python3 mini_keypad_daemon.py
```

#### Ejecutar al inicio de sesión

Para que se ejecute automáticamente:

- **Opción 1:** Añádelo en "Aplicaciones al inicio" de tu entorno de escritorio
- **Opción 2:** Crea un servicio systemd `--user`

---

## 💡 Ideas para el Futuro

- [ ] Soporte de **perfiles de layouts** (cambiar entre distintos mapeos guardados)
- [ ] Mejoras en la **interfaz y experiencia de usuario**
- [ ] **Layouts predefinidos** para distintos tipos de teclados
- [ ] Mayor **compatibilidad** con modelos adicionales de keypads

---

## 🤝 Contribuciones

¡Las contribuciones son bienvenidas! 🎉

- Si tienes **otro modelo** de mini teclado, puedes hacer un fork y adaptarlo
- Si detectas un **bug** o necesitas soporte para un teclado distinto, abre un *issue* (no prometemos solucionarlo, pero lo revisaremos)
- **Pull requests** con mejoras son siempre apreciados

---

## 📄 Licencia

Este proyecto se distribuye bajo **licencia MIT**.

Eres libre de usarlo, modificarlo y compartirlo, siempre que incluyas la licencia original.
