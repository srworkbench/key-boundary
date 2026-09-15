"""Counterfactual deduplication audit. No delivery or external side effects."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re


class InvalidInput(ValueError):
    pass


def pointer(document, path):
    """JSON Pointer lookup; missing, empty, null and compound keys are unresolved."""
    if not isinstance(path, str) or not path.startswith('/'):
        raise InvalidInput('Key paths must be nonempty JSON Pointers, such as /body/item_id')
    current = document
    for token in path[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise InvalidInput('Invalid JSON Pointer escape: ' + path)
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(current):
            current = current[int(token)]
        else:
            return None
    if current is None or current == '' or isinstance(current, (dict, list)):
        return None
    if isinstance(current, float) and not math.isfinite(current):
        raise InvalidInput('Non-finite key value: ' + path)
    # JSON encoding preserves type: true, 1 and "1" must not collapse.
    return json.dumps(current, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def fields(value):
    if not isinstance(value, list) or not value or any(not isinstance(p, str) for p in value):
        raise InvalidInput('Each key needs a nonempty list of JSON Pointer fields')
    if len(set(value)) != len(value):
        raise InvalidInput('Repeated key fields are not allowed')
    for path in value:
        pointer({}, path)
    return value


def key(record, paths):
    values = tuple(pointer(record, p) for p in paths)
    return None if None in values else values


def audit(spec):
    if not isinstance(spec, dict):
        raise InvalidInput('Input must be a JSON object')
    reference = fields(spec.get('reference_fields'))
    events = spec.get('deliveries')
    policies = spec.get('policies')
    if not isinstance(events, list) or not events:
        raise InvalidInput('Provide at least one delivery')
    if not isinstance(policies, list) or not policies:
        raise InvalidInput('Provide at least one policy')
    ids, last = set(), -math.inf
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not event['id']:
            raise InvalidInput('Every delivery needs a nonempty string id')
        if event['id'] in ids:
            raise InvalidInput('Delivery row ids must be unique; use body fields for repeated provider IDs')
        ids.add(event['id'])
        time = event.get('at')
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or time < 0 or time < last:
            raise InvalidInput('Delivery at values must be finite nonnegative seconds in arrival order')
        last = time
    output = {'version': 1, 'reference_fields': reference,
              'assumption': 'Reference fields define the same intended action across this entire input. Results are conditional on that definition.',
              'delivery_count': len(events), 'policies': []}
    names = set()
    for policy in policies:
        if not isinstance(policy, dict) or not isinstance(policy.get('name'), str) or not policy['name']:
            raise InvalidInput('Each policy needs a nonempty name')
        if policy['name'] in names:
            raise InvalidInput('Policy names must be unique')
        names.add(policy['name'])
        paths = fields(policy.get('fields'))
        window = policy.get('window_seconds')
        if window is not None and (isinstance(window, bool) or not isinstance(window, (int, float)) or not math.isfinite(window) or window <= 0):
            raise InvalidInput('window_seconds must be positive or null for whole-input retention')
        cache, delivered, rows = {}, {}, []
        for event in events:
            ref, candidate = key(event, reference), key(event, paths)
            row = {'id': event['id'], 'at': event['at'], 'witness': None,
                   'reference_values': {p: pointer(event, p) for p in reference},
                   'candidate_values': {p: pointer(event, p) for p in paths}}
            if ref is None or candidate is None:
                row.update(status='unresolved', reason='Missing or nonscalar reference identity' if ref is None else 'Missing or nonscalar candidate key')
            else:
                previous = cache.get(candidate)
                if previous and window is not None and event['at'] - previous['at'] >= window:
                    previous = None
                if previous:
                    same = previous['reference'] == ref
                    row.update(status='duplicate' if same else 'false_merge', witness=previous['id'],
                               reason='Same intended action suppressed' if same else 'Different intended action suppressed by this key')
                else:
                    witness = delivered.get(ref)
                    row.update(status='false_split' if witness else 'accepted', witness=witness,
                               reason='Intended action admitted again' if witness else 'First admission of this intended action')
                    cache[candidate] = {'reference': ref, 'id': event['id'], 'at': event['at']}
                    delivered.setdefault(ref, event['id'])
            rows.append(row)
        output['policies'].append({'name': policy['name'], 'fields': paths, 'window_seconds': window,
                                   'counts': dict(Counter(r['status'] for r in rows)), 'rows': rows})
    return output


def read_spec(path):
    def reject_constant(value):
        raise InvalidInput('Non-finite JSON number: ' + value)
    def unique_pairs(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise InvalidInput('Duplicate JSON property: ' + k)
            result[k] = v
        return result
    return json.loads(Path(path).read_text(), parse_constant=reject_constant, object_pairs_hook=unique_pairs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='New output directory; never overwrites a previous audit')
    args = parser.parse_args()
    try:
        result = audit(read_spec(args.input))
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
        from report import render_svg, render_html
        from focus import render_focus
        (args.out / 'focus.svg').write_text(render_focus(result))
        (args.out / 'comparison.svg').write_text(render_svg(result))
        (args.out / 'audit.html').write_text(render_html(result))
    except (InvalidInput, OSError, json.JSONDecodeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps({p['name']: p['counts'] for p in result['policies']}, indent=2))


if __name__ == '__main__':
    main()
