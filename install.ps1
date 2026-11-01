# Glass Interpreter - instalacion (una sola vez)
# Uso:  Set-ExecutionPolicy -Scope Process Bypass ; .\install.ps1
$ErrorActionPreference = "Stop"
$Carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Carpeta

function Paso($texto) { Write-Host ""; Write-Host "== $texto" -ForegroundColor Cyan }
function Ejecutar($bloque) {
    & $bloque
    if ($LASTEXITCODE -ne 0) { throw "El comando fallo (codigo $LASTEXITCODE)." }
}

# 1. Buscar Python 3.12 ------------------------------------------------------
Paso "Buscando Python 3.12"
$candidatos = @(
    @{ exe = "py";     pre = @("-3.12") },
    @{ exe = "python"; pre = @() }
)
$py = $null
foreach ($c in $candidatos) {
    try {
        $version = & $c.exe @($c.pre) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.12") { $py = $c; break }
    } catch { }
}
if (-not $py) {
    Write-Host "No se encontro Python 3.12. Instalalo con:" -ForegroundColor Yellow
    Write-Host "    winget install --exact --id Python.Python.3.12"
    Write-Host "Cierra y vuelve a abrir PowerShell y ejecuta install.ps1 otra vez."
    exit 1
}

# 2. Entorno virtual y dependencias -----------------------------------------
Paso "Creando entorno virtual (.venv)"
Ejecutar { & $py.exe @($py.pre) -m venv .venv }
$vpy = Join-Path $Carpeta ".venv\Scripts\python.exe"

Paso "Instalando dependencias (LibreTranslate incluido; puede tardar varios minutos)"
Ejecutar { & $vpy -m pip install --upgrade pip }
Ejecutar { & $vpy -m pip install -r requirements.txt }

# 3. Modelos de traduccion en->es y es->en ----------------------------------
Paso "Descargando modelos Argos (en->es y es->en)"
$codigo = @'
import argostranslate.package as p
p.update_package_index()
disponibles = p.get_available_packages()
for a, b in (("en", "es"), ("es", "en")):
    pk = next((x for x in disponibles if x.from_code == a and x.to_code == b), None)
    if pk is None:
        raise SystemExit("No se encontro el modelo %s->%s" % (a, b))
    p.install_from_path(pk.download())
    print("Modelo instalado: %s -> %s" % (a, b))
'@
$codigo | & $vpy -
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar los modelos." }

# 4. Acceso directo en el escritorio ----------------------------------------
Paso "Creando acceso directo"
$vbs = Join-Path $Carpeta "Reiniciar_Glass.vbs"
$escritorio = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell
$acceso = $ws.CreateShortcut((Join-Path $escritorio "Glass Interpreter.lnk"))
$acceso.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
$acceso.Arguments = "`"$vbs`""
$acceso.WorkingDirectory = $Carpeta
$icono = Join-Path $Carpeta "Glass.ico"
if (Test-Path $icono) { $acceso.IconLocation = $icono }
$acceso.Save()

Write-Host ""
Write-Host "Listo. Abre 'Glass Interpreter' desde el escritorio." -ForegroundColor Green
Write-Host "Activa antes los subtitulos en vivo de Windows (ingles) y de Chrome (espanol)."
