# Instrucciones para Claude Code — Despliegue del asistente RAG

> Ejecuta este plan paso a paso en el VPS. Antes de cada bloque, **muéstrame los comandos
> que vas a ejecutar y pídeme confirmación**. No hagas nada destructivo sin avisar.
> Si encuentras algo inesperado (servicios ya corriendo, configs distintas), **pregúntame**.

---

## CONTEXTO

- Soy Alejandro. Este VPS sirve mi portafolio en `portafolio.óptimoia.es` (punycode: `portafolio.xn--ptimoia-k0a.es`).
- Quiero desplegar un chatbot RAG (FastAPI + LangGraph + ChromaDB + OpenAI) detrás de Nginx en el subdominio `api.óptimoia.es`.
- Tengo el código en este repo. La estructura es:
  ```
  api.py                       # FastAPI
  requirements.txt
  .env.example
  docs/alejandro_rag_completo.md  # base de conocimiento del RAG
  deploy/
    asistente.service          # plantilla systemd
    nginx-api-asistente.conf   # config nginx
  ```
- Tengo `OPENAI_API_KEY` lista, te la daré cuando la pidas.

---

## FASE 0 — Reconocimiento del entorno

Antes de tocar nada, dime exactamente qué tengo:

```bash
# Sistema operativo y versión
cat /etc/os-release

# Usuario actual y permisos sudo
whoami
sudo -n true 2>&1 | head -1

# Python
which python3 && python3 --version
which pip3 || echo "pip3 no instalado"
python3 -m venv --help > /dev/null 2>&1 && echo "venv OK" || echo "venv no disponible"

# Servidor web ya corriendo
sudo systemctl is-active nginx 2>/dev/null || echo "nginx no activo"
sudo systemctl is-active apache2 2>/dev/null || echo "apache2 no activo"
sudo systemctl is-active httpd 2>/dev/null || echo "httpd no activo"

# Puertos ocupados
sudo ss -tlnp | grep -E ':(80|443|8000)\s'

# Firewall
sudo ufw status 2>/dev/null || sudo firewall-cmd --state 2>/dev/null || echo "sin ufw/firewalld activo"

# Certbot
which certbot || echo "certbot no instalado"

# DNS del subdominio api (puede no estar aún)
dig +short api.xn--ptimoia-k0a.es || nslookup api.xn--ptimoia-k0a.es 2>&1 | tail -5
```

Pásame el output completo. **No avances hasta que yo te lo confirme.**

---

## FASE 1 — Instalar dependencias del sistema

Adapta los comandos al SO detectado en la Fase 0 (apt para Debian/Ubuntu, dnf para AlmaLinux/RHEL).

Necesitamos: `python3`, `python3-venv`, `python3-pip`, `nginx`, `certbot + python3-certbot-nginx`, `git`.

**Importante:** si nginx ya está corriendo sirviendo otro sitio (probablemente el portafolio), NO lo reinstales ni borres configs. Solo añade lo que falte.

Muéstrame el comando exacto antes de ejecutarlo.

---

## FASE 2 — Crear el subdominio en Hostinger

El subdominio `api.óptimoia.es` debe apuntar a la IP del VPS.

Esto se hace en hPanel de Hostinger, no en el VPS. Hazme una pausa y dime:

1. La IP pública del VPS (sácala con `curl -s ifconfig.me`).
2. Las instrucciones exactas para que yo cree en hPanel un registro A:
   - Tipo: A
   - Nombre: `api`
   - Apunta a: <IP del VPS>
   - TTL: por defecto

Espera mi confirmación de que el DNS ya propaga (puedes verificarlo con `dig +short api.xn--ptimoia-k0a.es` — debe devolver la IP).

---

## FASE 3 — Desplegar la aplicación

```bash
# 1. Carpeta de la app
sudo mkdir -p /opt/asistente
sudo chown $USER:$USER /opt/asistente
cd /opt/asistente

# 2. Clonar el código (te paso la URL del repo cuando lleguemos aquí)
git clone <URL_DEL_REPO> .

# 3. Virtualenv + dependencias
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configurar el .env (pídeme las claves)
cp .env.example .env
nano .env   # rellenar OPENAI_API_KEY y CORS_ORIGINS
```

**Antes del paso 4**, pídeme la `OPENAI_API_KEY`. Te la pasaré por chat. No la imprimas en logs.

