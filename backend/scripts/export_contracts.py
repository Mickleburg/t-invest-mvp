"""Export implemented operations; human approval is tracked separately."""
from pathlib import Path
import yaml
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def document():
    spec = create_app().openapi()
    spec['info'] = {'title': 'TradeGuard MVP', 'version': '0.2.0',
                    'description': 'Implemented dialogue, versioned plans, confirmation and monitoring. Provisional: human review required.'}
    spec['x-contract-state'] = 'provisional-team-review-required'
    for item in spec['paths'].values():
        for operation in item.values(): operation['x-implementation-status'] = 'implemented'
    return spec


if __name__ == '__main__':
    (ROOT / 'contracts/openapi.yaml').write_text(yaml.safe_dump(document(), allow_unicode=True, sort_keys=False), encoding='utf-8')