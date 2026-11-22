"""Repair only currency citations using an already quoted numeric parameter.

No number, currency value or economic meaning is inferred or changed. If no
literal supporting quote exists, the existing Risk Engine rejects the input.
"""
from backend.app.risk.grounding import explicit_unit


def currency_citations(inputs,messages):
    if inputs is None:return None
    updates={}
    for name,anchors in [('capital_currency',('capital',)),
                         ('price_currency',('entry','stop','target')),
                         ('point_value_currency',('point_value',))]:
        field=getattr(inputs,name)
        if field is None:continue
        unit='pt' if field.value=='points' else field.value
        if any(field.quote in message for message in messages) and explicit_unit(field.quote,unit):continue
        for anchor in anchors:
            number=getattr(inputs,anchor)
            if number and any(number.quote in message for message in messages) and explicit_unit(number.quote,unit):
                updates[name]=field.model_copy(update={'quote':number.quote})
                break
    return inputs.model_copy(update=updates) if updates else inputs
