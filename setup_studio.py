#!/usr/bin/env python3
"""Check the only server dependency; no downloads or model installation."""
import sys

def main():
    if sys.version_info < (3, 9):
        raise RuntimeError('Install Python 3.9 or newer.')
    print('Ready. Run python start_studio.py or open the launcher.')

if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
