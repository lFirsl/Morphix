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
# AgEAAgEAAgEAAgEAAgEAMCEwCQYFKw4DAhoFAAQUA2LE3U6IBripBt2ypvwOr3J3
# aqmgggL4MIIC9DCCAdygAwIBAgIQGifc04oUAotJOYl6YGqQYjANBgkqhkiG9w0B
# AQsFADASMRAwDgYDVQQDDAdNb3JwaGl4MB4XDTI2MDYxMTIwMjIzNloXDTI3MDYx
# MTIwNDIzNlowEjEQMA4GA1UEAwwHTW9ycGhpeDCCASIwDQYJKoZIhvcNAQEBBQAD
# ggEPADCCAQoCggEBAMCBh+v2BYW/PmiVP/e3fks0+bGz3IBsEcH98wb9lUwjRh4T
# UcSvMxA3Skt63D1EdHJvmGAe6R+HcMkDEaJmClBVF/A6U3KFF7C8JerfQdELGYma
# EDtLPj48cYTKnUXSCmsMD0+VUyhvQZuAyL8EbRqjLz23CiTkv2QmfQ/1L9mEDUdB
# mtJnwh4pP2ZfAeOv86xzlcewenNnUH1TWBXjJ6yFPBYg0YI7SR6ZY5StsNG4Uc2s
# x9LanwuQLYDQaCyLafWA9px9J4sUowoFx+vjt7vtEKhWbHNvEiQRW3qboekbnw4O
# wQ5t2FWyaQ0VNjF5M4Nzjehv6sAH9RcIBPNijd0CAwEAAaNGMEQwDgYDVR0PAQH/
# BAQDAgeAMBMGA1UdJQQMMAoGCCsGAQUFBwMDMB0GA1UdDgQWBBQcqdS15rgSjH/v
# rjCk5+YNAClKpDANBgkqhkiG9w0BAQsFAAOCAQEAZD0koezXwt37K26z7uJ8Tlnp
# gq8qAPwhQK8ji9mfi8oh8M/DIn/1x9hlJACqvYPvB7RjF6zFb8cIQU/g7BTZrmvE
# iVH+zTGrHUhffem/ppdUGYVl7ijFKzGn4qMnJNTCnJA8VID6X7he6/DeUNV+ZPuP
# Q4rPfA9PSa0UXTXFHRYy8GOLaVNvAwsYFd6327YsgBY+VcrPAvM1dRrD7lKcsjC4
# Ss3r9xmn75y5QoL4MK+v8ZnixiXo/2NuoA7I+br85Zr7/+e328RLR7PQHFwZeQJj
# s8FFuAfYnClajxmV9Bl+Ka1Bzuxz1pfttS03J0wkrmk/ErGdt9FB994IoKdm+DGC
# AccwggHDAgEBMCYwEjEQMA4GA1UEAwwHTW9ycGhpeAIQGifc04oUAotJOYl6YGqQ
# YjAJBgUrDgMCGgUAoHgwGAYKKwYBBAGCNwIBDDEKMAigAoAAoQKAADAZBgkqhkiG
# 9w0BCQMxDAYKKwYBBAGCNwIBBDAcBgorBgEEAYI3AgELMQ4wDAYKKwYBBAGCNwIB
# FTAjBgkqhkiG9w0BCQQxFgQUkn0jxcv0keIQfCHyAxo0Y8w4aZEwDQYJKoZIhvcN
# AQEBBQAEggEAVKgjjST74iuzs/vY0cfCPHNPHE8r9ZCwdhzWZk4VOBRRcQNNkEuq
# Cja7acS2Vja40Ym1JacXE2gb38u3dnO3+/1OFeaKLOV6FzoyjN9uF0NUx08iAO9O
# v7SEak3p1DOijrIU97WpPnlypgwx6MJRaQxl5P3yTfXTHzNwcZyWVQKro4hUVnXM
# 9cF+vm2zXTjprPrWQFEg2bvrMtEMEYMoPmnybHtnW5FtTwsT7u29obStFRqgFtsd
# hOSqFT0UY4yOe+iHDQDVxcd93hRKGpeW6SXw3GDB8gvr5s/WPt2y2ANmJEQS0Cg6
# I9OEHCCBE7tEU5EXrgX2AUb+8zEfzOYt+Q==
# SIG # End signature block
