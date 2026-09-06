# Sends all supported files in a folder to the /upload endpoint of script1_api_server.
# Usage:
#   .\scripts\send_files.ps1 -Folder "C:\path\to\your\excel\folder"
#   .\scripts\send_files.ps1 -Folder "C:\path\to\folder" -Filter "*.xlsx" -Uri "http://127.0.0.1:5000/upload"
#   .\scripts\send_files.ps1 -Folder "C:\path\to\folder" -Filter "*.xlsx", "*.docx", "*.pdf"

param(
    [Parameter(Mandatory = $true)]
    [string]$Folder,

    [string[]]$Filter = @("*.xlsx", "*.xls", "*.csv", "*.doc", "*.docx", "*.txt", "*.pdf", "*.rtf"),

    [string]$Uri = "http://127.0.0.1:6666/upload"
)

# Map file extensions to the MIME types the server expects (see config/settings.py).
$MimeTypes = @{
    ".xls"  = "application/vnd.ms-excel"
    ".xlsx" = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ".csv"  = "text/csv"
    ".doc"  = "application/msword"
    ".docx" = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ".rtf"  = "application/rtf"
    ".txt"  = "text/plain"
    ".pdf"  = "application/pdf"
}

# -Include only works reliably with a wildcarded -Path, so glob directly under $Folder.
$files = Get-ChildItem -Path (Join-Path $Folder "*") -Include $Filter -File
if ($files.Count -eq 0) {
    Write-Warning "No files matching '$($Filter -join ', ')' found in '$Folder'."
    exit 1
}

Write-Host "Found $($files.Count) file(s) to send:"
$files | ForEach-Object { Write-Host "  - $($_.Name)" }

$payloadFiles = $files | ForEach-Object {
    $extension = $_.Extension.ToLower()
    $mimeType = $MimeTypes[$extension]
    if (-not $mimeType) {
        Write-Warning "Skipping '$($_.Name)': unsupported extension '$extension'."
        return
    }
    @{
        filename  = $_.Name
        mime_type = $mimeType
        content   = [Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName))
    }
}

$payload = @{ files = @($payloadFiles) }
$json = $payload | ConvertTo-Json -Depth 5

Write-Host "`nSending request to $Uri ..."
try {
    $response = Invoke-RestMethod -Uri $Uri -Method Post -Body $json -ContentType "application/json"
    Write-Host "`nResponse:"
    $response | ConvertTo-Json -Depth 5
}
catch {
    Write-Error "Request failed: $_"
}
