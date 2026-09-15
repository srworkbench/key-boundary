"""A compact witness view derived from an audit, not a fixed demonstration."""
from html import escape


def witnesses(result):
    """Select the first observed disagreement of each kind, in policy order."""
    selected = {}
    for policy in result['policies']:
        rows = {row['id']: row for row in policy['rows']}
        for row in policy['rows']:
            status = row['status']
            if status in ('false_merge', 'false_split') and status not in selected:
                selected[status] = (policy, rows[row['witness']], row)
    return selected


def render_focus(result):
    selected = witnesses(result)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1150" viewBox="0 0 900 1150" role="img" aria-label="Key Boundary selected failure witnesses">',
             '<rect width="900" height="1150" fill="#faf6ed"/>']

    def text(x, y, value, size=28, color='#202a36', bold=False, limit=48):
        value = str(value)
        shown = value if len(value) <= limit else value[:limit-1] + '…'
        parts.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}"><title>{escape(value)}</title>{escape(shown)}</text>')

    text(42, 48, 'KEY BOUNDARY / SELECTED WITNESSES', 24, '#506276', True)
    text(42, 112, 'What does your key throw away?', 42, bold=True)
    text(42, 153, 'Compare decisions against your action identity.', 27)
    for index, status in enumerate(('false_merge', 'false_split')):
        y = 192 + index * 432
        color = '#ae293c' if status == 'false_merge' else '#965409'
        parts.append(f'<rect x="28" y="{y}" width="844" height="406" rx="18" fill="#ffffff" stroke="{color}" stroke-width="2"/>')
        label = 'WRONG DROP' if status == 'false_merge' else 'REPEAT ADMISSION'
        text(50, y+43, label, 25, color, True)
        if status not in selected:
            text(50, y+115, 'No witness in this audit.', 34, bold=True)
            text(50, y+164, 'This is not proof that the rule is safe.', 28)
            continue
        policy, earlier, current = selected[status]
        text(50, y+89, policy['name'], 33, bold=True, limit=39)
        text(50, y+126, 'Earlier -> later: ' + earlier['id'] + ' -> ' + current['id'], 24, limit=62)
        group = 'reference_values'
        preferred = next(iter(current[group]))
        if 'false_merge' in selected:
            _, old_merge, new_merge = selected['false_merge']
            preferred = next(p for p in new_merge[group] if new_merge[group][p] != old_merge[group][p])
        field = next((p for p in current[group] if current[group][p] != earlier[group][p]), preferred)
        text(50, y+171, 'ACTION FIELD: ' + field, 23, '#506276', limit=60)
        text(50, y+212, earlier[group][field] + '  ->  ' + current[group][field], 32, bold=True, limit=38)
        group = 'candidate_values'
        key_field = next((p for p in current[group] if current[group][p] != earlier[group][p]), next(iter(current[group])))
        text(50, y+251, 'KEY FIELD: ' + key_field, 23, '#506276', limit=60)
        text(50, y+292, earlier[group][key_field] + '  ->  ' + current[group][key_field], 32, bold=True, limit=38)
        if status == 'false_merge':
            outcome = 'Different action. Same key. Suppressed.'
        elif earlier[group] == current[group]:
            outcome = 'Same action. Key expired. Admitted again.'
        else:
            outcome = 'Same action. New key. Admitted again.'
        text(50, y+345, outcome, 29, color, True, limit=51)
        text(50, y+381, 'Selected fields shown; complete values in audit.json.', 22, '#506276', limit=65)
    text(42, 1103, 'Inspect the witness before changing the rule.', 30, bold=True)
    parts.append('</svg>')
    return '\n'.join(parts)
