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

$maxEmbeddedLogChars = 60000
$fullLogText = if ($logPath) {
  $reader = [System.IO.StreamReader]::new($logPath.FullName)
  try {
    $buffer = [char[]]::new($maxEmbeddedLogChars + 1)
    $charsRead = $reader.ReadBlock($buffer, 0, $buffer.Length)
    $text = [string]::new($buffer, 0, [Math]::Min($charsRead, $maxEmbeddedLogChars))
    if ($charsRead -gt $maxEmbeddedLogChars) {
      $text + "`n`n--- Embedded log truncated. Open GitHub artifacts for the complete file. ---"
    } else {
      $text
    }
  } finally {
    $reader.Dispose()
  }
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
$hasZeroItemWarning = $env:SCRAPE_STATUS -eq "success" -and $zeroItemLines.Count -gt 0
$alertText = if ($hasZeroItemWarning) {
  "WARNING: successful scrape reported zero items for: $($zeroItemLines -join '; ')"
} else {
  "No scrape data warnings detected."
}
$subjectPrefix = if ($hasZeroItemWarning) {
  "[Sal Kal] Scrape warning"
} else {
  "[Sal Kal] Scrape $($env:SCRAPE_STATUS)"
}
$subject = "$subjectPrefix - run $($env:GITHUB_RUN_NUMBER)"
$statusColor = if ($env:SCRAPE_STATUS -eq "success" -and -not $hasZeroItemWarning) {
  "#15803d"
} elseif ($env:SCRAPE_STATUS -eq "success") {
  "#b45309"
} else {
  "#b91c1c"
}
$statusLabel = if ($hasZeroItemWarning) {
  "warning"
} else {
  $env:SCRAPE_STATUS
}
$runUrl = "$($env:GITHUB_SERVER_URL)/$($env:GITHUB_REPOSITORY)/actions/runs/$($env:GITHUB_RUN_ID)"
$encodedRepository = [System.Net.WebUtility]::HtmlEncode($env:GITHUB_REPOSITORY)
$encodedBranch = [System.Net.WebUtility]::HtmlEncode($env:GITHUB_REF_NAME)
$encodedForceFull = [System.Net.WebUtility]::HtmlEncode($env:FORCE_FULL)
$encodedSchedule = [System.Net.WebUtility]::HtmlEncode($env:SCHEDULE)
$encodedRunUrl = [System.Net.WebUtility]::HtmlEncode($runUrl)
$encodedLogsUrl = [System.Net.WebUtility]::HtmlEncode($env:SCRAPE_LOGS_URL)
$encodedSummary = [System.Net.WebUtility]::HtmlEncode($summaryText)
$encodedFullLog = [System.Net.WebUtility]::HtmlEncode($fullLogText)
$encodedAlert = [System.Net.WebUtility]::HtmlEncode($alertText)

$body = @"
<!doctype html>
<html>
  <body style="margin:0;background:#f6f8fb;color:#172033;font-family:Segoe UI,Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="1040" cellspacing="0" cellpadding="0" style="width:1040px;max-width:96%;background:#ffffff;border:1px solid #d9e2ec;border-radius:14px;overflow:hidden;">
            <tr>
              <td style="padding:24px 28px;background:#0f172a;color:#ffffff;">
                <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#93c5fd;">Sal Kal scraper</div>
                <div style="font-size:24px;font-weight:700;margin-top:6px;">Scrape completed</div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px;">
                <div style="display:inline-block;padding:7px 12px;border-radius:999px;background:$statusColor;color:#ffffff;font-weight:700;text-transform:uppercase;font-size:12px;letter-spacing:.06em;">$statusLabel</div>
                <p style="margin:16px 0 0;font-size:15px;line-height:1.5;color:#334155;">$encodedAlert</p>

                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:22px;border-collapse:collapse;font-size:14px;">
                  <tr><td style="padding:8px 0;color:#64748b;width:130px;">Repository</td><td style="padding:8px 0;color:#0f172a;">$encodedRepository</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Branch</td><td style="padding:8px 0;color:#0f172a;">$encodedBranch</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Force full</td><td style="padding:8px 0;color:#0f172a;">$encodedForceFull</td></tr>
                  <tr><td style="padding:8px 0;color:#64748b;">Schedule</td><td style="padding:8px 0;color:#0f172a;">$encodedSchedule</td></tr>
                </table>

                <p style="margin:18px 0 0;"><a href="$encodedRunUrl" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:700;">Open GitHub run</a> <a href="$encodedLogsUrl" style="display:inline-block;margin-left:8px;background:#0f172a;color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:700;">Download full logs</a></p>

                <h2 style="font-size:16px;margin:28px 0 10px;color:#0f172a;">Scraper summary</h2>
                <pre style="white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;color:#172033;font-size:13px;line-height:1.45;overflow-x:auto;">$encodedSummary</pre>

                <h2 style="font-size:16px;margin:24px 0 10px;color:#0f172a;">Scraper log</h2>
                <p style="margin:0 0 10px;font-size:13px;color:#64748b;">Embedded log preview. Use Download full logs for the uploaded artifact.</p>
                <pre style="white-space:pre-wrap;background:#0b1220;border-radius:10px;padding:16px;color:#dbeafe;font-size:12px;line-height:1.5;overflow-x:auto;">$encodedFullLog</pre>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
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
$message.IsBodyHtml = $true

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
