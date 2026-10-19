# Glass Interpreter v1.0.2 (versión semi portable)

Traduce en tiempo real los subtítulos de **Windows Live Captions** (inglés) y de **Chrome Live Caption** (español) al idioma contrario, en una ventana propia de cuatro paneles.



Novedades

* **LibreTranslate se inicia y se cierra de forma invisible junto con Glass.** Ya no hace falta una tarea programada ni scripts que cierren Python a la fuerza: al salir de Glass (Esc) se detiene solo el servicio que Glass inició, con todos sus procesos hijos.
* **Carpeta portable con rutas relativas.** Puede vivir en cualquier carpeta donde Windows permita escribir.
* **Instalador `install.ps1`:** crea un entorno virtual (`.venv`), instala las dependencias, descarga los modelos en→es y es→en y crea el acceso directo en el escritorio.
* **Timer flotante incluido** (`timer\_flotante.pyw`), opcional e independiente de la traducción.
* `Reiniciar\_Glass.vbs` reinicia todo limpio y abre Glass y el timer.

## Requisitos

* Windows 11 con Live Captions (Windows) y Live Caption (Chrome) activados.
* Python 3.12.
* Conexión a internet durante la instalación (aproximadamente 300 MB entre dependencias y modelos).

## Instalación

Ejecuta desde PowerShell:

```powershell
winget install --exact --id Python.Python.3.12
```

Cierra y vuelve a abrir PowerShell, descomprime el zip y, dentro de la carpeta (clic derecho en un espacio vacío de la carpeta > Abrir en Terminal):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\\install.ps1
```

Después abre **Glass Interpreter** desde el escritorio. Activa antes los subtítulos de Windows (inglés) y de Chrome (español). Esc cierra cada ventana.

## Notas

* Los modelos de traducción **no se incluyen** en este paquete: se descargan durante la instalación desde el índice de Argos Translate y se guardan en el perfil del usuario.
* LibreTranslate se instala como dependencia externa y se ejecuta como proceso aparte.
* Glass escucha solo en `127.0.0.1:5000`. Si ese puerto ya está ocupado por otro LibreTranslate, Glass lo reutiliza pero no lo cierra al salir.
* Si cierras Glass de forma forzada (por ejemplo, desde el Administrador de tareas), el servicio puede quedar activo; `Reiniciar\_Glass.vbs` lo limpia al volver a abrir.
* Se incluye kill\_python.vbs como extra por si llegase a ser necesario. Cuidado: Este detiene todos los procesos de Python en la PC, no sólo los de Glass.

## Cambios respecto a la versión anterior (0.1.0)

* La 0.1.0 dependía de una máquina virtual como segunda fuente de subtítulos; esta versión usa solo Windows (inglés) y Chrome (español).

## Licencia

GPL-3.0. Consulta `LICENSE`.

