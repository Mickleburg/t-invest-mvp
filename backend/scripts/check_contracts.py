"""Offline contract gate: validation, snapshot drift and examples; no network calls."""
import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator,FormatChecker
from openapi_spec_validator import validate_spec
from backend.app.main import create_app
from backend.app.api.models import SessionState
from backend.scripts.export_contracts import document

ROOT=Path(__file__).resolve().parents[2]

def check():
    spec=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text(encoding='utf-8'))
    validate_spec(spec)
    assert spec==document(),'Frozen contract drift: review before regenerating'
    schema=json.loads((ROOT/'contracts/trade_plan.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    validator=Draft202012Validator(schema,format_checker=FormatChecker())
    for name in ('draft','confirmed'):validator.validate(json.loads((ROOT/f'contracts/examples/trade_plan.{name}.json').read_text(encoding='utf-8')))
    SessionState.model_validate(json.loads((ROOT/'contracts/examples/session_state.mock.json').read_text(encoding='utf-8')))
    actual=create_app().openapi()
    for path,item in spec['paths'].items():
        for verb,op in item.items():
            if op['x-implementation-status']=='planned':assert verb not in actual['paths'].get(path,{})
            else:
                runtime=actual['paths'][path][verb]
                assert {k:v for k,v in op.items() if k!='x-implementation-status'}==runtime
    return {'openapi':'valid','plan_schema':'valid','examples':'valid','implemented_drift':False,'planned_routes_implemented':False}

if __name__=='__main__':print(json.dumps(check()))
