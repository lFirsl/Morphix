# Morphix MSIX package

This folder is the MSIX payload root. Put all packaged binaries here:

- `Morphix.exe`
- `ContextMenu\MorphixContextMenu.dll`
- `Assets\*.png`
- `AppxManifest.xml`

## Build steps

1) Build the COM handler (this drops the DLL into `msix\ContextMenu\`):

```
msbuild .\ContextMenuWrl\MorphixContextMenu.vcxproj /p:Configuration=Release /p:Platform=x64
```

2) Copy your packaged `Morphix.exe` into `msix\`:

```
copy .\dist\Morphix.exe .\msix\Morphix.exe
```

3) Ensure placeholder assets exist under `msix\Assets`.

4) Pack & sign:

```
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22000.0\x64\makeappx.exe" pack /d C:\Users\flori\source\repos\morphix-prototype\msix /p C:\Users\flori\source\repos\morphix-prototype\Morphix.msix /nv
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22000.0\x64\signtool.exe" sign /fd SHA256 /a /f "C:\path\to\your.pfx" /p <YOUR_PASSWORD> "C:\Users\flori\source\repos\morphix-prototype\Morphix.msix"
```

5) Install the MSIX:

```
Add-AppxPackage C:\Users\flori\source\repos\morphix-prototype\Morphix.msix
```
