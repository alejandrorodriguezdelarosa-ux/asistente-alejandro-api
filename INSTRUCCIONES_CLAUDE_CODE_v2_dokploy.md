# Instrucciones para Claude Code v2 — Despliegue en Dokploy + Traefik

> Este plan reemplaza al `INSTRUCCIONES_CLAUDE_CODE.md` original. El VPS usa
> Dokploy + Traefik, no Nginx + systemd. Adaptamos el despliegue a la
> infraestructura existente para no romper nada.

---

## CONTEXTO

- VPS Hostinger, Ubuntu 24.04, root.
- IP pública IPv4: `72.62.237.236`.
- Dokploy gestiona los servicios; Traefik (en Docker) hace de reverse proxy con SSL automático.
- Quiero desplegar mi chatbot RAG como un servicio más de Dokploy, en `api.óptimoia.es` (punycode `api.xn--ptimoia-k0a.es`).
- El repo trae ya `Dockerfile`, `docker-compose.yml` con labels de Traefik, y `.env.example`.

---

## FASE A — Verificar el entorno Dokploy/Traefik

Antes de tocar nada, confirma estos puntos y muéstrame el output:

```bash
# Dokploy corriendo
sudo systemctl is-active dokploy 2>/dev/null || docker ps --filter "name=dokploy" --format "table {{.Names}}\t{{.Status}}"

# Nombre exacto de la red de Docker que usa Dokploy/Traefik
docker network ls

# Contenedor de Traefik y a qué red está adjunto
docker ps --filter "ancestor=traefik" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>/dev/null
docker ps | grep -i traefik

# Confirmar que Traefik usa Let's Encrypt y qué nombre tiene el resolver
# (suele ser "letsencrypt", pero en Dokploy puede variar)
docker inspect $(docker ps -qf "name=traefik" | head -1) 2>/dev/null \
  | grep -iE "certificatesresolvers|letsencrypt|acme" | head -20

# Ver el directorio donde Dokploy guarda configs dinámicas (puede no usarse si todo va por labels)
ls -la /etc/dokploy/ 2>/dev/null
```

**Datos críticos que necesito antes de avanzar:**

1. ¿Cuál es el nombre exacto de la red de Dokploy/Traefik? (probablemente `dokploy-network`, pero confírmalo).
2. ¿Cuál es el nombre del cert resolver de Traefik en la config de Dokploy? (probablemente `letsencrypt`).
3. ¿Dokploy permite desplegar desde repos de GitHub via su UI, o se hace todo por CLI/docker?

Pásame el output y espera mi confirmación.

---

## FASE B — DNS del subdominio

El subdominio debe apuntar al VPS antes de seguir. Yo lo hago en hPanel de Hostinger:

- Tipo: `A`
- Nombre: `api`
- Valor: `72.62.237.236`
- TTL: por defecto

Verifica cuando te lo confirme:

```bash
dig +short api.xn--ptimoia-k0a.es
# Debe devolver 72.62.237.236
```

No avances hasta que la IP responda correctamente.

---

## FASE C — Desplegar via Dokploy

Hay dos rutas posibles. Elige la que mejor encaje con cómo gestiono yo el resto de servicios (pregúntamelo si no está claro):

### Ruta C.1 — Desde la UI de Dokploy (recomendada si así despliego el resto)

1. En la UI de Dokploy → New Application → Docker Compose.
2. Conectar el repo `https://github.com/alejandrorodriguezdelarosa-ux/asistente-alejandro-api.git`, rama `main`.
3. Variables de entorno (las añado en la UI, no en el repo):
   - `OPENAI_API_KEY` → me la pides aquí
   - `OPENAI_MODEL` = `gpt-4o-mini`
   - `CORS_ORIGINS` = `https://portafolio.xn--ptimoia-k0a.es,https://xn--ptimoia-k0a.es`
4. Deploy.

Mírame el flujo exacto que sigues con los otros servicios (Chatwoot, n8n) y replícalo.

### Ruta C.2 — Por CLI con `docker compose` (si Dokploy no permite UI para esto)

```bash
# Carpeta de la app
sudo mkdir -p /opt/asistente && sudo chown root:root /opt/asistente
cd /opt/asistente

# Clonar
git clone https://github.com/alejandrorodriguezdelarosa-ux/asistente-alejandro-api.git .

# Crear .env REAL (pídeme la OPENAI_API_KEY aquí, NO la imprimas en logs)
cp .env.example .env
# editar .env con la clave real

# Verificar que el docker-compose.yml apunta a la red correcta
# (si en la FASE A la red NO se llama "dokploy-network", editar el yml antes)

# Levantar
docker compose up -d --build

# Verificar
docker compose ps
docker compose logs --tail=50 asistente
```

---

## FASE D — Validación

```bash
# Healthcheck (puede tardar 30-60s la primera vez, está cargando embeddings)
curl -s https://api.xn--ptimoia-k0a.es/health

# Debe responder algo como:
# {"status":"ok","modelo":"gpt-4o-mini","bloques_indexados":NN,"agente_listo":true}

# Prueba real de chat
curl -s -X POST https://api.xn--ptimoia-k0a.es/chat \
  -H "Content-Type: application/json" \
  -d '{"pregunta":"¿Qué formación tiene Alejandro?"}'
```

Si el healthcheck devuelve `agente_listo: false`, espera 30s y reintenta — el agente tarda en arrancar la primera vez por la indexación de ChromaDB.

---

## FASE E — Hand-off

Cuando todo funcione, dame:

1. URL final: `https://api.xn--ptimoia-k0a.es`
2. Cómo lo gestiono desde Dokploy (UI o CLI).
3. Cómo veo logs en vivo:
   - UI: panel de logs del servicio
   - CLI: `cd /opt/asistente && docker compose logs -f asistente`
4. Cómo actualizo cuando haga push al repo (probablemente redeploy desde la UI de Dokploy).

---

## REGLAS GENERALES

- **NO toques** la config de Traefik existente: solo añadimos un servicio nuevo con sus labels.
- **NO instales Nginx, certbot, ufw, ni nada que pise puertos 80/443.**
- **NO imprimas secretos** (`OPENAI_API_KEY`) en chat ni en logs.
- Si algo es ambiguo o no encaja con cómo está montado este VPS, **pregúntame**.
- Backups antes de tocar configs compartidas: `cp X X.bak`.
