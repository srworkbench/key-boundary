"""Render the audit's computed decisions as a native SVG comparison."""
from html import escape

COLORS = {'accepted': '#4de0b0', 'duplicate': '#83a7c5', 'false_merge': '#ff727e', 'false_split': '#ffbc69', 'unresolved': '#d4b2ff'}
LABELS = {'accepted': 'ADMIT', 'duplicate': 'DUPLICATE', 'false_merge': 'WRONG DROP', 'false_split': 'REPEAT ADMIT', 'unresolved': 'REVIEW'}


def render_svg(result):
    policies = result['policies']
    width = max(1080, 170 + 295 * len(policies))
    height = 300 + 66 * result['delivery_count']
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Key Boundary audit comparison">',
             f'<rect width="{width}" height="{height}" fill="#0b1321"/>']
    def text(x,y,value,size=16,color='#e8f0fa',weight=400):
        parts.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(str(value))}</text>')
    text(36,44,'KEY BOUNDARY / DUPLICATE RULE AUDIT',16,'#4de0b0',700)
    text(36,91,'Same deliveries. Different work survives.',34,weight=700)
    text(36,123,'Wrong drop = a different action lost. Repeat admit = the same action admitted again.',16,'#afc1d8')
    text(36,153,'Decisions are conditional on your reference identity. Input order is arrival order.',14,'#afc1d8')
    for column, policy in enumerate(policies):
        x = 175 + 295 * column
        text(x,195,policy['name'][:28],21,weight=700)
        c = policy['counts']
        text(x,221,f"{c.get('false_merge',0)} wrong drops / {c.get('false_split',0)} repeat admits",14,'#afc1d8')
        for index, row in enumerate(policy['rows']):
            y = 240 + 66 * index
            color = COLORS[row['status']]
            parts.append(f'<rect x="{x}" y="{y}" width="270" height="56" rx="8" fill="#162338"/>')
            text(x+13,y+23,LABELS[row['status']],15,color,700)
            text(x+13,y+44,('matches ' + row['witness'])[:34] if row['witness'] else ('Missing identity or key' if row['status'] == 'unresolved' else 'First admission'),12,'#afc1d8')
            if column == 0:
                text(36,y+24,row['id'][:16],16,weight=700)
                text(36,y+43,str(row['at'])+'s',12,'#afc1d8')
    text(36,height-18,'Whole-input reference identity / Fixed expiry from admission / Full witnesses in audit.json',13,'#afc1d8')
    parts.append('</svg>')
    return '\n'.join(parts)


def render_html(result):
    """Static field-level evidence, with no scripts, uploads or network resources."""
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Key Boundary evidence</title>',
             '<style>body{font:17px/1.5 system-ui;background:#0b1321;color:#e8f0fa;margin:24px auto;padding:0 20px;max-width:1000px}article{background:#162338;padding:20px;margin:16px 0;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #34465e;overflow-wrap:anywhere}h3{margin-top:0}code{white-space:pre-wrap}svg{width:100%;height:auto} .changed{background:#50303a}p{color:#afc1d8}</style>',
             '<h1>Which deliveries does your key collapse?</h1><p>Inspect the selected fields beside the earlier delivery that explains each decision. Highlighted rows differ. Values retain their JSON types; unresolved means missing, empty, null or nonscalar.</p>', render_svg(result)]
    for policy in result['policies']:
        parts.append('<h2>' + escape(policy['name']) + '</h2>')
        rows_by_id = {r['id']: r for r in policy['rows']}
        for row in policy['rows']:
            parts.append('<article><h3>' + escape(row['id']) + ' / ' + LABELS[row['status']] + '</h3><p>' + escape(row['reason']) + '</p>')
            previous = rows_by_id.get(row['witness'])
            if previous:
                parts.append('<p>Earlier delivery: ' + escape(previous['id']) + '</p>')
            for label, group in [('Reference identity','reference_values'), ('Candidate key','candidate_values')]:
                parts.append('<h4>'+label+'</h4><table><tr><th>Field</th><th>This delivery</th><th>Earlier delivery</th></tr>')
                for field, value in row[group].items():
                    old = previous[group].get(field) if previous else None
                    changed = previous is not None and value != old
                    cls = ' class="changed"' if changed else ''
                    show = lambda v: escape(v if v is not None else '(unresolved)')
                    parts.append('<tr'+cls+'><td><code>'+escape(field)+'</code></td><td><code>'+show(value)+'</code></td><td><code>'+(show(old) if previous else '—')+'</code></td></tr>')
                parts.append('</table>')
            parts.append('</article>')
    parts.append('</html>')
    return '\n'.join(parts)
