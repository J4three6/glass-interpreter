# Glass Interpreter

Esta versión, mucho más ligera, de Glass Interpreter sólo usa los subtítulos de Windows (en inglés) y los de Chrome (en español) y los traduce al idioma opuesto. Eliminando la necesidad de usar una máquina virtual. ¡Óptimo para correr en laptops sencillas!

La versión anterior, 0.1.0 , dependía de una máquina virtual como segunda fuente de subtítulos.

La preparación consiste en bajar el repositorio, ejecutar unas cuantas líneas en PowerShell, usar el instalador - `run_glass.ps1` y luego usar el icono del escritorio para ejecutar el programa (se cierra con la tecla Esc):

1. Instala las herramientas necesarias desde PowerShell:

   ```powershell
   winget install --exact --id Python.Python.3.12
   winget install --exact --id Git.Git
   ```

2. Cierra y vuelve a abrir PowerShell. Descarga el repositorio (reemplaza `OWNER/REPO` con su URL real):

   ```powershell
   git clone https://github.com/J4three6/glass-interpreter.git "$env:USERPROFILE\GlassInterpreter"
   Set-Location "$env:USERPROFILE\GlassInterpreter"
   ```

3. Instala LibreTranslate, la interfaz y los dos modelos Argos; se creará el acceso directo con el icono oficial:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install.ps1
   ```

La primera instalación descarga varios cientos de MB de dependencias y modelos y puede tardar. Después, abre **Glass Interpreter** desde el acceso directo del escritorio. No ejecutes `Glass_Interpreter.pyw` directamente: el acceso directo inicia el servidor local oculto, arranca la interfaz y al salir cierra únicamente el servidor iniciado por esa sesión.

Activa los subtítulos en vivo de Windows (en inglés) y Chrome (en español) antes de abrir Glass. Usa la tecla de **Escape** para cerrar la interfaz.

## Archivos

- `Glass_Interpreter.pyw`: interfaz de cuatro paneles.
- `install.ps1`: crea un entorno Python local al repositorio, instala dependencias y modelos en `%LOCALAPPDATA%`, y crea el acceso directo.
- `run_glass.ps1`: inicia LibreTranslate en un puerto loopback libre y lo detiene al cerrar Glass.
- `requirements.txt`: dependencias Python con versiones validadas.

## Licencias y publicación

El código no incluye todavía una licencia del proyecto: hasta que se elija una, no se concede permiso de reutilización. El modelo Argos inglés-español descarga su paquete desde el índice Argos; el paquete no declara explícitamente una licencia del modelo ni los derechos de redistribución de todos sus corpus. No subas modelos ni un instalador autocontenido hasta resolverlo. Consulta `PUBLISHING.md` y `THIRD_PARTY_NOTICES.md`.
