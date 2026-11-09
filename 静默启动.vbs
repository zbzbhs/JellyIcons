Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
py = base & "\.venv\Scripts\python.exe"
If Not fso.FileExists(py) Then py = "python"
sh.CurrentDirectory = base
sh.Run """" & py & """ -X utf8 """ & base & "\run.py""", 0, False
