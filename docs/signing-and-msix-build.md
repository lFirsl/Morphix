# Signing And MSIX Build Guide

This document captures the end-to-end process for building, signing, and installing the Morphix MSIX package, including signing the PowerShell build script.

## Why this process is necessary

Windows 11 requires a signed MSIX package to install and register features like top-level context menu extensions. The signing step proves package integrity and publisher identity. For local development, a self-signed certificate is acceptable, but Windows must trust that certificate before the MSIX will install. The COM DLL is required because top-level context menu items are implemented through a COM `IExplorerCommand` handler, and the MSIX manifest must register that COM class. Packaging and signing ensure that Windows will load the COM server from the MSIX payload reliably.

## 1) Build the Morphix EXE (PyInstaller)

From the repo root:
```bash
py -3 -m PyInstaller --onefile --hidden-import=ffmpeg Morphix.py
```

Output:
- `dist\Morphix.exe`

## 2) Build the COM DLL (context menu handler)

```powershell
msbuild .\ContextMenuWrl\MorphixContextMenu.vcxproj /p:Configuration=Release /p:Platform=x64
```

Output:
- `msix\ContextMenu\MorphixContextMenu.dll`

## 3) Pack and sign the MSIX (scripted)

Use the build script:
```powershell
.\scripts\build_msix.ps1 -PfxPassword "<YOUR_PASSWORD>" -CopyExe
```

This script:
1. Builds the COM DLL.
2. Copies `dist\Morphix.exe` to `msix\Morphix.exe` (only when `-CopyExe` is provided).
3. Packs the MSIX with `makeappx.exe`.
4. Signs the MSIX with `signtool.exe`.

Output:
- `Morphix.msix` (repo root)

## 4) Install / Reinstall the MSIX

Remove the existing package:
```powershell
Get-AppxPackage -Name Morphix.Package | Remove-AppxPackage
```

Install the new package:
```powershell
Add-AppxPackage ".\Morphix.msix"
```

## 5) Signing the PowerShell build script

If your execution policy requires signed scripts, create a local code-signing cert and trust it.

Create a code-signing cert:
```powershell
$cert = New-SelfSignedCertificate -Type CodeSigning -Subject "CN=Morphix" -CertStoreLocation "Cert:\CurrentUser\My"
```

Export to .cer:
```powershell
Export-Certificate -Cert $cert -FilePath ".\scripts\MorphixCodeSigning.cer"
```

Trust the cert:
```powershell
Import-Certificate -FilePath ".\scripts\MorphixCodeSigning.cer" -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher"
Import-Certificate -FilePath ".\scripts\MorphixCodeSigning.cer" -CertStoreLocation "Cert:\CurrentUser\Root"
```

Sign the script:
```powershell
Set-AuthenticodeSignature -FilePath ".\scripts\build_msix.ps1" -Certificate $cert
```

Verify:
```powershell
Get-AuthenticodeSignature ".\scripts\build_msix.ps1"
```

## Notes

- `msix\AppxManifest.xml` `Publisher` must match the signing certificate subject.
- The context menu CLSID must match in:
  - `ContextMenuWrl\MorphixExplorerCommand.h`
  - `msix\AppxManifest.xml`
- If the context menu doesn't appear, rebuild the COM DLL and re-pack the MSIX.
