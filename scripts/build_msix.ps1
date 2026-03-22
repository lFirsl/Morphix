param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PfxPath = "$RepoRoot\Morphix.pfx",
    [string]$PfxPassword = "",
    [string]$WindowsKitBin = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64",
    [switch]$Install,
    [switch]$CopyExe
)

# Paths for MSIX payload and outputs.
$msixDir = Join-Path $RepoRoot "msix"
$msixPath = Join-Path $RepoRoot "Morphix.msix"
$exePath = Join-Path $RepoRoot "dist\Morphix.exe"
$uiExePath = Join-Path $RepoRoot "dist\Morphix_UI.exe"

# Try to find MSBuild (either on PATH or via Visual Studio's vswhere).
function Resolve-MSBuild {
    # Prefer MSBuild on PATH if available.
    $msbuild = Get-Command msbuild -ErrorAction SilentlyContinue
    if ($msbuild) { return $msbuild.Source }

    # Fallback: use vswhere to locate MSBuild from Visual Studio installation.
    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $path = & $vswhere -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe
        if ($path) { return $path }
    }

    return $null
}

# Ensure the Morphix EXE exists before packaging.
if ($CopyExe -and -not (Test-Path $exePath)) {
    throw "Morphix.exe not found at $exePath. Build it first or use -BuildExe."
}

Write-Host "Building COM DLL..."
$msbuildPath = Resolve-MSBuild
if (-not $msbuildPath) {
    throw "MSBuild not found. Install Visual Studio Build Tools or add MSBuild to PATH."
}
# Build the COM context menu handler (Release x64).
& $msbuildPath (Join-Path $RepoRoot "ContextMenuWrl\MorphixContextMenu.vcxproj") /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw "COM DLL build failed." }

if ($CopyExe) {
    Write-Host "Copying Morphix.exe into MSIX payload..."
    # Put the EXE inside the MSIX payload directory.
    Copy-Item $exePath (Join-Path $msixDir "Morphix.exe") -Force
    if (Test-Path $uiExePath) {
        Write-Host "Copying Morphix_UI.exe into MSIX payload..."
        Copy-Item $uiExePath (Join-Path $msixDir "Morphix_UI.exe") -Force
    }
}

Write-Host "Packing MSIX..."
# Package everything in msix/ into a single .msix file.
# /d = content directory, /p = output package path, /nv = disable validation of file extensions.
& (Join-Path $WindowsKitBin "makeappx.exe") pack /d $msixDir /p $msixPath /nv
if ($LASTEXITCODE -ne 0) { throw "makeappx failed." }

if (-not (Test-Path $PfxPath)) {
    throw "PFX not found at $PfxPath."
}
if ([string]::IsNullOrWhiteSpace($PfxPassword)) {
    throw "PfxPassword is required. Provide -PfxPassword <password>."
}

Write-Host "Signing MSIX..."
# Sign the MSIX so Windows will trust/install it.
# /fd = file digest algorithm, /a = select best signing cert from the PFX, /f = PFX path, /p = PFX password.
& (Join-Path $WindowsKitBin "signtool.exe") sign /fd SHA256 /a /f $PfxPath /p $PfxPassword $msixPath
if ($LASTEXITCODE -ne 0) { throw "signtool failed." }

Write-Host "Done: $msixPath"

if ($Install) {
    Write-Host "Reinstalling package..."
    $packageName = "Morphix.Package"
    $existing = Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue
    if ($existing) {
        Remove-AppxPackage -Package $existing.PackageFullName
    }
    Add-AppxPackage $msixPath
}

