# Baconator-s-CGF-Converter-GUI
GUI interface for Markemp/Heffay's CGF-Converter.

Windows GUI for Star Citizen asset conversion: recursive batch export, preserved folder structure, named USDA/legacy DAE presets, and an optional decoded DBA animation exporter. Requires an external CryEngine converter.

You will need download the CGF-Converter seperately: https://github.com/Markemp/Cryengine-Converter


SC CGF Converter
A Windows desktop utility for converting extracted Star Citizen assets with an external CryEngine converter. It provides recursive folder batches, preserved output structure, named export presets, tooltips and in-app Help. An optional native animation processor decodes supported DBA tracks using an exported CGF skeleton's original coordinate convention.
The external `cgf-converter.exe` is not included or modified. Game assets, private settings, local paths, logs, exported scenes and historical experiment reports are not included.
Requirements
Windows with Python 3.10 or newer and Tkinter.
An independently obtained compatible `cgf-converter.exe`.
Asset files you are authorized to access and use.
No third-party Python dependencies are needed for the application or included checks.
Start
Download/extract the project, or clone it into a local folder.
Double-click `START_SC_CGF_Converter_0_3_11.vbs` or `START_SC_CGF_Converter.vbs`.
The title must show version 0.3.11. The `.pyw` launcher uses the same implementation as `.py`.
Browse to `cgf-converter.exe`, then click Check Converter.
Optionally click Create Desktop Shortcut to point a shortcut at this installation.
If windowed launching fails, use `RUN_SC_CGF_Converter_DEBUG_CONSOLE.bat`. Local settings and logs are created in the application folder when it runs.
Normal batch export
Select StarCitizen and SC_Normal_Batch_USDA. Leave Processor at `<None>`.
Click Input Folder and select the input root.
Set Game/Data root to the extracted `Data` folder containing `Objects` and `Animations`.
Choose an Output folder.
Keep Batch folder processing, Preserve input folder structure and Collect native outputs on; these default to on.
Click EXPORT.
`Input/Ships/Example/gear.chr` exports under `Output/Ships/Example`. Input-root files export directly under Output. Disabling recursive processing limits the scan to the chosen top-level folder. Disabling preserved structure flattens output; duplicate stems from different source folders are rejected. A file input processes one asset.
When the selected converter supports an output switch, each asset is sent to its mapped destination. Otherwise it writes beside the source, and collection copies generated exports into the mapped output folder. Source-side exports remain. Output inside Input is excluded from scanning; directory symlinks are not traversed.
Presets
Preset	Included source types	Animation behavior
SC_Normal_Batch_USDA	CGF, CGA, CHR, SKIN	Stock animation requested for CHR/CGA
.skin/chr (landing gear, armor, weapons)	SKIN, CHR	Existing stock `-anim` preset behavior
Animated Files (.cga, .skin, .chr)	CGA, SKIN, CHR	Stock animation for CGA/CHR; SKIN supplies skinned geometry
All Star Citizen Files	CGF, CGA, SKIN, CHR, ANIM, DBA	Supported inputs only; converter limitations remain
SC_Static_USDA	Supported asset inputs	No requested stock animation
DAE (legacy)	Supported asset inputs	Existing stock DAE/animation behavior
“All” does not include textures, XML or unsupported game formats. Presets do not add format decoding support. Diagnostic presets are hidden unless Show diagnostics is enabled.
Corrected native landing-gear animation
Use [STABLE] SC Native Animation Export v0.3.7 for the corrected native DBA workflow. The processor version differs from the host version; v0.3.7 contains the confirmed vector/quaternion and USD matrix fixes. Ordinary stock export with Processor `<None>` does not use this processor.
First export the original CHR skeletons using the stock converter.
Set Input to the corresponding DBA, or to a folder of DBAs.
Put matching original CHR USDA skeletons in the corresponding Output folder/subfolders.
Select SC Native Animation Export and click Export Animation Only.
Find clean `*_anim_NATIVE.usda` files and `*_ApplyToExistingRig.ms` loaders in `NATIVE_ANIMATION` under each mapped output folder.
In 3ds Max, import the original CHR/SKIN rig, select the intended rig root and run the appropriate `.ms` loader. Exact joint names and the original unscaled/unrotated rig are required. One clip is applied at a time.
Original CGF joint axes and bind/rest matrices are preserved. No diagnostic marker meshes or legacy HTR pivot corrections are added. Validation is limited to supplied Hornet front/left clips. Matching skeletons are required; unsupported formats, ambiguous rigs or unresolved tracks can be rejected or skipped. This public package contains no sample game data.
Help and diagnostics
Hover over buttons for tooltips. Help describes setup, folders, presets and animation. Diagnostics are hidden by default; enabling them reveals command preview, listener, optional reference paths, extra arguments and dry run. Logs are written even when hidden. Turning diagnostics off clears extra arguments/format overrides and disables dry run.
Checks
Run `RUN_SELF_TEST.bat`, or `python Tools/SELF_TEST.py`. These checks do not run the external Windows converter or verify live skinned playback. See AI-assisted development disclosure for validation limits and the as-is disclaimer.
Uploading to GitHub
Extract this public package and upload its contents as the repository root. Do not upload a configured private installation or copy generated settings, logs, game assets or exports into the repository. The included `.gitignore` covers common local output and source-asset files. `GITHUB_DESCRIPTION.txt` contains a short repository description.
No repository license is selected in this package. Choose one appropriate for code you own before granting public reuse permissions; third-party software and game-asset rights are separate.
