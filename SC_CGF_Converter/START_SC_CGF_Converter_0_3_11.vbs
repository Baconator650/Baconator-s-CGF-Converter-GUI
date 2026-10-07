Option Explicit

Dim fso, ws, shellApp, baseDir, scriptPath, pythonExe, cmd, localPythonRoot, folder, subFolder
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
Set shellApp = CreateObject("Shell.Application")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(baseDir, "SC_CGF_Converter.pyw")

If Not fso.FileExists(scriptPath) Then
    MsgBox "SC_CGF_Converter.pyw was not found:" & vbCrLf & scriptPath, 16, "SC CC"
    WScript.Quit 1
End If

pythonExe = ""

' 1) Prefer the standard Python windowed launcher when installed.
If fso.FileExists(ws.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe") Then
    pythonExe = ws.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
End If

' 2) Search common per-user python.org installs for pythonw.exe.
If pythonExe = "" Then
    localPythonRoot = ws.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(localPythonRoot) Then
        Set folder = fso.GetFolder(localPythonRoot)
        For Each subFolder In folder.SubFolders
            If fso.FileExists(fso.BuildPath(subFolder.Path, "pythonw.exe")) Then
                pythonExe = fso.BuildPath(subFolder.Path, "pythonw.exe")
            End If
        Next
    End If
End If

' 3) Search PATH for pythonw.exe without showing a console.
If pythonExe = "" Then
    Dim tmpFile, rc, line, ts
    tmpFile = fso.BuildPath(ws.ExpandEnvironmentStrings("%TEMP%"), "sc_cc_pythonw_path.txt")
    On Error Resume Next
    fso.DeleteFile tmpFile, True
    On Error GoTo 0
    cmd = ws.ExpandEnvironmentStrings("%COMSPEC%") & " /d /c where pythonw.exe > """ & tmpFile & """ 2>nul"
    rc = ws.Run(cmd, 0, True)
    If fso.FileExists(tmpFile) Then
        Set ts = fso.OpenTextFile(tmpFile, 1, False)
        If Not ts.AtEndOfStream Then
            line = Trim(ts.ReadLine)
            If line <> "" And fso.FileExists(line) Then pythonExe = line
        End If
        ts.Close
        On Error Resume Next
        fso.DeleteFile tmpFile, True
        On Error GoTo 0
    End If
End If

' 4) Last-resort fallback: use python.exe, but launch it hidden.
If pythonExe = "" Then
    Dim tmpFile2, rc2, line2, ts2
    tmpFile2 = fso.BuildPath(ws.ExpandEnvironmentStrings("%TEMP%"), "sc_cc_python_path.txt")
    On Error Resume Next
    fso.DeleteFile tmpFile2, True
    On Error GoTo 0
    cmd = ws.ExpandEnvironmentStrings("%COMSPEC%") & " /d /c where python.exe > """ & tmpFile2 & """ 2>nul"
    rc2 = ws.Run(cmd, 0, True)
    If fso.FileExists(tmpFile2) Then
        Set ts2 = fso.OpenTextFile(tmpFile2, 1, False)
        If Not ts2.AtEndOfStream Then
            line2 = Trim(ts2.ReadLine)
            If line2 <> "" And fso.FileExists(line2) Then pythonExe = line2
        End If
        ts2.Close
        On Error Resume Next
        fso.DeleteFile tmpFile2, True
        On Error GoTo 0
    End If
End If

If pythonExe = "" Then
    MsgBox "Python could not be found." & vbCrLf & vbCrLf & _
           "SC CC requires Python 3 for this development build." & vbCrLf & _
           "Install Python or use RUN_SC_CGF_Converter_DEBUG_CONSOLE.bat to diagnose the installation.", _
           16, "SC CC"
    WScript.Quit 2
End If

' Explicitly invoke Python/PythonW. Do NOT rely on the Windows .pyw file association.
cmd = """" & pythonExe & """ """ & scriptPath & """"
ws.Run cmd, 0, False
