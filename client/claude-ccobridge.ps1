[CmdletBinding()]
param(
    [Alias("TeamKey")]
    [System.Security.SecureString]$ApiKey,

    [string]$Gateway = "http://127.0.0.1:4000",

    [string]$Model = "qwen-code",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ClaudeArguments
)

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    throw "Claude Code executable not found in PATH."
}

if (-not $ApiKey) {
    $ApiKey = Read-Host "API key" -AsSecureString
}

$keyPointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($ApiKey)
try {
    $apiKeyText = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($apiKeyText)) {
        throw "API key cannot be empty."
    }
    $env:ANTHROPIC_AUTH_TOKEN = $apiKeyText
}
finally {
    $apiKeyText = $null
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}

$env:ANTHROPIC_BASE_URL = $Gateway.TrimEnd("/")
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

& claude --model $Model @ClaudeArguments
exit $LASTEXITCODE
