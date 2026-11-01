Set WshShell = CreateObject("WScript.Shell")

' Ejecuta el comando de PowerShell para detener todos los procesos de python/pythonw de forma forzada (el 0 al final significa que se ejecuta de forma completamente oculta)
WshShell.Run "powershell -Command ""Stop-Process -Name 'python', 'pythonw' -Force""", 0, True