<#
.SYNOPSIS
    Genera las llaves RSA (RS256) para JWT en backend/secrets.

.DESCRIPTION
    Crea jwt_private.pem y jwt_public.pem necesarios para firmar tokens.
    Delega en scripts/generar_llaves_jwt.py (librería "cryptography" del venv).

.EXAMPLE
    .\scripts\generar_llaves_jwt.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$backend = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python (Join-Path $backend "scripts\generar_llaves_jwt.py")
if ($LASTEXITCODE -ne 0) { throw "Fallo al generar las llaves." }