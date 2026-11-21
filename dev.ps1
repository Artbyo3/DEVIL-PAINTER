param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)
python -B -u tools/dev.py @Arguments