---

## FASE 4 — Validación local (sin Nginx aún)

```bash
cd /opt/asistente
source venv/bin/activate
# Arrancar en primer plano para ver los logs de la primera carga
uvicorn api:app --host 127.0.0.1 --port 8000
```

En otra terminal SSH (o con `&` y `curl` desde el mismo VPS):

```bash
curl -s http://127.0.0.1:8000/health
# Debe responder: {"status":"ok","modelo":"gpt-4o-mini","bloques_indexados":NN,...}

curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"pregunta":"¿Qué formación tiene Alejandro?"}'
# Debe responder con una respuesta en español.
```

Si todo va bien, para el uvicorn con Ctrl+C y pasamos a la fase 5. **Si falla, pásame el log completo y no avances.**

---

## FASE 5 — Servicio systemd

```bash
# 1. Rellenar la plantilla con el usuario y el path reales
sed -e "s|__USER__|$USER|g" -e "s|__APP_DIR__|/opt/asistente|g" \
    /opt/asistente/deploy/asistente.service | sudo tee /etc/systemd/system/asistente.service > /dev/null

# 2. Activar
sudo systemctl daemon-reload
sudo systemctl enable --now asistente.service

# 3. Verificar
sudo systemctl status asistente.service --no-pager
sudo journalctl -u asistente.service -n 30 --no-pager
curl -s http://127.0.0.1:8000/health
```

El servicio debe quedar `active (running)`. **Si falla, pásame el journalctl completo.**

---

## FASE 6 — Nginx (HTTP)

```bash
# 1. Copiar config (ya viene apuntando a api.xn--ptimoia-k0a.es)
sudo cp /opt/asistente/deploy/nginx-api-asistente.conf /etc/nginx/sites-available/api-asistente

# 2. Habilitar
sudo ln -sf /etc/nginx/sites-available/api-asistente /etc/nginx/sites-enabled/api-asistente

# 3. Validar y recargar
sudo nginx -t
sudo systemctl reload nginx

# 4. Probar
curl -s http://api.xn--ptimoia-k0a.es/health
```

**Importante:** si el sistema usa `conf.d/` en lugar de `sites-available/sites-enabled` (típico en AlmaLinux/RHEL), copia el archivo a `/etc/nginx/conf.d/api-asistente.conf` directamente.

Si el firewall (`ufw` o `firewalld`) está activo y bloquea el 80/443, abre los puertos:

```bash
# ufw
sudo ufw allow 'Nginx Full'
# firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## FASE 7 — HTTPS con Let's Encrypt

```bash
sudo certbot --nginx -d api.xn--ptimoia-k0a.es
# Acepta los términos, da un email cuando lo pida, elige redirect HTTP→HTTPS.

# Verificar
curl -s https://api.xn--ptimoia-k0a.es/health

# Comprobar renovación automática
sudo systemctl status certbot.timer --no-pager
```

---

## FASE 8 — Prueba end-to-end

```bash
curl -s -X POST https://api.xn--ptimoia-k0a.es/chat \
  -H "Content-Type: application/json" \
  -d '{"pregunta":"¿Cuál es la formación de Alejandro?"}'
```

Debe devolver un JSON con `respuesta` en español, `tiempo_ms`, `thread_id`, etc.

---

## FASE 9 — Resumen y hand-off

Cuando todo funcione, dame:

1. URL final de la API: `https://api.xn--ptimoia-k0a.es`
2. Comandos útiles para gestionar el servicio:
   - `sudo systemctl status asistente`
   - `sudo systemctl restart asistente`
   - `sudo journalctl -u asistente -f` (logs en vivo)
3. Cómo actualizar el código: `cd /opt/asistente && git pull && sudo systemctl restart asistente`
4. Confirmación de que el cron de renovación de SSL está activo.

---

## REGLAS GENERALES

- **No borres nada** sin avisar. Si vas a sobrescribir un archivo, haz backup primero (`cp X X.bak`).
- **No expongas el puerto 8000** al exterior; uvicorn debe escuchar solo en `127.0.0.1`.
- **No imprimas secretos** en logs ni en el chat.
- Si **algo no encaja** con estas instrucciones (ej: hay otro sitio en el VPS que comparte config), pregúntame antes de modificar.
