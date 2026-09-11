#!/usr/bin/env python3
"""Create .env with unique secrets; never print them and never overwrite an existing file."""
import argparse
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--test-mode', action='store_true', help='Offline synthetic fixture mode')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
values = {key: secrets.token_hex(32) for key in ('POSTGRES_PASSWORD', 'POSTGRES_APP_PASSWORD',
          'POSTGRES_N8N_PASSWORD', 'WORKER_API_KEY', 'N8N_ENCRYPTION_KEY')}
if args.test_mode:
    values.update(LLM_PROVIDER='mock', STOCK_PROVIDER='mock', TTS_PROVIDER='mock', ALLOW_TEST_MODE='true')
lines = (root / '.env.example').read_text().splitlines()
content = '\n'.join(f'{line.split("=", 1)[0]}={values[line.split("=", 1)[0]]}'
                    if '=' in line and line.split('=', 1)[0] in values else line for line in lines) + '\n'
try:
    fd = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env already exists. Edit it manually; nothing was overwritten.')
with os.fdopen(fd, 'w') as handle:
    handle.write(content)
print('Created .env with independent random secrets. ' + ('Offline test mode enabled.' if args.test_mode else 'Now set PEXELS_API_KEY, LLM_API_KEY and LLM_MODEL.'))
