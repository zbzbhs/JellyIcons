Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
cfg = base & "\.venv\pyvenv.cfg"
py = ""
If fso.FileExists(cfg) Then
    Set f = fso.OpenTextFile(cfg, 1)
    Do Until f.AtEndOfStream
        line = f.ReadLine
        If LCase(Left(line, 5)) = "home " Then
            home = Trim(Mid(line, InStr(line, "=") + 1))
            If fso.FileExists(home & "\python.exe") Then py = home & "\python.exe"
        End If
    Loop
    f.Close
End If
If py = "" Then py = "python"
sh.Environment("PROCESS")("PYTHONPATH") = base & "\.venv\Lib\site-packages"
sh.CurrentDirectory = base
sh.Run """" & py & """ -X utf8 """ & base & "\run.py""", 0, False
