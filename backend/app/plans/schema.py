"""The frozen JSON Schema is also the runtime validator, without a second model."""
import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / 'contracts/trade_plan.schema.json').read_text(encoding='utf-8'))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
EDITABLE = set(SCHEMA['properties']) - {'id', 'version', 'status', 'confirmation'}


def content_hash(plan):
    """SHA256 of the UTF-8 canonical draft: sorted keys, no whitespace, no NaN."""
    draft = {k: v for k, v in plan.items() if k != 'confirmation'}
    draft['status'] = 'draft'
    return hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate(plan):
    # Bound arbitrary user strings/arrays as well as Decimal operands before arithmetic.
    if len(json.dumps(plan, ensure_ascii=False)) > 60000:
        raise PlanError(422, 'План слишком большой')
    def bounds(value):
        if isinstance(value, dict):
            for v in value.values(): bounds(v)
        elif isinstance(value, list):
            if len(value) > 40: raise PlanError(422, 'Слишком много элементов плана')
            for v in value: bounds(v)
        elif isinstance(value, str) and len(value) > 3000:
            raise PlanError(422, 'Поле плана слишком длинное')
    bounds(plan)
    if next(VALIDATOR.iter_errors(plan), None):
        raise PlanError(422, 'План не соответствует схеме: проверьте обязательные поля, форматы и условия')


class PlanError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


def openapi_schemas():
    def refs(value):
        if isinstance(value, dict):
            return {k: (v.replace('#/$defs/', '#/components/schemas/Plan_') if k == '$ref' else refs(v)) for k, v in value.items()}
        if isinstance(value, list): return [refs(v) for v in value]
        return value
    schemas = {'TradePlan': refs({k: v for k, v in SCHEMA.items() if k not in ('$schema', '$id', '$defs')})}
    schemas.update({'Plan_' + k: refs(v) for k, v in SCHEMA['$defs'].items()})
    schemas['PlanChanges'] = {'type': 'object', 'additionalProperties': False, 'minProperties': 1,
                             'properties': {k: copy.deepcopy(v) for k, v in schemas['TradePlan']['properties'].items() if k in EDITABLE}}
    return schemas
