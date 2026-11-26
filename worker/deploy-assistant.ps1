# Deploys the Mind Freedom website assistant to Cloudflare Workers (free plan) and stores the
# API key as an encrypted secret. The key is read from your file and sent straight to Cloudflare;
# it is never printed, and it never goes into the website.
#
# Run in PowerShell from this folder:
#   .\deploy-assistant.ps1 -KeyFile "D:\AI CONSULTANCY\API Key\mindfreedom.co.tz webiste.txt"

param(
  [Parameter(Mandatory = $true)][string]$KeyFile
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:npm_config_cache = "D:\npm-cache"          # keep npm downloads off drive C:
$env:WRANGLER_SEND_METRICS = "false"

if (-not (Test-Path -LiteralPath $KeyFile)) { throw "Key file not found: $KeyFile" }

# 1. sign in to Cloudflare (opens the browser once; skipped if already signed in)
npx --yes wrangler@4 whoami 2>$null | Out-String | Select-String -Quiet "associated with the email" | ForEach-Object { $signedIn = $_ }
if (-not $signedIn) { npx --yes wrangler@4 login }

# 2. publish the Worker
npx --yes wrangler@4 deploy

# 3. store the key as the encrypted secret AI_API_KEY (taken from the last non-empty line of the file)
$key = (Get-Content -LiteralPath $KeyFile | Where-Object { $_.Trim() } | Select-Object -Last 1).Trim()
if ($key -match '[:=]\s*(\S+)$') { $key = $Matches[1] }   # "API key: xxxx" -> "xxxx"
$key | npx --yes wrangler@4 secret put AI_API_KEY
Remove-Variable key
Write-Host "Done. The assistant is live at the workers.dev address shown above."
