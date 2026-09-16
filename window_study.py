"""Compare explicit retention windows without recommending a production setting."""
import argparse
from html import escape
import json
import math
from pathlib import Path

from key_boundary import audit, InvalidInput, read_spec


def validate_windows(windows):
    if not isinstance(windows, list) or not 1 <= len(windows) <= 32:
        raise InvalidInput('Provide between 1 and 32 distinct windows')
    for window in windows:
        if window is not None and (isinstance(window, bool) or not isinstance(window, (int, float))
                                   or not math.isfinite(window) or window <= 0):
            raise InvalidInput('Windows must be positive finite seconds or null for whole-input retention')
    if len(set(windows)) != len(windows):
        raise InvalidInput('Windows must be distinct')
    return sorted((w for w in windows if w is not None)) + ([None] if None in windows else [])


def study(spec, windows, *, max_wrong_drops=0, max_repeat_admits=0, max_unresolved=0):
    windows = validate_windows(windows)
    limits = {'false_merge': max_wrong_drops, 'false_split': max_repeat_admits, 'unresolved': max_unresolved}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in limits.values()):
        raise InvalidInput('Outcome limits must be nonnegative integers')
    baseline = audit(spec)  # Validate every input policy before making a study.
    if len(baseline['policies']) * len(windows) > 128:
        raise InvalidInput('Study is limited to 128 policy/window combinations')
    result = {'version': 1, 'reference_fields': baseline['reference_fields'],
              'assumption': baseline['assumption'], 'delivery_count': baseline['delivery_count'],
              'windows': windows, 'limits': limits, 'policies': []}
    for policy in spec['policies']:
        evaluations, previous = [], None
        for window in windows:
            candidate = dict(policy, window_seconds=window)
            evaluation = audit(dict(spec, policies=[candidate]))['policies'][0]
            counts = evaluation['counts']
            evaluation['within_limits'] = all(counts.get(k, 0) <= value for k, value in limits.items())
            evaluation['changes_from_previous'] = []
            if previous is not None:
                for old, new in zip(previous['rows'], evaluation['rows']):
                    if (old['status'], old['witness']) != (new['status'], new['witness']):
                        evaluation['changes_from_previous'].append({
                            'id': new['id'], 'from_status': old['status'], 'to_status': new['status'],
                            'from_witness': old['witness'], 'to_witness': new['witness']})
            evaluations.append(evaluation)
            previous = evaluation
        result['policies'].append({'name': policy['name'], 'fields': policy['fields'],
                                   'evaluations': evaluations})
    return result


def window_label(window):
    return 'Whole input' if window is None else f'{window:g}s'


def render_study(result):
    """Native comparison, with explicit unresolved counts and bounded claims."""
    row_height = 72
    panel_height = 150 + row_height * len(result['windows'])
    height = 240 + len(result['policies']) * panel_height
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-label="Retention-window study">',
             f'<rect width="1000" height="{height}" fill="#f9f5ed"/>']
    def text(x, y, value, size=27, color='#243243', bold=False, limit=60):
        value = str(value)
        shown = value if len(value) <= limit else value[:limit-3] + '...'
        parts.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="{color}" font-weight="{700 if bold else 400}"><title>{escape(value)}</title>{escape(shown)}</text>')
    text(36, 45, 'KEY BOUNDARY / RETENTION WINDOWS', 24, '#596b7d', True)
    text(36, 103, 'How long should a key remember?', 44, bold=True)
    text(36, 146, f"{result['delivery_count']} deliveries. {len(result['windows'])} windows. Same action identity.", 28)
    limits = result['limits']
    text(36, 184, f"Limits: {limits['false_merge']} wrong drops / {limits['false_split']} repeats / {limits['unresolved']} unresolved", 23)
    for index, policy in enumerate(result['policies']):
        top = 205 + index * panel_height
        text(36, top+37, policy['name'], 34, bold=True, limit=47)
        for x, label in [(36,'Retention'),(274,'Wrong drops'),(500,'Repeats'),(667,'Unresolved'),(856,'Fits')]:
            text(x, top+83, label, 24, '#596b7d')
        for row_index, evaluation in enumerate(policy['evaluations']):
            y = top+102 + row_index*row_height
            fit = evaluation['within_limits']
            parts.append(f'<rect x="24" y="{y}" width="952" height="62" rx="9" fill="{"#dcefe5" if fit else "#f5e4df"}"/>')
            text(36,y+41,window_label(evaluation['window_seconds']),28,bold=True)
            for x,key in [(325,'false_merge'),(534,'false_split'),(723,'unresolved')]:
                count = evaluation['counts'].get(key,0)
                text(x,y+41,count,32,'#9e283b' if count > limits[key] else '#243243',True)
            text(865,y+41,'YES' if fit else 'NO',26,'#255c46' if fit else '#9e283b',True)
    text(36,height-21,'Fits applies to these deliveries. Full witnesses in JSON.',23)
    parts.append('</svg>')
    return '\n'.join(parts)


def parse_windows(value):
    try:
        return validate_windows([None if v.strip() == 'all' else float(v) for v in value.split(',')])
    except (ValueError, InvalidInput) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--windows', required=True, type=parse_windows, help='Comma-separated seconds; all means whole-input retention')
    parser.add_argument('--max-wrong-drops', type=int, default=0)
    parser.add_argument('--max-repeat-admits', type=int, default=0)
    parser.add_argument('--max-unresolved', type=int, default=0)
    parser.add_argument('--out', required=True, type=Path, help='New output directory')
    args = parser.parse_args()
    try:
        result = study(read_spec(args.input), args.windows, max_wrong_drops=args.max_wrong_drops,
                       max_repeat_admits=args.max_repeat_admits, max_unresolved=args.max_unresolved)
        svg = render_study(result)
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/'window-study.json').write_text(json.dumps(result, indent=2)+'\n')
        (args.out/'window-study.svg').write_text(svg)
    except (InvalidInput, OSError, json.JSONDecodeError) as error:
        parser.exit(2, str(error)+'\n')
    print(json.dumps({p['name']: [window_label(e['window_seconds']) for e in p['evaluations'] if e['within_limits']]
                      for p in result['policies']}, indent=2))


if __name__ == '__main__':
    main()
