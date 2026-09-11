#!/usr/bin/env python3
"""Small authenticated CLI, runs inside worker or locally with Python dependencies."""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import httpx
from dotenv import load_dotenv

load_dotenv()
parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['create', 'list', 'get', 'download', 'seed', 'retry'])
parser.add_argument('--topic', default='Why do the F and J keys on keyboards have raised bumps?')
parser.add_argument('--id')
parser.add_argument('--wait', action='store_true')
parser.add_argument('--base-url', default=os.getenv('WORKER_BASE_URL', 'http://127.0.0.1:8000'))
parser.add_argument('--output', default='./output')
args = parser.parse_args()
key = os.environ.get('WORKER_API_KEY', '')
if not key:
    raise SystemExit('Set WORKER_API_KEY in the environment or .env')
client = httpx.Client(base_url=args.base_url, headers={'Authorization': 'Bearer ' + key}, timeout=60)


def request(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if not response.is_success:
        raise SystemExit(f'HTTP {response.status_code}: {response.text}')
    return response.json()


if args.command in ('get', 'download', 'retry') and not args.id:
    parser.error('--id is required')
if args.command == 'seed':
    for topic in [args.topic, 'Why is the Save icon a floppy disk?', 'Why are airplane windows rounded?',
                  'Where did the @ symbol come from?', 'How did QR codes originate?',
                  'Why is QWERTY arranged this way?', 'Why was USB-A so easy to insert incorrectly?']:
        request('POST', '/api/v1/topics', json={'title': topic})
    print('Topics added. Scheduling consumes unused topics only.')
elif args.command in ('create', 'retry'):
    path = '/api/v1/videos' if args.command == 'create' else f'/api/v1/videos/{args.id}/render'
    result = request('POST', path, json={'topic': args.topic} if args.command == 'create' else None,
                     headers={'Idempotency-Key': str(uuid4())})
    print(json.dumps(result, indent=2))
    if args.wait:
        started = time.monotonic()
        while time.monotonic() - started < 7200:
            job = request('GET', '/api/v1/jobs/' + result['job_id'])
            print(job['status'], flush=True)
            if job['status'] in ('READY', 'FAILED', 'NEEDS_REVIEW'):
                print(json.dumps(job, indent=2))
                raise SystemExit(0 if job['status'] == 'READY' else 1)
            time.sleep(15)
        raise SystemExit('Timed out waiting. Job remains persisted; inspect status later.')
elif args.command == 'list':
    print(json.dumps(request('GET', '/api/v1/videos?status=READY'), indent=2))
elif args.command == 'get':
    print(json.dumps(request('GET', f'/api/v1/videos/{args.id}'), indent=2))
elif args.command == 'download':
    directory = Path(args.output) / args.id
    directory.mkdir(parents=True, exist_ok=True)
    for endpoint, filename in [('download', 'final.mp4'), ('caption', 'caption.txt'),
                               ('metadata', 'metadata.json'), ('manifest', 'rights_manifest.json')]:
        path = directory / filename
        with client.stream('GET', f'/api/v1/videos/{args.id}/{endpoint}') as response:
            if not response.is_success:
                raise SystemExit(f'Download failed: HTTP {response.status_code}')
            with path.open('wb') as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    print('Saved to', directory.resolve())
