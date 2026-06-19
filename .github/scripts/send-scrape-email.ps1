$missingConfig = @(
  if ([string]::IsNullOrWhiteSpace($env:SMTP_HOST)) { "SMTP_HOST" }
  if ([string]::IsNullOrWhiteSpace($env:SMTP_PORT)) { "SMTP_PORT" }
  if ([string]::IsNullOrWhiteSpace($env:SMTP_USERNAME)) { "SMTP_USERNAME" }
  if ([string]::IsNullOrWhiteSpace($env:SMTP_PASSWORD)) { "SMTP_PASSWORD" }
  if ([string]::IsNullOrWhiteSpace($env:SCRAPE_MAIL_FROM)) { "SCRAPE_MAIL_FROM" }
  if ([string]::IsNullOrWhiteSpace($env:SCRAPE_MAIL_TO)) { "SCRAPE_MAIL_TO" }
)

if ($missingConfig.Count -gt 0) {
  "Email notification skipped: missing $($missingConfig -join ', ')."
  exit 0
}

$smtpPort = 0
if (-not [int]::TryParse($env:SMTP_PORT, [ref]$smtpPort)) {
  "Email notification skipped: SMTP_PORT is not a valid integer."
  exit 0
}

$logPath = Get-ChildItem -Path "logs" -Filter "scraper-*.log" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

$logText = if ($logPath) {
  (Get-Content -LiteralPath $logPath.FullName -Tail 300) -join [Environment]::NewLine
} else {
  "No scraper log file was created."
}

$summaryText = if ($logPath) {
  $allLogLines = @(Get-Content -LiteralPath $logPath.FullName)
  $summaryStart = [Array]::IndexOf($allLogLines, "=== Scraping Summary ===")
  if ($summaryStart -ge 0) {
    ($allLogLines[$summaryStart..($allLogLines.Count - 1)] | Where-Object {
      $_ -notmatch "^Scraper finished at "
    }) -join [Environment]::NewLine
  } else {
    "Scraping summary was not found in the log."
  }
} else {
  "Scraping summary was not found because no log file was created."
}

$zeroItemLines = @($summaryText -split [Environment]::NewLine | Where-Object {
  $_ -match "^\s+\S.*\s+0 items upserted,"
})
$alertText = if ($env:SCRAPE_STATUS -eq "success" -and $zeroItemLines.Count -gt 0) {
  "WARNING: successful scrape reported zero items for: $($zeroItemLines -join '; ')"
} else {
  "No scrape data warnings detected."
}
$subjectPrefix = if ($env:SCRAPE_STATUS -eq "success" -and $zeroItemLines.Count -gt 0) {
  "[Sal Kal] Scrape warning"
} else {
  "[Sal Kal] Scrape $($env:SCRAPE_STATUS)"
}
$subject = "$subjectPrefix - run $($env:GITHUB_RUN_NUMBER)"
$body = @"
Sal Kal scrape completed.

Status: $($env:SCRAPE_STATUS)
Repository: $($env:GITHUB_REPOSITORY)
Branch: $($env:GITHUB_REF_NAME)
Run: $($env:GITHUB_SERVER_URL)/$($env:GITHUB_REPOSITORY)/actions/runs/$($env:GITHUB_RUN_ID)
Force full: $($env:FORCE_FULL)
Schedule: $($env:SCHEDULE)
Alert: $alertText

Scraper summary:

$summaryText

Last scraper log lines:

$logText
"@

$message = [System.Net.Mail.MailMessage]::new()
$message.From = $env:SCRAPE_MAIL_FROM
foreach ($recipient in $env:SCRAPE_MAIL_TO.Split(",")) {
  if (-not [string]::IsNullOrWhiteSpace($recipient)) {
    $message.To.Add($recipient.Trim())
  }
}

if ($message.To.Count -eq 0) {
  "Email notification skipped: no valid recipients configured."
  exit 0
}

$message.Subject = $subject
$message.Body = $body

if ($logPath -and $env:SCRAPE_STATUS -ne "success") {
  $attachment = [System.Net.Mail.Attachment]::new($logPath.FullName)
  $message.Attachments.Add($attachment)
}

$client = [System.Net.Mail.SmtpClient]::new($env:SMTP_HOST, $smtpPort)
$client.EnableSsl = $true
$client.Credentials = [System.Net.NetworkCredential]::new(
  $env:SMTP_USERNAME,
  $env:SMTP_PASSWORD
)

try {
  $client.Send($message)
  "Email notification sent to $($env:SCRAPE_MAIL_TO)."
} finally {
  $message.Dispose()
  $client.Dispose()
}
