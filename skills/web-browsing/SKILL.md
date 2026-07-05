---
name: "web-browsing"
version: "1.1.0"
description: >-
  Activa cuando el usuario quiere navegar a internet, buscar en la web,
  abrir páginas, abrir archivos locales en el navegador (PDF, imágenes,
  HTML, video, audio, código), hacer clic en botones, rellenar formularios,
  leer contenido de páginas o tomar capturas de pantalla del navegador.
tags: [browser, web, internet, navegar, buscar, url, pagina, chrome, chromium, screenshot, formulario, clic, pdf, imagen, video, audio]
---

## Context
Eres un experto en automatización web con Playwright y en apertura de
archivos locales en el navegador. Controlas un navegador Chromium real.
La sesión persiste entre tus acciones en la misma conversación.

El navegador puede renderizar de forma nativa sin necesidad de otras apps:
- **PDF**        → visor integrado con zoom, búsqueda de texto y descarga
- **Imágenes**   → png, jpg, jpeg, gif, svg, webp, bmp, ico, avif
- **HTML**       → renderizado completo con CSS y JS
- **Video**      → mp4, webm, ogv  (player HTML5 nativo)
- **Audio**      → mp3, wav, ogg, flac, aac, m4a (player HTML5 nativo)
- **Texto/Código** → txt, json, xml, csv, md, py, js, yaml... (texto plano)

Para Word/Excel/PowerPoint usa `open_file` en su lugar.

## Instructions

### Abrir archivos locales en el navegador
```
browser(action="open", url="/home/ANDERVRZ/Downloads/documento.pdf")
browser(action="open", url="/home/ANDERVRZ/Pictures/foto.png")
browser(action="open", url="/home/ANDERVRZ/Documents/informe.html")
```
Pasa la ruta absoluta directamente en `url` — se convierte automáticamente
a `file:///ruta`. No hace falta escribir `file://` manualmente.

### Navegar a internet
```
browser(action="open", url="https://example.com")
browser(action="search", query="noticias de IA hoy")
```

### Interactuar con la página
1. `click` con el texto visible del elemento o selector CSS
2. `type` para rellenar campos (con selector o elemento activo)
3. `read` para extraer el texto de la página actual
4. `screenshot` para capturar lo que se ve

### Flujo formulario
```
browser(action="open",   url="https://sitio.com/login")
browser(action="click",  selector="input[name=email]")
browser(action="type",   text="usuario@ejemplo.com")
browser(action="click",  selector="Iniciar sesión")
```

## Constraints
- NO uses `open_file` para PDFs o imágenes si el usuario quiere verlos
  directamente — usa `browser` para que se abran en el visor integrado.
- NO hagas clic en botones de pago o confirmación sin autorización explícita.
- Contenido truncado a 6000 caracteres en `read` para no saturar el contexto.
- Screenshots guardados en ~/Pictures/screenshots/.
- Si no hay display gráfico, el navegador corre en modo headless automáticamente.

## Examples
- "ábrme el PDF del currículum" → `browser(action="open", url="/home/ANDERVRZ/Downloads/Curriculum Vitae.pdf")`
- "muéstrame la foto jpeg" → `browser(action="open", url="/home/ANDERVRZ/Pictures/foto.jpg")`
- "abre el HTML que generé" → `browser(action="open", url="/home/ANDERVRZ/Documents/reporte.html")`
- "reproduce el video" → `browser(action="open", url="/home/ANDERVRZ/Videos/clip.mp4")`
- "busca documentación de FastAPI" → `browser(action="search", query="FastAPI documentation")`
- "léeme lo que dice esa página" → `browser(action="read")`
- "haz clic en Enviar" → `browser(action="click", selector="Enviar")`
- "toma una captura del estado actual" → `browser(action="screenshot")`
- "cierra el navegador" → `browser(action="close")`