# SIG # Begin signature block
# MIIFVQYJKoZIhvcNAQcCoIIFRjCCBUICAQExCzAJBgUrDgMCGgUAMGkGCisGAQQB
# gjcCAQSgWzBZMDQGCisGAQQBgjcCAR4wJgIDAQAABBAfzDtgWUsITrck0sYpfvNR
# AgEAAgEAAgEAAgEAAgEAMCEwCQYFKw4DAhoFAAQU2LmrnSNWm52f6Zy237RfLJav
# qBGgggL4MIIC9DCCAdygAwIBAgIQElX+n8N6PZROFhAYVYbpZDANBgkqhkiG9w0B
# AQsFADASMRAwDgYDVQQDDAdNb3JwaGl4MB4XDTI2MDMwMTEzMjcyM1oXDTI3MDMw
# MTEzNDcyM1owEjEQMA4GA1UEAwwHTW9ycGhpeDCCASIwDQYJKoZIhvcNAQEBBQAD
# ggEPADCCAQoCggEBAK8OlLytGa1OIAKaYc9zVQ6JdS29mEJRDvY06dCy5Ue7HOma
# /MYp6+sbF/puwf/hlEox/iI/S8UXC6toI/kfQZF+Jy/wF4kaMbIUMkSc0p1/vYKv
# sgsaJkJrwkHf8rslHPF+yHS8YaKuNNrIRfLMeSQbcD4qM2VY5utDc1kDI9xXaH4V
# aoezpw6zEQa3MSlIWouNwvmJZUg+N/69QYvnj2UAFzZ08Pm9ra5kVJispIyIVjiW
# 7KLC4vAwOk/8PrX5mS2vMjZ4qzMYQ2ydl8b5UbgRljoiAGesegy/j+zw/5dRi0o0
# ggqbXp8a2k1ktr7bSBcETUVe/lZW4fuYjjTc9QkCAwEAAaNGMEQwDgYDVR0PAQH/
# BAQDAgeAMBMGA1UdJQQMMAoGCCsGAQUFBwMDMB0GA1UdDgQWBBQzROQY/BsmUPEE
# 3k7CuzbgiLTk0DANBgkqhkiG9w0BAQsFAAOCAQEAEnG2BOP6FlKhVdAKocpsUmto
# Usxu5m5fc5dP+m0yMR+1ZvNmm7IhHYPbc2IBezpezTz4mFKTwhf8CAbqXEmK8O9V
# oHyed4ulYSRyaZzUc3N5b7h9DzQpN/FhZA5O8fiespjxOHEPK4uOorutUDrfh4Lh
# eS+PXbbBvF8nYzrYi/EMVetMohVJ4Z6WrHsqV3c9gyaaqAlUbnWX2+wPKpzKNwCk
# VtU8IMg0WSn60zpQt9UyOyncCJyur0WYvX189dXaci2tTnW+68VrpLL1F9VmP4lF
# joHPqQaswLT5uf1wSd+ZLVwqx3k8XiUDQF9z3lXIiYxW93Bv/A9vTsf9SMhHAjGC
# AccwggHDAgEBMCYwEjEQMA4GA1UEAwwHTW9ycGhpeAIQElX+n8N6PZROFhAYVYbp
# ZDAJBgUrDgMCGgUAoHgwGAYKKwYBBAGCNwIBDDEKMAigAoAAoQKAADAZBgkqhkiG
# 9w0BCQMxDAYKKwYBBAGCNwIBBDAcBgorBgEEAYI3AgELMQ4wDAYKKwYBBAGCNwIB
# FTAjBgkqhkiG9w0BCQQxFgQUCKugrFmwfGgnaC3PEVzoyp0UyzIwDQYJKoZIhvcN
# AQEBBQAEggEAL9q6btzFrpayW9LfO5g6mSEO7WiEBOCdU6vt8PS4FHQSWEgp01NP
# YselSeIAMPdZFr8j9xbR49thcN3Xocsf0YJlJFHpySXmUfSsPIvDwJAAf2TfG/5y
# t6Q1DCUJdwuaIardJ4APUPhtu8FNjXa2ShyZnvP5topJoxI1exDfkPSF+R7Wfici
# ArEAdGR0y0PqEuSoMtHC+OOGhqrrwt/rlFhCE3O2K6TCScD6Tpt0KLEY8V/AeBPs
# js/nuNUyH4p4a10F+FxHHu5CdbV6L/EQ6F6f4NLTOrrCvi7k2ARj9mWUWIJEWH+O
# Jj+RBoQkzD4dCBHwGhe6HR/lczghV6qToQ==
# SIG # End signature block
