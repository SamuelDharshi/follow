# Prevents idle sleep while this process runs (does not change power settings). Stop it by ending the process.
Add-Type -Namespace Win -Name Pwr -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
while ($true) { [Win.Pwr]::SetThreadExecutionState(0x80000001) | Out-Null; Start-Sleep -Seconds 30 }
