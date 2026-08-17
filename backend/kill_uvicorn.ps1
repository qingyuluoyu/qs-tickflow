Get-NetTCPConnection -State Listen -LocalPort 3018 -ErrorAction SilentlyContinue | ForEach-Object { $conn = $_; $p = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue; if ($p) { Write-Output "$($p.Id) $($p.ProcessName) listening on 3018" } }
Write-Output "---"
Get-Process python* -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, HasExited | Format-Table -AutoSize
