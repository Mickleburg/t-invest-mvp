"""CP6 OFFLINE: explicit synthetic sources, real HTTP/SQLite/risk/worker."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes import create_app
from backend.app.plans.schema import content_hash
from backend.app.storage.repository import Store

from backend.scripts.cp6_fixtures import Fixtures, TEXT, INSTRUMENT, NARRATIVE


@pytest.fixture
def workflow(tmp_path):
    fixture = Fixtures()
    app = create_app(tmp_path, model=fixture.model, tool=fixture.tool, test_doubles=True, worker_enabled=False)
    with TestClient(app) as client:
        app.state.plans.clock = app.state.monitor.clock = fixture.clock
        sid = client.post('/api/sessions').json()['session']['id']
        result = client.post(f'/api/sessions/{sid}/messages', json={'text': TEXT, 'request_id': str(uuid4()), 'educational': True})
        assert result.status_code == 200 and not result.json()['messages'][-1]['response'].get('error')
        draft = client.get(f'/api/sessions/{sid}/plan')
        assert draft.status_code == 200, draft.text
        plan = draft.json(); pid = plan['id']
        edited = client.patch('/api/plans/' + pid, json={'expected_version': plan['version'], 'changes': NARRATIVE})
        assert edited.status_code == 200, edited.text
        assert edited.json()['risk']['status'] == 'calculated', edited.text
        yield fixture, client, edited


def confirm(client, response, request_id=None):
    plan = response.json()
    return client.post(f"/api/plans/{plan['id']}/confirm", json={'version': plan['version'],
                       'content_hash': response.headers['etag'].strip('"'), 'request_id': request_id or str(uuid4())})


def run_check(client, plan, request_id=None):
    return client.portal.call(client.app.state.monitor.check, plan['id'], plan['version'], request_id or str(uuid4()))


def test_version_hash_confirmation_and_immutable_snapshot(workflow):
    fixture, client, draft = workflow
    p = draft.json(); pid = p['id']
    assert content_hash(p) == draft.headers['etag'].strip('"')
    assert Decimal(p['risk']['calculation']['loss_at_stop']) == 1000
    assert client.patch('/api/plans/' + pid, json={'expected_version': 1, 'changes': NARRATIVE}).status_code == 409
    assert client.post(f'/api/plans/{pid}/confirm', json={'version': p['version'], 'content_hash': '0'*64, 'request_id': str(uuid4())}).status_code == 409
    request = str(uuid4()); result = confirm(client, draft, request)
    assert result.status_code == 200, result.text
    snapshot = result.json()
    assert snapshot['confirmation']['version'] == snapshot['version'] == 2
    assert confirm(client, draft, request).json() == snapshot
    conflict = client.post(f'/api/plans/{pid}/confirm', json={'version': 2, 'content_hash': '1'*64, 'request_id': request})
    assert conflict.status_code == 409
    assert confirm(client, draft).status_code == 409
    new = client.patch('/api/plans/' + pid, json={'expected_version': 2, 'changes': {'hypothesis': 'Новый черновик'}})
    assert new.status_code == 200 and new.json()['version'] == 3 and new.json()['status'] == 'draft'
    with client.app.state.store.connect() as db:
        assert json.loads(db.execute('SELECT document FROM plan_snapshots WHERE plan_id=?', (pid,)).fetchone()[0]) == snapshot
        with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE plan_snapshots SET document=? WHERE plan_id=?', ('{}', pid))
    assert confirm(client, draft, request).json() == snapshot
    assert client.get(f'/api/plans/{pid}/monitoring').json()['confirmed_version'] == 2
    assert run_check(client, snapshot)['checks'][0]['plan_version'] == 2


@pytest.mark.parametrize('changes', [
    {'parameters': {'entry': '100000', 'stop': '101000', 'quantity': '1', 'capital': '100000', 'capital_currency': 'RUB', 'price_unit': 'points'}},
    {'parameters': {'entry': '100000', 'stop': '99000', 'quantity': '2', 'capital': '100000', 'capital_currency': 'RUB', 'price_unit': 'points'}},
    {'parameters': {'entry': '100000', 'stop': '99000', 'quantity': '0.5', 'capital': '100000', 'capital_currency': 'RUB', 'price_unit': 'points'}},
    {'parameters': {'entry': '100000', 'stop': '99000', 'quantity': '1', 'capital': '100000', 'capital_currency': 'USD', 'price_unit': 'points'}},
    {'parameters': {'entry': '100000', 'stop': '99000', 'quantity': '1', 'capital': '100000', 'capital_currency': 'RUB', 'price_unit': 'points', 'point_value': '0.01'}},
    {'parameters': {'entry': '100000', 'stop': '99000', 'quantity': '1', 'capital': '100000', 'capital_currency': 'RUB', 'price_unit': 'points', 'lot_size': 2}},
    {'hypothesis': ''}, {'horizon': ''}, {'review_conditions': []}, {'entry_conditions': ['  ']},
    {'rules': []}, {'risk': {'limit': {'kind': 'money', 'value': '999', 'currency': 'RUB'}}}
])
def test_unsafe_or_incomplete_plan_never_confirms(workflow, changes):
    fixture, client, draft = workflow
    edited = client.patch('/api/plans/' + draft.json()['id'], json={'expected_version': 2, 'changes': changes})
    assert edited.status_code == 200, edited.text
    result = confirm(client, edited)
    assert result.status_code == 422, result.text
    with client.app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM plan_snapshots').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM monitoring').fetchone()[0] == 0


@pytest.mark.parametrize('changes', [
    {'sources': []}, {'session_id': 'other'}, {'educational': False},
    {'instrument': INSTRUMENT | {'id': 'UNKNOWN'}},
    {'parameters': {'entry': 'NaN'}}, {'parameters': {'entry': '9'*41}},
    {'risk': {'calculation': {'loss_at_stop': '0'}}},
])
def test_untrusted_changes_fail_or_are_recomputed(workflow, changes):
    fixture, client, draft = workflow
    result = client.patch('/api/plans/' + draft.json()['id'], json={'expected_version': 2, 'changes': changes})
    if result.status_code == 200:
        assert confirm(client, result).status_code == 422
        assert result.json()['risk'].get('calculation', {}).get('loss_at_stop') != '0'
    else: assert result.status_code == 422, result.text


def test_rules_wrong_instrument_unit_and_manual_automation(workflow):
    fixture, client, draft = workflow
    original = draft.json()
    for change in ({'unit': 'RUB'}, {'source_ids': ['unknown']}, {'max_age_seconds': 999999},
                   {'metric': 'manual_event'}, {'id': ''}):
        rule = original['rules'][0] | change
        current = client.get('/api/plans/' + original['id'])
        edited = client.patch('/api/plans/' + original['id'], json={'expected_version': current.json()['version'], 'changes': {'rules': [rule]}})
        if edited.status_code == 200: assert confirm(client, edited).status_code == 422
        else: assert edited.status_code == 422


def test_worker_persists_provenance_delivery_ack_and_deduplicates_on_restart(workflow):
    fixture, client, draft = workflow
    confirmed = confirm(client, draft).json(); pid = confirmed['id']
    request = str(uuid4()); result = run_check(client, confirmed, request)
    check = result['checks'][0]
    assert check['status'] == 'satisfied' and check['observed_value'] == '98000'
    calls = len(fixture.calls)
    assert run_check(client, confirmed, request) == result and len(fixture.calls) == calls
    notices = client.get(f'/api/plans/{pid}/notifications').json()
    assert len(notices) == 1 and notices[0]['delivery_status'] == 'stored'
    assert 'Учебный' in notices[0]['text'] and '98000' in notices[0]['text'] and '23.11.2026 13:00:00 МСК' in notices[0]['text']
    # A new service instance uses the same DB (no copied DB) and retains deduplication.
    from backend.app.monitoring.service import Monitor
    client.app.state.monitor = Monitor(Store(client.app.state.store.path), tool=fixture.tool, test_doubles=True, clock=fixture.clock)
    run_check(client, confirmed)
    assert len(client.get(f'/api/plans/{pid}/notifications').json()) == 1
    ack = client.post(f"/api/plans/{pid}/notifications/{notices[0]['id']}/ack")
    assert ack.status_code == 200 and ack.json()['delivery_status'] == 'delivered'
    assert client.post(f"/api/plans/{pid}/notifications/{notices[0]['id']}/ack").json() == ack.json()
    state = client.get('/api/sessions/' + confirmed['session_id']).json()
    evidence = {e['id']: e for e in state['evidence']}
    assert all(s in evidence for s in check['source_ids'])
    assert evidence[check['source_ids'][1]]['result']['data']['instruments'][0]['values'][0]['time'] == fixture.current.isoformat()


@pytest.mark.parametrize('failure', ['stale', 'future', 'unit', 'identity', 'spec', 'quote', 'point_value'])
def test_bad_source_is_uncertainty_never_trigger(workflow, failure):
    fixture, client, draft = workflow
    confirmed = confirm(client, draft).json()
    if failure == 'stale': fixture.stale = True
    elif failure == 'future': fixture.future = True
    elif failure == 'unit': fixture.unit = 'rub'
    elif failure == 'identity': fixture.wrong_identity = True
    elif failure == 'point_value': fixture.point_value = '10'
    else: fixture.failed = failure
    check = run_check(client, confirmed)['checks'][0]
    assert check['status'] == 'insufficient_data' and check['observed_value'] is None
    notices = client.get(f"/api/plans/{confirmed['id']}/notifications").json()
    assert len(notices) == 1 and 'Недостаточно данных' in notices[0]['text']
    run_check(client, confirmed)
    assert len(client.get(f"/api/plans/{confirmed['id']}/notifications").json()) == 1


def test_draft_does_not_change_worker_and_new_confirmation_switches_version(workflow):
    fixture, client, draft = workflow
    first = confirm(client, draft).json()
    rule = first['rules'][0] | {'threshold': '97000'}
    edited = client.patch('/api/plans/' + first['id'], json={'expected_version': 2, 'changes': {'rules': [rule]}})
    assert run_check(client, first)['checks'][0]['status'] == 'satisfied'
    new = confirm(client, edited)
    assert new.status_code == 200, new.text
    assert run_check(client, new.json())['checks'][0]['status'] == 'affected'
    with pytest.raises(Exception) as error: run_check(client, first)
    assert error.value.status == 409


def test_confirmation_rollback_if_storage_write_fails(workflow):
    fixture, client, draft = workflow
    with client.app.state.store.connect() as db:
        db.execute("CREATE TRIGGER fail_monitor BEFORE INSERT ON monitoring BEGIN SELECT RAISE(ABORT,'TEST DOUBLE failure'); END")
    with pytest.raises(sqlite3.IntegrityError): confirm(client, draft)
    with client.app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM plan_snapshots').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM confirmations').fetchone()[0] == 0
    assert client.get('/api/plans/' + draft.json()['id']).json()['status'] == 'draft'


def test_compare_and_swap_concurrent_edits(workflow):
    fixture, client, draft = workflow
    async def edits():
        async def edit(value):
            try: return await client.app.state.plans.update_draft(draft.json()['id'], 2, {'hypothesis': value})
            except Exception as exc: return exc
        return await asyncio.gather(edit('A'), edit('B'))
    results = client.portal.call(edits)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert next(r for r in results if not isinstance(r, dict)).status == 409


@pytest.mark.parametrize('stale,synth,max_age', [(False, False, 300), (True, False, 300), (False, True, 300), (True, False, 1000)])
def test_non_educational_confirmation_requires_fresh_genuine_sources(tmp_path, stale, synth, max_age):
    fixture = Fixtures(); fixture.stale = stale
    async def trusted_transport_double(request, known):
        # Simulate transport provenance for this offline branch test only.
        return await fixture.tool(request, known) | {'synthetic': synth}
    with TestClient(create_app(tmp_path, model=fixture.model, tool=trusted_transport_double,
                               test_doubles=False, worker_enabled=False)) as client:
        client.app.state.plans.clock = fixture.clock
        sid = client.post('/api/sessions').json()['session']['id']
        client.post(f'/api/sessions/{sid}/messages', json={'text': TEXT, 'request_id': str(uuid4()), 'educational': False})
        initial = client.get(f'/api/sessions/{sid}/plan').json()
        assert initial['educational'] is False
        rule = initial['rules'][0] | {'max_age_seconds': max_age}
        draft = client.patch('/api/plans/' + initial['id'], json={'expected_version': 1, 'changes': NARRATIVE | {'rules': [rule]}})
        assert draft.status_code == 200
        result = confirm(client, draft)
        assert result.status_code == (422 if stale and max_age < 600 or synth else 200), result.text


def test_worker_lease_excludes_second_checker_and_recovers_after_cancellation(workflow):
    fixture, client, draft = workflow
    snapshot = confirm(client, draft).json()
    async def scenario():
        started = asyncio.Event(); release = asyncio.Event()
        async def blocked_tool(request, known):
            started.set(); await release.wait()
            return await fixture.tool(request, known)
        monitor = client.app.state.monitor; monitor.tool = blocked_tool
        task = asyncio.create_task(monitor.check(snapshot['id'], 2, str(uuid4())))
        await started.wait()
        from backend.app.plans.schema import PlanError
        with pytest.raises(PlanError) as error: await monitor.check(snapshot['id'], 2, str(uuid4()))
        assert error.value.status == 409
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        with client.app.state.store.connect() as db:
            assert db.execute('SELECT lease_owner FROM monitoring').fetchone()[0] is None
        monitor.tool = fixture.tool
        return await monitor.check(snapshot['id'], 2, str(uuid4()))
    assert client.portal.call(scenario)['checks'][0]['status'] == 'satisfied'


def test_new_confirmation_discards_in_flight_results_of_previous_version(workflow):
    fixture, client, draft = workflow
    original = confirm(client, draft).json()
    async def scenario():
        started = asyncio.Event(); release = asyncio.Event()
        async def blocked_tool(request, known):
            started.set(); await release.wait()
            return await fixture.tool(request, known)
        monitor = client.app.state.monitor; monitor.tool = blocked_tool
        task = asyncio.create_task(monitor.check(original['id'], 2, str(uuid4())))
        await started.wait()
        plans = client.app.state.plans
        changed = await plans.update_draft(original['id'], 2, {'hypothesis': 'Новая гипотеза'})
        await plans.confirm(original['id'], 3, content_hash(changed), str(uuid4()))
        release.set()
        from backend.app.plans.schema import PlanError
        with pytest.raises(PlanError) as error: await task
        assert error.value.status == 409
    client.portal.call(scenario)
    assert client.get(f"/api/plans/{original['id']}/checks").json() == []
    assert client.get(f"/api/plans/{original['id']}/notifications").json() == []


def test_worker_transaction_rolls_back_then_retries_error_after_restart(workflow):
    fixture, client, draft = workflow
    snapshot = confirm(client, draft).json()
    store = client.app.state.store
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_notice BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'TEST DOUBLE storage failure'); END")
        initial = db.execute('SELECT count(*) FROM evidence').fetchone()[0]
    client.portal.call(client.app.state.monitor.tick)
    with store.connect() as db:
        assert db.execute('SELECT state FROM monitoring').fetchone()[0] == 'error'
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == initial
        assert db.execute('SELECT count(*) FROM plan_checks').fetchone()[0] == 0
        db.execute('DROP TRIGGER fail_notice')
    fixture.current += timedelta(seconds=61)
    from backend.app.monitoring.service import Monitor
    monitor = Monitor(Store(store.path), tool=fixture.tool, test_doubles=True, clock=fixture.clock)
    client.portal.call(monitor.tick)
    assert monitor.state(snapshot['id'])['state'] == 'active'
    assert len(monitor.notifications(snapshot['id'])) == 1


def test_manual_events_stay_unverified_and_thresholds_need_tick_alignment(workflow):
    fixture, client, draft = workflow
    initial = draft.json()
    rule = initial['rules'][0] | {'threshold': '99000.5'}
    edited = client.patch('/api/plans/' + initial['id'], json={'expected_version': 2, 'changes': {'rules': [rule]}})
    assert confirm(client, edited).status_code == 422
    rule = {'id': 'Проверить новость вручную', 'metric': 'manual_event', 'operator': 'manual', 'automatic': False,
            'source_ids': [initial['instrument']['spec_source_id']]}
    edited = client.patch('/api/plans/' + initial['id'], json={'expected_version': 3, 'changes': {'rules': [rule]}})
    result = confirm(client, edited)
    assert result.status_code == 200, result.text
    assert run_check(client, result.json())['checks'][0]['status'] == 'insufficient_data'


def test_failed_latest_specification_cannot_hide_behind_saved_draft_source(workflow):
    fixture, client, draft = workflow
    from backend.app.storage.repository import dump
    with client.app.state.store.connect() as db:
        e = {'id': str(uuid4()), 'kind': 'spec', 'instrument_id': INSTRUMENT['id'], 'status': 'unavailable',
             'observed_at': fixture.current.isoformat(), 'result': None, 'calls': [], 'synthetic': True}
        db.execute('INSERT INTO evidence VALUES(?,?,NULL,?)', (e['id'], draft.json()['session_id'], dump(e)))
    result = confirm(client, draft)
    assert result.status_code == 422 and 'Последняя проверка' in result.json()['detail']
