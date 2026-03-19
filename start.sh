#!/bin/bash
# =============================================
# GIO TELEMETRY — Script de despliegue
# Corre en cada EC2 cuando GitHub Actions hace deploy
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

# 4. Copiar el servidor al home (donde lo corre systemd)
cp server_aws_final.py ~/server_aws_final.py
echo "[FILE] server_aws_final.py copiado a ~/"

# 5. Matar el servidor anterior si existe
sudo pkill -9 -f server_aws_final.py 2>/dev/null || true
sleep 2
echo "[KILL] Servidor anterior detenido"

# 6. Arrancar el servidor nuevo
if [ "$USE_HTTPS" = "true" ]; then
    echo "[START] Arrancando en modo HTTPS en puerto $PORT_HTTPS..."
    sudo -E nohup python3 ~/server_aws_final.py > ~/server.log 2>&1 &
else
    echo "[START] Arrancando en modo HTTP en puerto $PORT_WEB..."
    nohup python3 ~/server_aws_final.py > ~/server.log 2>&1 &
fi

sleep 3

# 7. Verificar que arranco correctamente
if pgrep -f server_aws_final.py > /dev/null; then
    echo "[OK] Servidor corriendo exitosamente"
    tail -5 ~/server.log
else
    echo "[ERROR] El servidor no arranco — revisa ~/server.log"
    cat ~/server.log
    exit 1
fi

echo "[DONE] Despliegue completado en $(hostname)"
