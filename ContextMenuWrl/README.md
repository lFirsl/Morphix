# Morphix WRL context menu handler

This is a barebones WRL COM DLL implementing `IExplorerCommand` for the Windows 11
top‑level context menu.

## Build

Open in Visual Studio and build x64, or run:

```
msbuild .\ContextMenuWrl\MorphixContextMenu.vcxproj /p:Configuration=Release /p:Platform=x64
```

Output DLL:

```
ContextMenuWrl\x64\Release\MorphixContextMenu.dll
```
