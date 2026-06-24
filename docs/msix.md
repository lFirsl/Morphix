# MSIX Packaging

## Build the COM DLL

```powershell
msbuild .\ContextMenuWrl\MorphixContextMenu.vcxproj /p:Configuration=Release /p:Platform=x64
```

Output lands in `msix\ContextMenu\`.

## Build the EXEs

```bash
conda run -n morphix python -m PyInstaller Morphix_CLI.spec
conda run -n morphix python -m PyInstaller Morphix_UI.spec
```

Copy into MSIX payload:

```powershell
copy .\dist\Morphix_CLI.exe .\msix\Morphix_CLI.exe
copy .\dist\Morphix_UI.exe .\msix\Morphix_UI.exe
```

## Pack & Sign

Requires Windows SDK (10.0.26100.0 or later):

```cmd
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\makeappx.exe" pack /d msix /p Morphix.msix /nv
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe" sign /fd SHA256 /a /f Morphix.pfx /p <YOUR_PASSWORD> Morphix.msix
```

## Install

```powershell
Get-AppxPackage -Name Morphix.Package | Remove-AppxPackage
Add-AppxPackage Morphix.msix
```

## Self-Signed Certificate

Create:

```powershell
New-SelfSignedCertificate -Type Custom -Subject "CN=Morphix" -KeyUsage DigitalSignature -FriendlyName "MorphixSignCert" -CertStoreLocation "Cert:\CurrentUser\My" -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
```

Export to PFX:

```powershell
$password = ConvertTo-SecureString -String <YOUR_PASSWORD> -Force -AsPlainText
Export-PfxCertificate -cert "Cert:\CurrentUser\My\<CERT_THUMBPRINT>" -FilePath Morphix.pfx -Password $password
```

Trust the cert (required for local install):

```powershell
Export-Certificate -Cert "Cert:\CurrentUser\My\<CERT_THUMBPRINT>" -FilePath Morphix.cer
Import-Certificate -FilePath Morphix.cer -CertStoreLocation "Cert:\LocalMachine\Root"
```

Note: `Publisher="CN=Morphix"` in `msix/AppxManifest.xml` must match the cert subject.
