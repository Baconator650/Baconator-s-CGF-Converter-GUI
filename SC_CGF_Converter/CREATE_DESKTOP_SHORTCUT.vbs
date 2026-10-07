Option Explicit
Dim fso, ws, baseDir, launcher, iconPath, desktop, shortcutPath, sc
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(baseDir, "START_SC_CGF_Converter.vbs")
iconPath = fso.BuildPath(fso.BuildPath(baseDir, "Assets"), "SC_CGF_Converter.ico")
desktop = ws.SpecialFolders("Desktop")
shortcutPath = fso.BuildPath(desktop, "SC CC - Star Citizen CGF Converter.lnk")
Set sc = ws.CreateShortcut(shortcutPath)
sc.TargetPath = ws.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"
sc.Arguments = Chr(34) & launcher & Chr(34)
sc.WorkingDirectory = baseDir
sc.Description = "SC CC - Star Citizen CGF Converter development host"
If fso.FileExists(iconPath) Then sc.IconLocation = iconPath & ",0"
sc.Save
MsgBox "Desktop shortcut created:" & vbCrLf & shortcutPath, 64, "SC CC"
