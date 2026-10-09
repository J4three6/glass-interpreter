# Glass Interpreter

Glass Interpreter muestra y traduce dos flujos de Windows 11 Subtítulos en vivo en una ventana de cuatro paneles.

- En el Host, captura subtítulos en inglés y los traduce al español.
- En la VM, captura subtítulos en español y envía el texto al Host por la red local; la VM no traduce.
- LibreTranslate y los modelos inglés/español se ejecutan en el Host. La primera instalación requiere internet para descargar Python, las dependencias y los modelos.
- El Host muestra el texto original y la traducción de ambos equipos. Los subtítulos no se envían a servicios externos.
- `Ctrl` + rueda del ratón cambia el tamaño del texto. `Esc` cierra el visor. El clic derecho no lo cierra.

## Instalación

1. En el Host, abre `GlassInterpreter-Setup.exe` y elige una carpeta de instalación.
2. El asistente detecta la IPv4 del Host y genera dentro de `VM` un instalador configurado para esa dirección.
3. Copia ese instalador a la VM, ejecútalo dentro de la VM y sigue los pasos.
4. Abre Windows 11 Subtítulos en vivo en ambos equipos: inglés en el Host y español en la VM.
5. Inicia cada parte con su acceso directo del Escritorio.

Si Windows muestra una solicitud del firewall al iniciar el Host, permite el acceso en la red privada a la que se conecta la VM.

## Compilar el instalador

Requisitos para compilar: Windows x64 y .NET 10 SDK.

```powershell
dotnet publish GlassInstaller.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o publish
```

El ejecutable principal se puede publicar como activo de una Release de GitHub. Cada instalación Host genera el instalador VM correspondiente a su propia red; no publiques una copia VM con una IP personal.

## Privacidad y componentes de terceros

La instalación usa Internet para descargar Python, LibreTranslate y modelos de traducción. En funcionamiento, el Host traduce localmente y recibe de la VM el texto de subtítulos a través de la red local. Consulta las licencias de Python, LibreTranslate, Argos Translate y los modelos de idiomas antes de redistribuirlos por separado.

## Licencias

- El código de Glass Interpreter está bajo MIT; ver `LICENSE`.
- El icono `Glass.ico` se dedica al dominio público mediante CC0 1.0; ver `ICON-LICENSE.md`.
- Las licencias de componentes de terceros son independientes y se mantienen con sus respectivos proyectos.
