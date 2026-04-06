#!/bin/bash
# =============================================
# GIO TELEMETRY — Script de despliegue v3
# Corre en cada EC2 cuando GitHub Actions hace deploy
# Actualizado para arquitectura modular
# =============================================

set -e  # si cualquier comando falla, para el script

echo "[START] Iniciando despliegue en $(hostname)..."

# 1. Cargar variables de entorno
if [ -f ~/.env ]; then
    set -a
    source ~/.env
    set +a
    echo "[ENV] Variables cargadas desde ~/.env"
else
    echo "[ERROR] No se encontro ~/.env — crea el archivo primero"
    exit 1
fi

# 2. Ir a la carpeta del repositorio
if [ ! -d ~/Gio-telemetry ]; then
    echo "[GIT] Clonando repositorio por primera vez..."
    cd ~
    git clone https://github.com/llancherof-fl/Gio-telemetry.git
else
    echo "[GIT] Repositorio ya existe, haciendo pull..."
fi

cd ~/Gio-telemetry

# 3. Actualizar el codigo desde main
git fetch origin
git reset --hard origin/main
echo "[GIT] Codigo actualizado a la ultima version de main"

# 4. Instalar dependencias (compatible con Python 3.12+ PEP 668)
if [ -f requirements.txt ]; then
    echo "[PIP] Instalando dependencias..."
    pip3 install --user --break-system-packages -q -r requirements.txt 2>&1 || \
    pip3 install --user -q -r requirements.txt 2>&1 || \
    pip3 install --break-system-packages -q -r requirements.txt 2>&1 || \
    sudo pip3 install --break-system-packages -q -r requirements.txt 2>&1 || \
    sudo pip3 install -q -r requirements.txt 2>&1 || \
    echo "[WARN] No se pudieron instalar dependencias pip (el servidor puede funcionar igual)"
    echo "[PIP] Dependencias procesadas"
fi

# 5. Copiar .env al directorio del proyecto
cp ~/.env ~/Gio-telemetry/.env 2>/dev/null || true

# 6. Matar TODOS los procesos del servidor anterior y liberar puertos
echo "[KILL] Deteniendo servidor anterior..."
sudo pkill -9 -f "python3.*server" 2>/dev/null || true
sudo pkill -9 -f server_aws_final.py 2>/dev/null || true
# Matar cualquier cosa en los puertos que necesitamos
sudo fuser -k 8080/tcp 2>/dev/null || true
sudo fuser -k 443/tcp 2>/dev/null || true
sudo fuser -k 5001/udp 2>/dev/null || true
# Esperar a que los puertos se liberen completamente
sleep 4
echo "[KILL] Servidor anterior detenido y puertos liberados"

# 7. Arrancar el servidor nuevo
if [ "$USE_HTTPS" = "true" ]; then
    echo "[START] Arrancando en modo HTTPS en puerto $PORT_HTTPS..."
    sudo -E nohup python3 ~/Gio-telemetry/server.py > ~/server.log 2>&1 &
else
    echo "[START] Arrancando en modo HTTP en puerto $PORT_WEB..."
    nohup python3 ~/Gio-telemetry/server.py > ~/server.log 2>&1 &
fi

sleep 4

# 8. Verificar que arranco correctamente
if pgrep -f "python3.*server.py" > /dev/null; then
    echo "[OK] Servidor corriendo exitosamente"
    tail -8 ~/server.log
else
    echo "[ERROR] El servidor no arranco — revisa ~/server.log"
    tail -20 ~/server.log
    exit 1
fi

echo "[DONE] Despliegue completado en $(hostname)"
