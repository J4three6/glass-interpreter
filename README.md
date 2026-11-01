
# Glass Interpreter

Traduce en tiempo real los subtítulos de **Windows Live Captions (inglés)** y **Chrome Live Caption (español)**, convirtiendo cada uno al idioma opuesto en una ventana propia. Incluye un timer flotante opcional.

## INSTALACIÓN

Clic derecho sobre `install.ps1` → **Ejecutar con PowerShell**.

También puedes abrir PowerShell y escribir:

```powershell
& "RUTA_COMPLETA_DE_install.ps1"
```

Por ejemplo:

```powershell
& "D:\Descargas\GlassInterpreter_v1.0.3\install.ps1"
```

Esto realizará las siguientes acciones:

- Creará un entorno virtual (`.venv`) dentro de la carpeta.
- Instalará LibreTranslate y las demás dependencias.
- Descargará los modelos de traducción `en → es` y `es → en`.
- Creará el acceso directo **Glass Interpreter** en el escritorio.

> **Nota:** Se necesita conexión a internet únicamente para descargar Python y los modelos de traducción (aprox. 300 MB). Este proceso puede tardar.

Los modelos se guardan en tu perfil de usuario, no en esta carpeta.

## USO

1. Activa los subtítulos de Windows (inglés) y de Chrome (español).
2. Abre **Glass Interpreter** desde el escritorio (o haz doble clic en `Reiniciar_Glass.vbs`).
3. Se abrirán dos ventanas: Glass y el timer flotante.

**Atajos:**

- `Esc` en la ventana de Glass: **cerrar Glass y detener LibreTranslate**.
- `Ctrl + rueda del ratón` en la ventana de Glass: **cambiar el tamaño del texto**.
- `Ctrl + clic izquierdo` en la ventana de Glass: **arrastrar y reordenar las ventanas**.
- `Esc` en el timer: **cerrar únicamente el timer**.
- `Espacio` en el timer: **silenciar el micrófono**.
- `Ctrl + rueda del ratón` en el timer: **cambiar el tamaño del texto**.

## ARCHIVOS ADICIONALES

- **`kill_python.vbs`**: incluido como herramienta adicional por si llegase a ser necesario.

  > ⚠️ **Precaución:** Este script detiene todos los procesos de Python que estén ejecutándose en la PC al momento de abrirlo, no solamente los de Glass Interpreter.

- **`Reiniciar_Glass.vbs`**: el acceso directo del escritorio ejecuta este archivo. Se asegura de cerrar Glass y el timer antes de volverlos a abrir.

## UBICACIÓN DE LA CARPETA

Esta carpeta puede estar en cualquier ubicación donde Windows permita escribir (excepto `Archivos de programa`).

Si la mueves, vuelve a ejecutar `install.ps1` para recrear el acceso directo del escritorio.
