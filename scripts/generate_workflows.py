#!/usr/bin/env python3
"""Reproducible n8n exports. No credentials, env access, code nodes or publication APIs."""
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def node(name, kind, parameters, x, y=0, version=1, **extra):
    return {'id': str(uuid4()), 'name': name, 'type': 'n8n-nodes-base.' + kind,
            'typeVersion': version, 'position': [x, y], 'parameters': parameters, **extra}


def http(name, parameters, x):
    return node(name, 'httpRequest', {'authentication': 'genericCredentialType',
                'genericAuthType': 'httpHeaderAuth', 'options': {'timeout': 30000}, **parameters}, x,
                version=4.2, retryOnFail=True, maxTries=3, waitBetweenTries=3000,
                credentials={'httpHeaderAuth': {'id': 'SELECT_YOUR_CREDENTIAL', 'name': 'VideoTT API'}})


def condition(name, expression, x):
    return node(name, 'if', {'conditions': {'options': {'caseSensitive': True, 'leftValue': '',
                'typeValidation': 'strict', 'version': 2}, 'conditions': [{'id': str(uuid4()),
                'leftValue': expression, 'rightValue': True, 'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}],
                'combinator': 'and'}, 'options': {}}, x, version=2.2)


def workflow(scheduled=False):
    if scheduled:
        trigger = node('Daily schedule', 'scheduleTrigger', {'rule': {'interval': [
            {'field': 'cronExpression', 'expression': '0 10 * * *'}]}}, 0, version=1.2)
    else:
        trigger = node('Manual test', 'manualTrigger', {}, 0)
    create_body = '{}' if scheduled else '={{ JSON.stringify({topic: $json.topic}) }}'
    nodes = [trigger]
    if not scheduled:
        nodes.append(node('Choose topic', 'set', {'assignments': {'assignments': [{'id': str(uuid4()),
            'name': 'topic', 'value': 'Why do the F and J keys on keyboards have raised bumps?', 'type': 'string'}]},
            'options': {}}, 200, version=3.4))
    nodes += [http('Create video', {'method': 'POST', 'url': 'http://worker:8000/api/v1/videos',
        'sendHeaders': True, 'headerParameters': {'parameters': [{'name': 'Idempotency-Key',
            'value': "={{ 'n8n-' + $workflow.id + '-' + $execution.id }}"}]},
        'sendBody': True, 'specifyBody': 'json', 'jsonBody': create_body}, 420),
        node('Wait 30 seconds', 'wait', {'amount': 30, 'unit': 'seconds'}, 640, version=1.1, webhookId=str(uuid4())),
        http('Check job', {'url': "={{ 'http://worker:8000/api/v1/jobs/' + $('Create video').first().json.job_id }}"}, 860),
        condition('Ready?', "={{ $json.status === 'READY' }}", 1080),
        node('Record completed video', 'set', {'assignments': {'assignments': [
            {'id': str(uuid4()), 'name': 'video_id', 'value': '={{ $json.video_id }}', 'type': 'string'},
            {'id': str(uuid4()), 'name': 'status', 'value': 'READY', 'type': 'string'},
            {'id': str(uuid4()), 'name': 'download_path', 'value': "={{ '/api/v1/videos/' + $json.video_id + '/download' }}", 'type': 'string'},
            {'id': str(uuid4()), 'name': 'next_step', 'value': 'Download, review the video and caption, then publish manually.', 'type': 'string'}]},
            'options': {}}, 1340, -140, version=3.4),
        condition('Still processing?', "={{ ['QUEUED','RESEARCHING','SCRIPTING','FETCHING_ASSETS','GENERATING_TTS','RENDERING','VALIDATING'].includes($json.status) && (Date.now() - Date.parse($json.created_at) < 7200000) }}", 1340),
        node('Needs attention', 'stopAndError', {'errorMessage': "={{ 'Video job stopped or exceeded 2 hours: ' + $json.status + ' / ' + ($json.error_code || 'check runner') + ' / video ' + $json.video_id }}"}, 1580, 140),
    ]
    def edge(name):
        return {'node': name, 'type': 'main', 'index': 0}
    connections = {
        trigger['name']: {'main': [[edge('Create video' if scheduled else 'Choose topic')]]},
        'Create video': {'main': [[edge('Wait 30 seconds')]]},
        'Wait 30 seconds': {'main': [[edge('Check job')]]},
        'Check job': {'main': [[edge('Ready?')]]},
        'Ready?': {'main': [[edge('Record completed video')], [edge('Still processing?')]]},
        'Still processing?': {'main': [[edge('Wait 30 seconds')], [edge('Needs attention')]]},
    }
    if not scheduled:
        connections['Choose topic'] = {'main': [[edge('Create video')]]}
    return {'name': 'VideoTT — ' + ('Daily creation' if scheduled else 'Manual creation'), 'active': False,
            'nodes': nodes, 'connections': connections,
            'settings': {'executionOrder': 'v1', 'timezone': 'Asia/Almaty', 'executionTimeout': 7200,
                         'saveDataSuccessExecution': 'all', 'saveDataErrorExecution': 'all'},
            'pinData': {}, 'tags': []}


if __name__ == '__main__':
    for scheduled, filename in [(False, 'manual.json'), (True, 'daily.json')]:
        (ROOT / 'workflows' / filename).write_text(json.dumps(workflow(scheduled), ensure_ascii=False, indent=2) + '\n')
