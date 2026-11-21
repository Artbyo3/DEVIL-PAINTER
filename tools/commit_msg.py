import re
import sys
from pathlib import Path

CO_AUTHOR = re.compile(r'co-authored-by\s*:', re.IGNORECASE)


def strip_co_authors(message):
    lines = message.splitlines()
    kept = [line for line in lines if not CO_AUTHOR.match(line.strip())]
    if len(kept) == len(lines):
        return message
    while kept and not kept[-1].strip():
        kept.pop()
    return '\n'.join(kept) + '\n'


def main(path):
    message_file = Path(path)
    message = message_file.read_text(encoding='utf-8')
    cleaned = strip_co_authors(message)
    if cleaned != message:
        message_file.write_text(cleaned, encoding='utf-8', newline='\n')
        print('commit-msg: removed Co-Authored-By trailers; attribution belongs in the PR body.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
