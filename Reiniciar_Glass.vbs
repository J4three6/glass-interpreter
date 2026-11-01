Option Explicit

Dim WshShell, WMI, Fso, Proceso
Dim Comando, Carpeta, PythonW, Timer, Glass

Set WshShell = CreateObject("WScript.Shell")
Set WMI = GetObject("winmgmts:\\.\root\cimv2")
Set Fso = CreateObject("Scripting.FileSystemObject")

' ==========================================
' RUTAS (relativas a la carpeta de este script)
' ==========================================

Carpeta = Fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = Carpeta

' Usa el entorno virtual creado por install.ps1; si no existe, el Python del PATH
PythonW = Carpeta & "\.venv\Scripts\pythonw.exe"
If Not Fso.FileExists(PythonW) Then PythonW = "pythonw.exe"

Timer = Carpeta & "\timer_flotante.pyw"
Glass = Carpeta & "\Glass_Interpreter.pyw"

' ==========================================
' 1. DETENER GLASS, TIMER Y LIBRETRANSLATE (por si quedo algo)
' ==========================================

On Error Resume Next

For Each Proceso In WMI.ExecQuery("SELECT * FROM Win32_Process")

    Comando = LCase("" & Proceso.CommandLine)

    If InStr(Comando, LCase(Timer)) > 0 _
    Or InStr(Comando, LCase(Glass)) > 0 _
    Or InStr(Comando, "libretranslate.exe") > 0 Then

        Proceso.Terminate

    End If

Next

On Error GoTo 0

' ==========================================
' 2. ESPERAR 1 SEGUNDO
' ==========================================

WScript.Sleep 1000

' ==========================================
' 3. INICIAR GLASS (el arranca LibreTranslate)
' ==========================================

WshShell.Run """" & PythonW & """ """ & Glass & """", 0, False

' ==========================================
' 4. INICIAR TIMER FLOTANTE
' ==========================================

WshShell.Run """" & PythonW & """ """ & Timer & """", 0, False

Set Fso = Nothing
Set WMI = Nothing
Set WshShell = Nothing